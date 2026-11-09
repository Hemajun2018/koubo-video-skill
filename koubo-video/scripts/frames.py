#!/usr/bin/env python3
"""Pick a frame from the video as the cover photo (when the user did not shoot a photo).

  python frames.py --video <work>/cut.mp4 --out <work>/cover                 # 均匀抽 12 帧 → frames.png
  python frames.py --video <work>/cut.mp4 --out <work>/cover --around 12.3   # 12.3s 前后 ±0.5s，每 0.1s 一帧
  python frames.py --video <work>/cut.mp4 --out <work>/cover --at 12.3 [--fix-skin]   # 导出这一帧原图

Look at frames.png, choose a frame where the eyes look at the camera, the mouth is closed with a
slight smile and the person is not blinking; refine with --around, export with --at.
--fix-skin removes the yellow cast of indoor light and brightens a little before image generation.
"""

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from vdp_common import font_spec, probe, run, tool

SKIN_FIX = ("colorbalance=rs=-0.06:gs=-0.01:bs=0.07:rm=-0.05:bm=0.05:rh=-0.02:bh=0.02,"
            "eq=brightness=0.05:contrast=1.06:saturation=0.9:gamma=1.08")


def grab(video, t, path, vf=None):
    run([tool("ffmpeg"), "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1"]
        + (["-vf", vf] if vf else []) + [str(path)])
    return path


def sheet(images, times, path, cols=4, thumb_w=270):
    first = Image.open(images[0])
    th = int(thumb_w * first.height / first.width)
    rows = (len(images) + cols - 1) // cols
    out = Image.new("RGB", (cols * thumb_w + (cols + 1) * 8, rows * (th + 8) + 8), "white")
    zh_path, zh_idx = font_spec("zh")
    f = ImageFont.truetype(zh_path, 22, index=zh_idx)
    d = ImageDraw.Draw(out)
    for i, (p, t) in enumerate(zip(images, times)):
        x, y = 8 + (i % cols) * (thumb_w + 8), 8 + (i // cols) * (th + 8)
        out.paste(Image.open(p).convert("RGB").resize((thumb_w, th)), (x, y))
        d.text((x + 6, y + 4), f"{t:.1f}s", font=f, fill="yellow", stroke_width=2, stroke_fill="black")
    out.save(path)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--count", type=int, default=12)
    ap.add_argument("--around", type=float, help="在这个时间点前后 ±0.5s 每 0.1s 抽一帧")
    ap.add_argument("--at", type=float, help="导出这个时间点的原尺寸 PNG")
    ap.add_argument("--fix-skin", action="store_true", help="去黄提亮（室内暖光、肤色发黄时）")
    args = ap.parse_args()
    out = args.out.expanduser()
    out.mkdir(parents=True, exist_ok=True)
    dur = probe(args.video)["duration"]

    if args.at is not None:
        p = grab(args.video, args.at, out / f"frame_{args.at:.2f}.png", SKIN_FIX if args.fix_skin else None)
        print(f"✓ {p}")
        return
    if args.around is not None:
        times = [round(args.around + k / 10, 2) for k in range(-5, 6) if 0 <= args.around + k / 10 < dur]
        name = f"around_{args.around:.1f}.png"
    else:
        times = [round(dur * (0.05 + 0.9 * i / max(1, args.count - 1)), 2) for i in range(args.count)]
        name = "frames.png"
    tmp = out / "_tmp"
    tmp.mkdir(exist_ok=True)
    imgs = [grab(args.video, t, tmp / f"{i:02}.jpg", "scale=540:-2") for i, t in enumerate(times)]
    print(f"✓ {sheet(imgs, times, out / name)}（看图挑一帧，再用 --around 细挑或 --at 导出）")


if __name__ == "__main__":
    main()
