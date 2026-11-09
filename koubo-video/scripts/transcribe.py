#!/usr/bin/env python3
"""Word-level Chinese transcript (whisper.cpp) refined with silence detection.

  python3 transcribe.py <video|wav> --out <dir> [--name source] [--model large-v3|small|PATH]

Outputs <dir>/<name>.words.json and <dir>/<name>.md. The .md is the reading view for the
agent: one line per sentence with time range, word index range, inline gap markers
(‹静0.32› silence, ‹声0.41› sound with no recognised word — often 呃/嗯 that whisper dropped)
and a list of heuristic hints. Cached: rerunning with the same input/model/prompt is free.
"""

import argparse
import array
import hashlib
import json
import os
import re
import statistics
import subprocess
import wave
from pathlib import Path

from vdp_common import CFG, IS_WIN, MODEL_DIR, SETTINGS_DIR, SKILL_DIR, die, run, run_err, save_json, scan_issues, tool, write_srt

PUNCT = set("，。,.!?！？、:：;；\"“”'‘’…·")
FINAL = set("。！？!?.")


def model_path(m):
    p = Path(m).expanduser()
    if p.exists():
        return p
    p = MODEL_DIR / f"ggml-{m}.bin"
    if not p.exists():
        die(f"找不到模型 {p}；可选：" + ", ".join(x.stem[5:] for x in MODEL_DIR.glob("ggml-*.bin")))
    return p


def build_prompt(dict_files):
    """个人词典在前（更重要），skill 自带的基础词典在后；whisper 提示词有长度上限。"""
    terms = []
    for f in dict_files:
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines():
                t = line.strip()
                if t and not t.startswith("#") and t not in terms:
                    terms.append(t)
    if IS_WIN and not windows_utf8_args():
        # whisper.cpp 在 Windows 上按系统代码页（中文系统是 GBK）接收命令行参数，再当 UTF-8 用：
        # 中文提示词会变成乱码。只传纯英文的词（任何代码页里都一样），繁简由 to_simplified 兜底。
        return ", ".join(t for t in terms if t.isascii())[:200]
    p = "以下是普通话口播，使用简体中文，如实保留口语和语气词，嗯，呃，这个，那个。"
    if terms:
        p += "常用词：" + "、".join(terms)
    return p[:160]


def windows_utf8_args():
    try:
        import ctypes
        return ctypes.windll.kernel32.GetACP() == 65001
    except Exception:  # noqa: BLE001
        return False


def to_simplified(text):
    """没有中文提示词时 whisper 偶尔输出繁体；装了 zhconv 就转成简体（setup.py 在 Windows 上会装）。"""
    try:
        import zhconv
        return zhconv.convert(text, "zh-cn")
    except ImportError:
        return text


def silences(wav, noise_db, min_d):
    err = run_err([tool("ffmpeg"), "-hide_banner", "-i", str(wav), "-af",
                   f"silencedetect=noise={noise_db}dB:d={min_d}", "-f", "null", "-"])
    out, start = [], None
    for line in err.splitlines():
        if m := re.search(r"silence_start: (-?[\d.]+)", line):
            start = max(0.0, float(m.group(1)))
        elif (m := re.search(r"silence_end: ([\d.]+)", line)) and start is not None:
            out.append([round(start, 3), round(float(m.group(1)), 3)])
            start = None
    return out


def overlap(a, b, sil):
    return sum(max(0.0, min(b, e) - max(a, s)) for s, e in sil)


def whisper_cmd(model):
    """-dtw 给出声学对齐的字起点；新版 whisper.cpp 默认开 flash attention，开着时 DTW 静默不出，要 -nfa 关掉。
    旧版本没有 -nfa（默认就是关的），不能硬传。"""
    cli = tool("whisper-cli")
    p = subprocess.run([cli, "--help"], capture_output=True, encoding="utf-8", errors="replace")
    help_text = (p.stdout or "") + (p.stderr or "")
    if "-dtw" not in help_text:
        die("whisper-cli 版本太旧，不支持 -dtw；运行 setup.py install 升级")
    threads = str(max(4, min(8, os.cpu_count() or 4)))
    return [cli, "-m", str(model), "-l", "zh", "-t", threads] + (["-nfa"] if "-nfa" in help_text else []) \
        + ["-dtw", dtw_preset(model)]


def dtw_preset(model):
    """whisper.cpp -dtw preset name for a model file (ggml-large-v3.bin → large.v3)."""
    name = re.sub(r"-q\d.*$", "", Path(model).stem.removeprefix("ggml-"))
    return name.replace("-", ".")


