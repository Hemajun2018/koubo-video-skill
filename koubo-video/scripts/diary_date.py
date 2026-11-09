#!/usr/bin/env python3
"""Compute the video's date (in the configured timezone, default Asia/Shanghai) and, when the
diary header is on, its Day number — never from the computer's local clock.

  python diary_date.py --video IN.MOV [--photo IMG.JPG] [--date 2026-10-13]

Priority: --date (user said so) > photo EXIF with timezone > video quicktime creationdate
(has offset) > video creation_time (UTC). Prints JSON with the basis so it can be shown
to the user.
"""

import argparse
import json
from datetime import date, datetime, timedelta, timezone

from vdp_common import CFG, DIARY, die, probe

FIXED = {"Asia/Shanghai": 8, "Asia/Hong_Kong": 8, "Asia/Taipei": 8, "Asia/Singapore": 8, "Asia/Tokyo": 9}


def zone(name):
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 —— Windows 没装 tzdata 时；这些时区没有夏令时，固定偏移是准确的
        if name in FIXED:
            return timezone(timedelta(hours=FIXED[name]), name)
        die(f"无法加载时区 {name}：运行 setup.py install（会装 tzdata）")


TZ = zone(CFG.get("timezone") or "Asia/Shanghai")
ANCHOR = DIARY.get("anchor") or ""   # "YYYY-MM-DD:Day"，在 setup.py init --diary-anchor 里设


def from_photo(path):
    from PIL import Image
    exif = Image.open(path).getexif()
    sub = exif.get_ifd(0x8769)
    raw = sub.get(0x9003) or exif.get(0x0132)          # DateTimeOriginal / DateTime
    off = sub.get(0x9011) or sub.get(0x9010)           # OffsetTimeOriginal / OffsetTime
    if not raw:
        return None
    dt = datetime.strptime(raw, "%Y:%m:%d %H:%M:%S")
    if not off:
        return None, f"照片 EXIF 有时间 {raw} 但没有时区，不采用"
    sign = 1 if off[0] == "+" else -1
    hh, mm = off[1:].split(":")
    tz = timezone(sign * timedelta(hours=int(hh), minutes=int(mm)))
    return dt.replace(tzinfo=tz), f"照片 EXIF 拍摄时间 {raw}{off}"


def from_video(path):
    tags = {k.lower(): v for k, v in probe(path)["tags"].items()}
    qt = tags.get("com.apple.quicktime.creationdate")
    if qt:
        return datetime.fromisoformat(qt.replace("Z", "+00:00")), f"视频 quicktime 拍摄时间 {qt}"
    ct = tags.get("creation_time")
    if ct:
        return (datetime.fromisoformat(ct.replace("Z", "+00:00")),
                f"视频 creation_time {ct}（UTC；导出副本可能是导出时间，请让用户确认）")
    return None, "视频没有时间元数据"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video")
    ap.add_argument("--photo")
    ap.add_argument("--date", help="用户指定的日期 YYYY-MM-DD 或 YYYY/MM/DD")
    ap.add_argument("--anchor", default=ANCHOR, help="YYYY-MM-DD:Day；不给就不算 Day")
    args = ap.parse_args()

    basis, d = [], None
    if args.date:
        d = date.fromisoformat(args.date.replace("/", "-"))
        basis.append(f"用户指定 {d}")
    else:
        for fn, src in ((from_photo, args.photo), (from_video, args.video)):
            if not src:
                continue
            try:
                res = fn(src)
            except Exception as e:  # noqa: BLE001
                basis.append(f"{src}: 读取失败 {e}")
                continue
            if res and res[0]:
                local = res[0].astimezone(TZ)
                d = local.date()
                basis.append(f"{res[1]} → {TZ} {local:%Y-%m-%d %H:%M}")
                if local.hour == 0 or local.hour == 23:
                    basis.append("⚠ 接近零点，日期容易差一天，请用户确认")
                break
            if res:
                basis.append(res[1])
    if d is None:
        print(json.dumps({"ok": False, "basis": basis, "hint": "日期无法可靠确定，先问用户"}, ensure_ascii=False))
        raise SystemExit(2)

    out = {"ok": True, "date": d.isoformat(), "date_slash": d.strftime("%Y/%m/%d"),
           "timezone": str(TZ), "basis": basis}
    if args.anchor:
        a_date, a_day = args.anchor.split(":")
        out.update(day=int(a_day) + (d - date.fromisoformat(a_date)).days, anchor=args.anchor)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
