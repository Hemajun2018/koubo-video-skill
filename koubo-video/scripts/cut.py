#!/usr/bin/env python3
"""Cut the source by keep ranges: snap edges to quiet valleys, frame-align, 30 ms fades, -14 LUFS.

  python3 cut.py --work <dir> --edl <dir>/edl.json [--out <dir>/cut.mp4]

edl.json (times = source seconds, taken from the transcript's word/sentence times):
  {"keep": [{"start": 0.09, "end": 7.13, "note": "S01-S04"}, ...],
   "cuts": [{"start": 7.13, "end": 9.40, "reason": "重录：S05 被 S06 完整重说"}]}   ← cuts 只做记录

Whisper word edges drift 0.1–0.3 s, so every edge is moved to the quietest 20 ms frame within
±snap seconds (never cutting inside a word even if the timestamp is off), then onto the frame
grid so audio and video segments have identical length (no cumulative A/V drift).
"""

import argparse
import json
import re
from pathlib import Path

from vdp_common import die, load_json, probe, run, run_err, save_json, tool
from transcribe import Loudness

KEEP_SIDE = 0.02  # 剪辑点最多往后挪这么多


def norm_keep(edl):
    out = []
    for k in edl["keep"]:
        s, e = (k["start"], k["end"]) if isinstance(k, dict) else (k[0], k[1])
        out.append([float(s), float(e)])
    return sorted(out)