def parse_tokens(whisper_json, duration):
    """Words with acoustic onsets from DTW (t_dtw). Without DTW whisper spreads token times
    evenly across a segment, which drifts by seconds on long takes — never cut on those."""
    raw = Path(whisper_json).read_bytes().decode("utf-8", errors="surrogateescape")
    data = json.loads(raw, strict=False)
    words, buf, buf_t, buf_p = [], b"", None, []
    have_dtw = False
    for seg in data.get("transcription", []):
        for tok in seg.get("tokens", []):
            text = tok.get("text", "")
            if text.startswith("[_") or re.fullmatch(r"\[.*\]", text.strip() or "x"):
                continue
            t = tok.get("t_dtw", -1)
            have_dtw |= t is not None and t >= 0
            onset = t / 100 if t is not None and t >= 0 else tok["offsets"]["from"] / 1000
            if buf_t is None:
                buf_t = onset
            buf += text.encode("utf-8", errors="surrogateescape")
            buf_p.append(tok.get("p", 1.0))
            try:
                s = buf.decode("utf-8")
            except UnicodeDecodeError:
                if len(buf) < 12:
                    continue          # 中文字被拆成多个字节 token，继续拼
                s = buf.decode("utf-8", errors="replace")
            words.append({"text": to_simplified(s) if IS_WIN else s, "start": buf_t, "seg_end": seg["offsets"]["to"] / 1000,
                          "p": round(min(buf_p), 2)})
            buf, buf_t, buf_p = b"", None, []
    if not have_dtw:
        print("⚠ whisper 没有输出 DTW 时间戳，字级时间不可靠", flush=True)
    out = []
    for w in words:                   # 标点并入前一个词
        t = w["text"].strip()
        if not t:
            continue
        if all(ch in PUNCT for ch in t):
            if out:
                out[-1]["punct"] = out[-1].get("punct", "") + t
            continue
        w["space"] = w["text"].startswith(" ")
        w["text"] = t
        out.append(w)
    for i, w in enumerate(out):       # 字尾 = 下一个字的起点（之后再用静音收紧）
        nxt = out[i + 1]["start"] if i + 1 < len(out) else min(duration, w["seg_end"] + 0.3)
        w["end"] = max(nxt, w["start"] + 0.04)
        del w["seg_end"]
    return out


def refine(words, sil, duration):
    """Tighten word ends to the start of a following silence and cap implausibly long words,
    so pauses and untranscribed sounds (呃/嗯) show up as gaps instead of hiding inside words."""
    for w in words:
        for s, e in sil:
            if w["start"] < s < w["end"]:
                w["end"] = min(w["end"], s + 0.02)
            if s <= w["start"] < e and e < w["end"]:
                w["start"] = e - 0.02          # 起点落在静音尾巴里
        n = len(w["text"]) if not w["text"].isascii() else max(1, len(w["text"]) / 3)
        cap = 0.35 + 0.2 * n
        if w["end"] - w["start"] > cap:
            w["long"] = round(w["end"] - w["start"], 2)
            w["end"] = w["start"] + cap
        w["start"], w["end"] = round(w["start"], 3), round(min(duration, max(w["end"], w["start"] + 0.04)), 3)
    return words


def needs_space(prev_text, w):
    return bool(prev_text) and w.get("space") and prev_text[-1:].isascii() and prev_text[-1:].isalnum()


def join(ws):
    s = ""
    for w in ws:
        s += (" " if needs_space(s, w) else "") + w["text"] + w.get("punct", "")
    return s


class Loudness:
    """RMS of the 16 kHz mono wav, to tell a voiced 呃/嗯 from a breath in an unrecognised gap."""

    def __init__(self, wav):
        with wave.open(str(wav)) as f:
            self.rate = f.getframerate()
            self.a = array.array("h", f.readframes(f.getnframes()))

    def rms(self, t0, t1):
        seg = self.a[int(t0 * self.rate):int(t1 * self.rate)]
        return (sum(x * x for x in seg[::4]) / max(1, len(seg[::4]))) ** 0.5 if len(seg) else 0.0


