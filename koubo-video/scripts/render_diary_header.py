#!/usr/bin/env python3
"""Render a reusable transparent 1080x1920 diary header for a video."""

import argparse
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from vdp_common import font_spec


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Beijing diary date: YYYY/MM/DD")
    parser.add_argument("--day", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    datetime.strptime(args.date, "%Y/%m/%d")
    if args.day < 1:
        parser.error("--day must be positive")

    im = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    for y in range(0, 350):
        alpha = round(165 * (1 - y / 350) ** 1.6)
        draw.line((0, y, 1079, y), fill=(2, 8, 22, alpha))

    yellow = (255, 225, 0, 255)
    white = (255, 255, 255, 255)
    (cjk_path, cjk_idx), (latin_path, latin_idx) = font_spec("header_zh"), font_spec("header_en")
    cjk = ImageFont.truetype(cjk_path, 65, index=cjk_idx)
    diary_en = ImageFont.truetype(latin_path, 28, index=latin_idx)
    rec = ImageFont.truetype(latin_path, 29, index=latin_idx)
    date_font = ImageFont.truetype(latin_path, 55, index=latin_idx)
    day_font = ImageFont.truetype(latin_path, 100, index=latin_idx)

    draw.ellipse((56, 39, 77, 60), fill=(255, 55, 36, 255))
    draw.text((87, 31), "REC", font=rec, fill=white, stroke_width=2, stroke_fill=(0, 0, 0, 190))

    # Open corner brackets echo the approved WeChat Channels diary cover.
    for points in [
        [(85, 95), (63, 95), (54, 106), (54, 267), (63, 278), (85, 278)],
        [(279, 95), (303, 95), (312, 106), (312, 267), (303, 278), (279, 278)],
    ]:
        draw.line(points, fill=yellow, width=8, joint="curve")
    draw.text((88, 102), "视频", font=cjk, fill=white, stroke_width=2, stroke_fill=(0, 0, 0, 200))
    draw.text((88, 182), "日记", font=cjk, fill=white, stroke_width=2, stroke_fill=(0, 0, 0, 200))
    draw.text((142, 283), "Diary", font=diary_en, fill=yellow, stroke_width=1, stroke_fill=(0, 0, 0, 150))

    date_box = draw.textbbox((0, 0), args.date, font=date_font)
    draw.text((1030 - (date_box[2] - date_box[0]), 66), args.date,
              font=date_font, fill=white, stroke_width=2, stroke_fill=(0, 0, 0, 210))
    day_text = f"Day {args.day}"
    day_box = draw.textbbox((0, 0), day_text, font=day_font)
    draw.text((1030 - (day_box[2] - day_box[0]), 152), day_text,
              font=day_font, fill=white, stroke_width=3, stroke_fill=(0, 0, 0, 210))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    im.save(args.output)


if __name__ == "__main__":
    main()
