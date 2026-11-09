#!/usr/bin/env python3
"""Automatic checks on the rendered versions. Exit code 1 if anything FAILs — a check that
could not run counts as failed, never as passed.

  python3 verify.py --work <dir> [--transcribe]

Reads <work>/render.json (outputs), <work>/cut.json (expected duration), <work>/captions.json.
Checks: full decode, duration vs. EDL, A/V stream lengths, loudness, caption completeness,
and — when both versions exist — the diary header present at start/middle/end of the diary
version and absent from the plain one. Writes <work>/check/contact.png (frames at 0.5 s / 25 /
50 / 75 % / end for each version — look at this one image) and <work>/check/check.json. With
--transcribe it also re-transcribes the plain version and lists residue hints (残字、重复).
"""

import argparse
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageStat

from vdp_common import ENGLISH, font_spec, load_json, probe, run, run_err, save_json, tool


def frame(video, t, path):
    run([tool("ffmpeg"), "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", str(path)])
    return Image.open(path).convert("RGB")


def loudness(video):
    err = run_err([tool("ffmpeg"), "-hide_banner", "-nostats", "-i", str(video), "-af",
                   "ebur128=peak=true", "-f", "null", "-"])
    summary = err[err.rfind("Summary:"):]
    i = tp = None
    for line in summary.splitlines():
        line = line.strip()
        if line.startswith("I:"):
            i = float(line.split()[1])
        elif line.startswith("Peak:"):
            tp = float(line.split()[1])
    return i, tp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--transcribe", action="store_true", help="成片再转写一遍，列出残字/重复提示")
    args = ap.parse_args()
    work = args.work.expanduser()
    chk = work / "check"
    chk.mkdir(exist_ok=True)
    results, fails = [], 0

    def add(name, ok, detail, warn=False):
        nonlocal fails
        status = "PASS" if ok else ("WARN" if warn else "FAIL")
        fails += status == "FAIL"
        results.append({"check": name, "status": status, "detail": detail})
        print(f"{'✓' if ok else ('⚠' if warn else '✗')} {name}：{detail}")

    try:
        render = load_json(work / "render.json")
        cut = load_json(work / "cut.json")
        caps = load_json(work / "captions.json")["items"]
    except Exception as e:  # noqa: BLE001
        print(f"✗ 读不到 render.json / cut.json / captions.json：{e}")
        sys.exit(1)
    expected = cut["expected_duration"]
    outs = render["outputs"]
    if "social" in outs:              # 旧版 render.json 的叫法
        outs["plain"] = outs.pop("social")

    for kind, o in outs.items():
        v = Path(o["path"])
        err = run_err([tool("ffmpeg"), "-v", "error", "-i", str(v), "-f", "null", "-"]).strip()
        add(f"{kind} 解码", not err, "无错误" if not err else err[-300:])
        info = probe(v)
        vd, ad = info.get("v_duration") or info["duration"], info.get("a_duration") or 0
        add(f"{kind} 时长", abs(vd - expected) < 0.1, f"视频 {vd:.2f}s / 音频 {ad:.2f}s / 剪辑预期 {expected:.2f}s")
        add(f"{kind} 音画长度", abs(vd - ad) < 0.08, f"差 {abs(vd - ad) * 1000:.0f}ms")
        i, tp = loudness(v)
        ok_l = i is not None and -16 <= i <= -12 and tp is not None and tp <= -0.5
        add(f"{kind} 响度", ok_l, f"{i} LUFS / 峰值 {tp} dBFS（目标 -14 / ≤-1）", warn=i is not None)

    missing = [c["id"] for c in caps if not c.get("zh", "").strip() or (ENGLISH and not c.get("en", "").strip())]
    add("字幕完整", not missing, f"{len(caps)} 条" + (f"，缺字：{missing}" if missing else
                                                    ("，中英齐全" if ENGLISH else "，中文齐全")))

    # 抽帧拼图 + 日记标识检查
    dur = expected
    times = [0.5, dur * 0.25, dur * 0.5, dur * 0.75, max(0.5, dur - 0.3)]
    rows = {}
    for kind, o in outs.items():
        rows[kind] = [frame(o["path"], t, chk / f"{kind}_{n}.png") for n, t in enumerate(times)]
    if "diary" in rows and "plain" in rows:
        diffs = []
        for a, b in zip(rows["diary"], rows["plain"]):
            top = (0, 0, a.width, int(a.height * 0.17))
            diffs.append(ImageStat.Stat(ImageChops.difference(a.crop(top), b.crop(top)).convert("L")).mean[0])
        add("日记标识", all(d > 8 for d in (diffs[0], diffs[2], diffs[-1])),
            "开头/中段/结尾顶部差异 " + " / ".join(f"{d:.0f}" for d in diffs))
    thumb_w = 216
    names = list(rows)
    sheet = Image.new("RGB", (thumb_w * len(times) + 20, (int(thumb_w * 16 / 9) + 40) * len(names) + 10), "white")
    d = ImageDraw.Draw(sheet)
    zh_path, zh_idx = font_spec("zh")
    f = ImageFont.truetype(zh_path, 18, index=zh_idx)
    for r, kind in enumerate(names):
        y0 = r * (int(thumb_w * 16 / 9) + 40) + 30
        d.text((10, y0 - 26), f"{kind}", font=f, fill="black")
        for c, im in enumerate(rows[kind]):
            t = im.resize((thumb_w, int(thumb_w * im.height / im.width)))
            sheet.paste(t, (10 + c * thumb_w, y0))
            d.text((14 + c * thumb_w, y0 + 4), f"{times[c]:.1f}s", font=f, fill="yellow")
    sheet.save(chk / "contact.png")
    print(f"· 抽帧拼图：{chk / 'contact.png'}（看字幕是否压脸、标识日期/Day 是否正确）")

    if args.transcribe and outs:
        final = (outs.get("plain") or next(iter(outs.values())))["path"]
        tr = subprocess.run([sys.executable, str(Path(__file__).with_name("transcribe.py")), final,
                             "--out", str(work / "transcript"), "--name", "final"],
                            capture_output=True, encoding="utf-8", errors="replace")
        if tr.returncode != 0:
            add("成片转写", False, tr.stderr[-300:])
        else:
            hints = load_json(work / "transcript/final.words.json")["hints"]
            add("成片残留扫描", not hints, "无提示" if not hints else
                "；".join(f"{h['at']:.1f}s {h['type']} {h['text']}" for h in hints), warn=True)
            print(f"· 成片转写：{work / 'transcript/final.md'}（通读一遍，看接缝处有无残字、重复、断句）")

    save_json({"results": results, "fails": fails}, chk / "check.json")
    print(f"{'✓ 全部通过' if not fails else f'✗ {fails} 项未通过'}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