def valley(loud, t, back, fwd, lo, hi):
    """Quietest 20 ms frame in [t-back, t+fwd] (asymmetric: search earlier, barely later)."""
    win = max(back, fwd)
    a, b = max(lo, t - back), min(hi, t + fwd)
    best, best_t, x = None, t, a
    while x + 0.02 <= b:
        r = loud.rms(x, x + 0.02)
        # 轻微偏向原位置，避免在一片安静里漂太远
        score = r * (1 + 0.5 * abs(x + 0.01 - t) / max(win, 1e-6))
        if best is None or score < best:
            best, best_t = score, x + 0.01
        x += 0.01
    return best_t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--edl", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--snap", type=float, default=0.12, help="剪辑点吸附窗口（秒），0 关闭")
    ap.add_argument("--lufs", type=float, default=-14.0, help="响度目标；传 0 关闭")
    ap.add_argument("--crf", default="14", help="中间文件，最终导出还会再编码一次，所以给高质量+快速预设")
    args = ap.parse_args()

    work = args.work.expanduser()
    src = load_json(work / "source.json")
    edl_path = (args.edl or work / "edl.json").expanduser()
    edl = load_json(edl_path)
    out = (args.out or work / "cut.mp4").expanduser()
    dur, fps = src["duration"], src.get("fps") or 30.0
    keep = norm_keep(edl)
    for (s, e), nxt in zip(keep, keep[1:] + [[dur + 1, 0]]):
        if not (0 <= s < e <= dur + 0.05):
            die(f"区间超出素材范围或起止颠倒：{s}-{e}（素材 {dur:.2f}s）")
        if e > nxt[0]:
            die(f"区间重叠：{s}-{e} 与 {nxt[0]}")

    loud = Loudness(work / "audio16k.wav")
    final = []
    for i, (s, e) in enumerate(keep):
        lo = keep[i - 1][1] if i else 0.0
        hi = keep[i + 1][0] if i + 1 < len(keep) else dur
        # 转写里的时间是字的起点（DTW）：保留段起点=首字起点，终点=下一个（被删）字的起点。
        # 两种边都只该往前找安静处；往后挪会吞进下一个字的开头，留下「就」「这个视」这类残字。
        s2 = valley(loud, s, args.snap, KEEP_SIDE, lo, e) if args.snap and s > 0.05 else s
        e2 = valley(loud, e, args.snap, KEEP_SIDE, s2, hi) if args.snap and e < dur - 0.05 else e
        s2, e2 = round(s2 * fps) / fps, min(round(e2 * fps) / fps, dur)
        if final and s2 - final[-1][1] < 0.05:
            print(f"  ⚠ {keep[i - 1][1]:.2f}-{s:.2f} 的删除吸附后不足 0.05s，已合并保留（删除点太短，需要更精细的定位）")
            final[-1][1] = e2            # 吸附后相接的区间合并
        elif e2 - s2 >= 0.1:
            final.append([s2, e2])
    expected = sum(e - s for s, e in final)

    vparts, aparts, labels = [], [], []
    for i, (s, e) in enumerate(final):
        d = e - s
        # 帧时间是 k/fps，s/e 也在帧格上；按半帧偏移取，避免 4 位小数舍入让段首丢帧、段尾多帧（10/26 累计多 4 帧）
        half = 0.5 / fps
        vparts.append(f"[0:v]trim=start={max(0, s - half):.4f}:end={e - half:.4f},setpts=PTS-STARTPTS[v{i}]")
        aparts.append(f"[0:a]atrim=start={s:.4f}:end={e:.4f},asetpts=PTS-STARTPTS,"
                      f"afade=t=in:st=0:d=0.03,afade=t=out:st={max(0, d - 0.03):.4f}:d=0.03[a{i}]")
        labels.append(f"[v{i}][a{i}]")
    graph = ";".join(vparts + aparts) + f";{''.join(labels)}concat=n={len(final)}:v=1:a=1[v][acat]"
    audio_only = ";".join(aparts) + f";{''.join(f'[a{i}]' for i in range(len(final)))}concat=n={len(final)}:v=0:a=1[acat]"

    rate = str(src.get("sample_rate", 48000))
    loudness = None
    if args.lufs:
        probe_graph = audio_only + f";[acat]loudnorm=I={args.lufs}:TP=-2:LRA=11:print_format=json[a]"
        err = run_err([tool("ffmpeg"), "-hide_banner", "-i", src["local"], "-filter_complex", probe_graph,
                       "-map", "[a]", "-f", "null", "-"])
        found = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", err)
        if not found:
            die(f"响度测量失败：{err[-600:]}")
        m = json.loads(found[-1])
        loudness = {k: m[k] for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")}
        graph += (f";[acat]loudnorm=I={args.lufs}:TP=-2:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}"
                  f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}"
                  f":linear=true,aresample={rate},alimiter=limit=0.708:level=false,atrim=end={expected:.4f}[a]")   # loudnorm 会在尾部补出约 0.1s；限幅 -3 dBFS 防 AAC 后峰值过 0
    else:
        graph += ";[acat]anull[a]"

    run([tool("ffmpeg"), "-v", "error", "-y", "-i", src["local"], "-filter_complex", graph,
         "-map", "[v]", "-map", "[a]", "-r", f"{fps:g}", "-fps_mode", "cfr",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", args.crf, "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-ar", rate, "-movflags", "+faststart", str(out)])

    got = probe(out)
    offset, ranges = 0.0, []
    for s, e in final:
        ranges.append({"src_start": round(s, 3), "src_end": round(e, 3), "out_start": round(offset, 3)})
        offset += e - s
    ok = abs((got.get("v_duration") or got["duration"]) - expected) <= 1.5 / fps + 0.02 \
        and abs(got.get("a_duration", expected) - expected) <= 0.05
    save_json({"source": src["local"], "edl": str(edl_path), "requested": keep, "ranges": ranges,
               "expected_duration": round(expected, 3), "duration": got["duration"],
               "loudness_in": loudness, "lufs_target": args.lufs or None,
               "cuts": edl.get("cuts", [])}, out.with_suffix(".json"))
    removed = dur - expected
    print(f"{'✓' if ok else '✗'} {out.name}: {len(final)} 段，删除 {removed:.2f}s，成片 {got['duration']:.2f}s"
          f"（预期 {expected:.2f}s）" + ("" if ok else "  ← 时长不符，检查后再继续"))
    for (s, e), (s2, e2) in zip(keep, final) if len(keep) == len(final) else []:
        if abs(s - s2) > 0.04 or abs(e - e2) > 0.04:
            print(f"  吸附：{s:.2f}-{e:.2f} → {s2:.2f}-{e2:.2f}")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