def build(words, sil, split_gap, loud):
    speech = statistics.median([loud.rms(w["start"], w["end"]) for w in words]) or 1.0
    gaps, sentences, cur = [], [], []
    for i, w in enumerate(words):
        w["i"] = i
        if cur:
            prev = words[i - 1]
            g = w["start"] - prev["end"]
            if g >= 0.12:
                if overlap(prev["end"], w["start"], sil) / g >= 0.6:
                    kind = "静"
                else:  # 有能量但没识别出字：响度接近说话 → 多半是呃/嗯；明显更轻 → 吸气/底噪
                    kind = "声" if loud.rms(prev["end"], w["start"]) / speech >= 0.35 else "气"
                gaps.append({"after": i - 1, "start": prev["end"], "end": w["start"], "dur": round(g, 2), "kind": kind})
            # 按标点切成短句（重录/口头禅比对以短句为单位），长停顿也切
            if g >= split_gap or (prev.get("punct") and len(join(cur)) >= 3):
                sentences.append(cur)
                cur = []
        cur.append(w)
    if cur:
        sentences.append(cur)
    gap_after = {g["after"]: g for g in gaps}
    sents = []
    for n, ws in enumerate(sentences, 1):
        pieces = []
        for w in ws:
            sp = " " if needs_space("".join(pieces), w) else ""
            pieces.append(sp + w["text"] + ("[?]" if w["p"] < 0.3 else "") + w.get("punct", ""))
            g = gap_after.get(w["i"])
            if g and w is not ws[-1] and g["dur"] >= 0.25:
                pieces.append(f"‹{g['kind']}{g['dur']:.2f}›")
        text_marked = "".join(pieces)
        last = gap_after.get(ws[-1]["i"])
        sents.append({"id": f"S{n:02}", "start": ws[0]["start"], "end": ws[-1]["end"],
                      "w": [ws[0]["i"], ws[-1]["i"]], "text": join(ws), "marked": text_marked,
                      "after": f"{last['kind']}{last['dur']:.2f}" if last else ""})
    return gaps, sents


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--name", default="source")
    ap.add_argument("--model", default=CFG["model"], help="large-v3 / large-v3-turbo / small / 模型文件路径")
    ap.add_argument("--dict", type=Path, action="append", help="额外的词典文件；默认 个人设置/词典.txt + skill 基础词典")
    ap.add_argument("--noise", default="-35", help="silencedetect 阈值 dB；底噪大时调到 -30")
    ap.add_argument("--split-gap", type=float, default=0.45)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    out = args.out.expanduser()
    out.mkdir(parents=True, exist_ok=True)
    src = args.input.expanduser()
    wav = src
    if src.suffix.lower() != ".wav":
        wav = out / f"{args.name}.16k.wav"
        run([tool("ffmpeg"), "-v", "error", "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000",
             "-c:a", "pcm_s16le", str(wav)])
    model = model_path(args.model)
    prompt = build_prompt((args.dict or []) + [SETTINGS_DIR / "词典.txt", SKILL_DIR / "references/词典.txt"])
    st = src.stat()
    key = hashlib.sha1(json.dumps([str(src), st.st_size, int(st.st_mtime), str(model), prompt,
                                   args.noise, args.split_gap]).encode()).hexdigest()
    words_json = out / f"{args.name}.words.json"
    stem = out / f"{args.name}.whisper"
    keyfile = Path(f"{stem}.key")
    # 只缓存 whisper 这一步（耗时）；分句、静音、提示每次都重算（便宜，且规则会迭代）
    if args.force or not Path(f"{stem}.json").exists() or not keyfile.exists() or keyfile.read_text() != key:
        # 在输出目录里用相对路径调用：Windows 上 whisper.cpp 对非 GBK 字符的路径会打不开
        try:
            rel_wav = os.path.relpath(wav, out)
        except ValueError:            # Windows 上跨盘符
            rel_wav = str(wav)
        log = run(whisper_cmd(model) + ["-ojf", "-of", stem.name, "-f", rel_wav]
                  + (["--prompt", prompt] if prompt else []), check=False, cwd=out)
        if not Path(f"{stem}.json").exists():
            die(f"whisper 没有产出：{log[-800:]}")
        keyfile.write_text(key)
    else:
        print("· whisper 结果未变，复用缓存")
    dur = float(run([tool("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(wav)]))
    sil = silences(wav, args.noise, 0.12)
    words = refine(parse_tokens(f"{stem}.json", dur), sil, dur)
    if not words:
        die("没有识别出任何文字")
    gaps, sents = build(words, sil, args.split_gap, Loudness(wav))
    hints = scan_issues(sents)
    for g in gaps:
        if g["kind"] == "声" and g["dur"] >= 0.35:  # 更短的多是时间戳漂移
            hints.append({"type": "有声无字", "at": g["start"], "sid": "", "text": f"{g['dur']:.2f}s（疑似呃/嗯或漏识别的字，剪前可用 transcribe 局部复核）"})
    hints.sort(key=lambda h: h["at"])

    save_json({"source": str(src), "model": model.name, "prompt": prompt, "duration": dur,
               "words": words, "gaps": gaps, "silences": sil, "sentences": sents, "hints": hints}, words_json)
    lines = [f"# 转写：{src.name}", f"模型 {model.name} · 时长 {dur:.2f}s · 时间均为本文件时间轴（秒）",
             "", "## 全文", "", "".join(s["text"] for s in sents), "",
             "## 分句（S编号 [开始-结束] 词号范围 文本；‹静x›=静音 ‹气x›=吸气/底噪 ‹声x›=有声无字（疑似呃/嗯）；[?]=低置信；行尾=句后停顿）", ""]
    for s in sents:
        lines.append(f"{s['id']} [{s['start']:07.2f}-{s['end']:07.2f}] w{s['w'][0]}-w{s['w'][1]}  {s['marked']}"
                     + (f"  ⏸{s['after']}" if s["after"] else ""))
    lines += ["", "## 待查提示（启发式，只指出值得看的位置，去留由你按口误规则判断）", ""]
    lines += [f"- {h['at']:07.2f} {h['type']} {h['sid']}：{h['text']}" for h in hints] or ["- 无"]
    (out / f"{args.name}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_srt([{"start": x["start"], "end": x["end"], "zh": x["text"]} for x in sents], out / f"{args.name}.srt", "zh")
    print(f"✓ {len(words)} 词 / {len(sents)} 句 / {len(hints)} 条提示 → {out / (args.name + '.md')}")


if __name__ == "__main__":
    main()
