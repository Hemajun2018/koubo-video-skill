#!/usr/bin/env python3
"""Copy finished deliverables into <成品>/<date>/ without overwriting, verify the copies,
and write/update 制作发布记录.json.

  python archive.py --work <dir> --date 2026-10-13 --topic 用AI别只图便宜 \
      [--day 75] [--topic-plain 用AI便宜的就是最贵的] [--cover 封面名=a.png ...]

Videos come from <work>/render.json, subtitles from <work>/out/. File names:
  视频/<date>_Day<day>_<topic>_<日记版标签>.mp4   (diary version, only when rendered)
  视频/<date>_<topic>_<普通版标签>.mp4             (plain version)
  封面/<date>_<封面名>.png
The cover names listed in the config ("covers") are required: any missing one is reported and
the script exits 2 — publishing must not start without them.
"""

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image

from vdp_common import ARCHIVE_ROOT, CFG, LABELS, load_json, probe, save_json


def free_name(path):
    if not path.exists():
        return path
    n = 2
    while True:
        p = path.with_name(f"{path.stem}_v{n}{path.suffix}")
        if not p.exists():
            return p
        n += 1


def copy_checked(src, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest = free_name(dest)
    shutil.copy2(src, dest)
    if dest.stat().st_size != Path(src).stat().st_size:
        raise RuntimeError(f"复制后大小不一致：{dest}")
    if dest.suffix.lower() in (".mp4", ".mov"):
        probe(dest)
    elif dest.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
        Image.open(dest).verify()
    return dest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--date", required=True, help="YYYY-MM-DD（diary_date.py 的结果）")
    ap.add_argument("--day", type=int, help="日记 Day 编号（开了日记标识才有）")
    ap.add_argument("--topic", required=True, help="文件名里的内容主题")
    ap.add_argument("--topic-plain", "--topic-social", dest="topic_plain", help="普通版的主题，默认同 --topic")
    ap.add_argument("--video", type=Path, help="用户自己剪好的成片（不经 render.py）；给了就不读 render.json、不归档字幕")
    ap.add_argument("--cover", action="append", default=[], metavar="名字=路径",
                    help="封面，可多次给；名字用配置 covers 里的，例 --cover 封面=cover.png")
    ap.add_argument("--root", type=Path, default=ARCHIVE_ROOT)
    args = ap.parse_args()

    work = args.work.expanduser()
    day_dir = args.root.expanduser() / args.date
    d, tp = args.date, args.topic_plain or args.topic
    day_part = f"_Day{args.day}" if args.day else ""
    plan = []
    render = {} if args.video else load_json(work / "render.json")["outputs"]
    if "social" in render:                       # 旧版 render.json 的叫法
        render["plain"] = render.pop("social")
    if args.video:
        plan.append(("成片", args.video, day_dir / "视频" / f"{d}{day_part}_{args.topic}{args.video.suffix.lower()}"))
    if "diary" in render:
        plan.append(("日记版", render["diary"]["path"],
                     day_dir / "视频" / f"{d}{day_part}_{args.topic}_{LABELS['diary']}.mp4"))
    if "plain" in render:
        plan.append(("普通版", render["plain"]["path"], day_dir / "视频" / f"{d}_{tp}_{LABELS['plain']}.mp4"))

    covers = {}
    for item in args.cover:
        if "=" not in item:
            sys.exit(f"✗ --cover 要写成 名字=路径：{item}")
        name, path = item.split("=", 1)
        covers[name.strip()] = Path(path.strip()).expanduser()
    for name, path in covers.items():
        if not path.exists():
            sys.exit(f"✗ 找不到封面 {path}")
        plan.append((f"封面:{name}", path, day_dir / "封面" / f"{d}_{name}{path.suffix.lower()}"))

    if not args.video:
        for kind in ("中英双语", "中文"):
            src = work / "out" / f"{d}_{kind}.srt"
            if src.exists():
                plan.append((f"{kind}字幕", src, day_dir / "字幕" / src.name))
        raw = work / "transcript" / "source.srt"
        if raw.exists():
            plan.append(("原片转写", raw, day_dir / "字幕" / f"{d}_原片转写.srt"))

    done = {}
    for label, src, dest in plan:
        done[label] = str(copy_checked(src, dest))
        print(f"✓ {label} → {done[label]}")
    missing = [f"封面:{n}" for n in CFG.get("covers", []) if n not in covers]
    if not any(k in done for k in ("成片", "日记版", "普通版")):
        missing.insert(0, "成片")

    record_path = day_dir / "制作发布记录.json"
    record = load_json(record_path) if record_path.exists() else {}
    record.update({"date": d, "archive": str(day_dir), "files": done,
                   "archived_at": datetime.now().astimezone().isoformat(timespec="seconds")})
    if args.day:
        record["day"] = args.day
    for name in ("cut.json", "captions.json", "check/check.json"):
        if (work / name).exists():
            record.setdefault("work", {})[name] = str(work / name)
    record.setdefault("platforms", {})
    save_json(record, record_path)
    print(f"✓ 记录 → {record_path}")
    if missing:
        print(f"⚠ 缺少：{'、'.join(missing)} —— 补齐前不要进入发布")
        sys.exit(2)


if __name__ == "__main__":
    main()
