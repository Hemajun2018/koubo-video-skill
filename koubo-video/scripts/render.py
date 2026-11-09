#!/usr/bin/env python3
"""Burn captions (and, optionally, the diary header) in one pass.

  python render.py --work <dir> --out <dir>/out/plain.mp4
  python render.py --work <dir> --date 2026-10-13 --day 75 \
      --diary-out <dir>/out/diary.mp4 --out <dir>/out/plain.mp4      # 开了日记标识时出两版

Uses <work>/cut.mp4 and <work>/captions.json. Captions are Pillow-rendered PNG cards (many
ffmpeg builds have no libass): Chinese on top in a CJK bold face, English below in a Latin face
(Latin glyphs from a CJK font look subtly off); English line only when the caption has one.
Header is composited first, captions last, so nothing covers the subtitles. Audio is copied.
"""

import argparse
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from vdp_common import die, font_spec, load_json, probe, run, save_json, tool
from subs import check


def font(spec, size):
    return ImageFont.truetype(spec[0], size, index=spec[1])


def fit(draw, text, spec, size, min_size, max_w):
    while size > min_size and draw.textlength(text, font=font(spec, size)) > max_w:
        size -= 1
    return font(spec, size)


def wrap_en(draw, text, f, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=f) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    return lines + [cur] if cur else lines


def caption_card(zh, en, W, path):
    k = W / 1080
    probe_im = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    max_w = int(W * 0.84)
    zh_spec, en_spec = font_spec("zh"), font_spec("en")
    fz = fit(probe_im, zh, zh_spec, int(46 * k), int(34 * k), max_w)
    en = (en or "").strip()
    fe = fit(probe_im, en, en_spec, int(31 * k), int(24 * k), max_w)
    en_lines = wrap_en(probe_im, en, fe, max_w) if en else []
    zh_h = fz.getbbox("国")[3]
    en_h = fe.getbbox("Ag")[3]
    pad_x, pad_y, gap = int(26 * k), int(16 * k), int(8 * k)
    text_w = max([probe_im.textlength(zh, font=fz)] + [probe_im.textlength(l, font=fe) for l in en_lines])
    bw = int(text_w + 2 * pad_x)
    bh = int(pad_y * 2 + zh_h + (gap + len(en_lines) * en_h + (len(en_lines) - 1) * int(4 * k) if en_lines else 0))
    im = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, bw - 1, bh - 1), radius=int(16 * k), fill=(0, 0, 0, 180))
    d.text((bw / 2, pad_y), zh, font=fz, fill="white", anchor="mt")
    y = pad_y + zh_h + gap
    for line in en_lines:
        d.text((bw / 2, y), line, font=fe, fill=(235, 235, 235, 255), anchor="mt")
        y += en_h + int(4 * k)
    im.save(path)
    return bw, bh


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--video", type=Path, help="默认 <work>/cut.mp4")
    ap.add_argument("--captions", type=Path, help="默认 <work>/captions.json")
    ap.add_argument("--date", help="日记标识上的日期 YYYY-MM-DD（diary_date.py 算）")
    ap.add_argument("--day", type=int)
    ap.add_argument("--diary-out", type=Path, help="带日记标识的版本；不给就不出")
    ap.add_argument("--out", "--plain-out", "--social-out", dest="plain_out", type=Path,
                    help="不带标识的普通版本；不给就不出")
    ap.add_argument("--y", type=float, default=0.75, help="字幕卡顶边位置（占画面高度比例）；压脸时调")
    ap.add_argument("--crf", default="18")
    args = ap.parse_args()

    work = args.work.expanduser()
    video = (args.video or work / "cut.mp4").expanduser()
    caps = load_json((args.captions or work / "captions.json").expanduser())
    info = probe(video)
    W, H, fps = info["width"], info["height"], info.get("fps") or 30
    problems = check(caps["items"], info["duration"])
    if problems:
        die("字幕未通过检查，先修 captions.json：\n  " + "\n  ".join(problems))
    if not (args.diary_out or args.plain_out):
        die("至少给 --out 或 --diary-out")

    card_dir = work / "cards"
    card_dir.mkdir(exist_ok=True)
    cards = []
    for i, c in enumerate(caps["items"], 1):
        p = card_dir / f"cap_{i:03}.png"
        bw, bh = caption_card(c["zh"], c["en"], W, p)
        cards.append((p.relative_to(work).as_posix(), (W - bw) // 2, int(H * args.y), c["start"], c["end"]))

    outputs = {}
    jobs = []
    if args.diary_out:
        if not (args.date and args.day):
            die("日记版需要 --date 和 --day（用 diary_date.py 算）")
        header = work / f"header_{args.date}_day{args.day}.png"
        run([sys.executable, str(Path(__file__).with_name("render_diary_header.py")),
             "--date", args.date.replace("-", "/"), "--day", str(args.day), "--output", str(header)])
        jobs.append(("diary", args.diary_out.expanduser().resolve(), header.name))
    if args.plain_out:
        jobs.append(("plain", args.plain_out.expanduser().resolve(), None))

    for kind, out, header in jobs:
        out.parent.mkdir(parents=True, exist_ok=True)
        # 在工作目录里用相对路径引用字幕卡：字幕多时命令行很长，Windows 有 32K 字符上限
        cmd = [tool("ffmpeg"), "-v", "error", "-y", "-i", str(video.resolve())]
        chain, last, n = [], "0:v", 1
        if header:
            cmd += ["-i", str(header)]
            chain.append(f"[1:v]scale={W}:{H}[hdr];[0:v][hdr]overlay=0:0[h]")
            last, n = "h", 2
        for j, (p, x, y, s, e) in enumerate(cards):
            cmd += ["-i", str(p)]
            chain.append(f"[{last}][{n}:v]overlay={x}:{y}:enable='between(t,{s:.3f},{e:.3f})'[c{j}]")
            last, n = f"c{j}", n + 1
        cmd += ["-filter_complex", ";".join(chain), "-map", f"[{last}]", "-map", "0:a",
                "-r", f"{fps:g}", "-c:v", "libx264", "-preset", "medium", "-crf", args.crf,
                "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(out)]
        subprocess.run(cmd, check=True, cwd=work)
        got = probe(out)
        outputs[kind] = {"path": str(out), "duration": got["duration"]}
        print(f"✓ {kind}: {out}  {got['duration']:.2f}s")
    save_json({"video": str(video), "outputs": outputs, "caption_y": args.y,
               "date": args.date, "day": args.day}, work / "render.json")


if __name__ == "__main__":
    main()
