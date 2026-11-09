#!/usr/bin/env python3
"""Caption drafting and SRT export, timed from the transcript of the CUT video.

  python3 subs.py draft --words <work>/transcript/cut.words.json --out <work>/captions.json
  (agent: fix ASR errors in "zh" — only what was actually said — and fill "en")
  python3 subs.py srt --captions <work>/captions.json --out-dir <work>/out --prefix 2026-10-13

Times come from the cut video's own transcript, so they are already on the output timeline.
"""

import argparse
import re
from pathlib import Path

from vdp_common import ENGLISH, die, load_json, save_json, write_srt

TRAIL = "，。,.!！?？、；;：: "


BREAK_BEFORE = ("然后", "因为", "所以", "但是", "而且", "如果", "要是", "甚至", "其实", "就是", "比如",
                "跟", "和", "让", "把", "被", "给", "在", "就", "也", "还", "都", "去", "用")
BREAK_AFTER = ("的话", "了", "的", "啊", "呢", "吧", "吗", "着", "过", "说", "是")


def width(text):
    return sum(0.55 if ch.isascii() else 1 for ch in text)


def split_long(ws, max_zh):
    """Split words into chunks no wider than max_zh, at the most natural break near the middle:
    a pause, before a connective, after a particle; never inside a run of Latin letters."""
    text = "".join(w["text"] for w in ws)
    total = width(text)
    if total <= max_zh or len(ws) < 2:
        return [ws]
    best, best_score, left = 1, None, 0.0
    for i in range(1, len(ws)):
        left += width(ws[i - 1]["text"])
        if left > max_zh or total - left > max_zh * 2:
            continue
        a, b = ws[i - 1]["text"], ws[i]["text"]
        if a[-1:].isascii() and a[-1:].isalnum() and b[:1].isascii() and b[:1].isalnum():
            continue
        score = abs(left - total / 2)
        tail = "".join(w["text"] for w in ws[max(0, i - 2):i])
        head = "".join(w["text"] for w in ws[i:i + 2])
        score -= 4 * min(1.0, max(0.0, ws[i]["start"] - ws[i - 1]["end"] - 0.08) / 0.3)
        if any(head.startswith(x) for x in BREAK_BEFORE):
            score -= 4
        if any(tail.endswith(x) for x in BREAK_AFTER):
            score -= 3
        if ws[i - 1].get("punct"):
            score -= 8
        if best_score is None or score < best_score:
            best, best_score = i, score
    return split_long(ws[:best], max_zh) + split_long(ws[best:], max_zh)


def draft(args):
    data = load_json(args.words)
    words = data["words"]
    items = []
    for s in data["sentences"]:
        ws = words[s["w"][0]:s["w"][1] + 1]
        for chunk in split_long(ws, args.max_zh):
            zh = ""
            for w in chunk:
                if zh and w.get("space") and zh[-1:].isascii() and zh[-1:].isalnum():
                    zh += " "
                zh += w["text"] + w.get("punct", "")
            zh = re.sub(r"[，,、；;]", " ", zh.strip(TRAIL)).strip()
            items.append({"start": chunk[0]["start"], "end": chunk[-1]["end"], "zh": zh, "en": ""})
    dur = data["duration"]
    for c in items:
        c["start"] = round(max(0, c["start"] - 0.05), 2)
    for i, c in enumerate(items):          # 连续显示：没有长停顿就接到下一条，避免闪烁
        nxt = items[i + 1]["start"] if i + 1 < len(items) else dur
        c["end"] = round(min(dur, nxt if nxt - c["end"] < 0.6 else c["end"] + 0.3), 2)
        c["id"] = i + 1
    save_json({"video": data["source"], "duration": dur, "items": items}, args.out)
    print(f"✓ {len(items)} 条字幕草稿 → {args.out}（下一步：校对 zh 只改识别错误"
          + ("，补全 en）" if ENGLISH else "；配置为只要中文字幕，en 留空）"))


def check(items, dur, need_en=ENGLISH):
    problems = []
    for i, c in enumerate(items):
        if not c.get("zh", "").strip():
            problems.append(f"#{c.get('id', i + 1)} 缺中文")
        if need_en and not c.get("en", "").strip():
            problems.append(f"#{c.get('id', i + 1)} 缺英文")
        if c["end"] - c["start"] < 0.4:
            problems.append(f"#{c.get('id', i + 1)} 显示不足 0.4s")
        if i and c["start"] < items[i - 1]["end"] - 0.01:
            problems.append(f"#{c.get('id', i + 1)} 与上一条重叠")
        if c["end"] > dur + 0.05:
            problems.append(f"#{c.get('id', i + 1)} 超出视频时长")
    return problems


def srt(args):
    data = load_json(args.captions)
    items = data["items"]
    problems = check(items, data["duration"])
    if problems:
        die("字幕未通过检查：\n  " + "\n  ".join(problems))
    out = Path(args.out_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    names = [f"{args.prefix}_中文.srt"]
    write_srt(items, out / names[0], "zh")
    if any(c.get("en", "").strip() for c in items):
        names.insert(0, f"{args.prefix}_中英双语.srt")
        write_srt(items, out / names[0], "both")
    print(f"✓ {len(items)} 条 → {out}：{'、'.join(names)}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draft")
    d.add_argument("--words", type=Path, required=True)
    d.add_argument("--out", type=Path, required=True)
    d.add_argument("--max-zh", type=int, default=16, help="每条中文最多字数（英文按半个字算）")
    s = sub.add_parser("srt")
    s.add_argument("--captions", type=Path, required=True)
    s.add_argument("--out-dir", required=True)
    s.add_argument("--prefix", required=True)
    args = ap.parse_args()
    draft(args) if args.cmd == "draft" else srt(args)


if __name__ == "__main__":
    main()
