#!/usr/bin/env python3
"""Fit a generated cover to a platform aspect ratio and make a phone-thumbnail preview.

  python cover.py fit IN.png --out <work>/cover/封面.png [--ratio 3:4] [--mode crop|pad] [--width 1080]

crop: centre-crop to the ratio (generators often give 2:3; ask them to keep text and face in the
      middle so the crop is safe). pad: keep the whole image and fill the sides with a blurred,
      darkened copy (e.g. a 3:4 cover placed on a 16:9 canvas for landscape slots).
Also writes <out>_thumb.png at 240 px wide — open it to check the title is still readable at
the size people see in a feed.
"""

import argparse
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter


def fit(im, ratio, mode, width):
    rw, rh = ratio
    W, H = width, round(width * rh / rw)
    im = im.convert("RGB")
    if mode == "crop":
        scale = max(W / im.width, H / im.height)
        r = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
        x, y = (r.width - W) // 2, (r.height - H) // 2
        return r.crop((x, y, x + W, y + H))
    bg_scale = max(W / im.width, H / im.height)
    bg = im.resize((round(im.width * bg_scale), round(im.height * bg_scale)), Image.LANCZOS)
    x, y = (bg.width - W) // 2, (bg.height - H) // 2
    bg = bg.crop((x, y, x + W, y + H)).filter(ImageFilter.GaussianBlur(40))
    bg = ImageEnhance.Brightness(bg).enhance(0.45)
    scale = min(W / im.width, H / im.height)
    fg = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
    bg.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2))
    return bg


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fit")
    f.add_argument("image", type=Path)
    f.add_argument("--out", type=Path, required=True)
    f.add_argument("--ratio", default="3:4", help="3:4（竖版封面）/ 4:3 / 16:9 / 9:16 / 1:1")
    f.add_argument("--mode", choices=("crop", "pad"), default="crop")
    f.add_argument("--width", type=int, help="输出宽度，默认竖版 1080、横版 1920")
    args = ap.parse_args()

    rw, rh = (int(x) for x in args.ratio.split(":"))
    width = args.width or (1080 if rw <= rh else 1920)
    im = fit(Image.open(args.image), (rw, rh), args.mode, width)
    out = args.out.expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out)
    thumb = out.with_name(out.stem + "_thumb.png")
    im.resize((240, round(240 * im.height / im.width)), Image.LANCZOS).save(thumb)
    print(f"✓ {out}（{im.width}×{im.height}）  缩略图预览：{thumb}")


if __name__ == "__main__":
    main()
