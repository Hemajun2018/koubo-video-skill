#!/usr/bin/env python3
"""Check an inbox video is complete and local, copy it into the work dir, extract 16 kHz audio.

  python prepare.py IN.MOV --work <剪辑底稿>/2026-10-13

Fails fast (instead of hanging later) when the file is a cloud placeholder (iCloud on macOS),
still growing (phone upload / sync in progress) or does not decode. Writes <work>/source.json.
"""

import argparse
import os
import shutil
import subprocess
import time
from pathlib import Path

from vdp_common import IS_MAC, SF_DATALESS, die, probe, run, run_err, save_json, tool


def to_sdr(local, work, info):
    """iPhone 默认录 HDR（HLG/杜比视界）。直接按 SDR 编码颜色会发灰，先色调映射成 bt709 再剪。
    需要 ffmpeg 带 zscale（Windows 的 BtbN 构建、macOS 的 ffmpeg-full 都有）；没有就保持原样并警告。"""
    ff = None
    for cand in (tool("ffmpeg"), "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg", "/usr/local/opt/ffmpeg-full/bin/ffmpeg"):
        if Path(cand).exists() and " zscale " in run([cand, "-hide_banner", "-filters"], check=False):
            ff = cand
            break
    if not ff:
        return info
    sdr = work / "source_sdr.mp4"
    if sdr.exists() and sdr.stat().st_mtime >= local.stat().st_mtime and sdr.stat().st_size > 0:
        new = probe(sdr)
        new["hdr_converted_from"] = str(local)
        return new
    print("· HDR 素材，转换为 SDR（一次性，几十秒到几分钟）…", flush=True)
    vf = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,"
          "zscale=t=bt709:m=bt709:r=tv,format=yuv420p")
    run([ff, "-v", "error", "-y", "-i", str(local), "-vf", vf, "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "14", "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
         "-c:a", "copy", "-movflags", "+faststart", str(sdr)])
    new = probe(sdr)
    new["hdr_converted_from"] = str(local)
    return new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video", type=Path)
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--skip-decode", action="store_true", help="跳过整片解码校验（长视频赶时间时）")
    args = ap.parse_args()

    src = args.video.expanduser()
    if not src.exists():
        die(f"找不到 {src}")
    st = os.stat(src)
    if IS_MAC and getattr(st, "st_flags", 0) & SF_DATALESS:
        subprocess.run(["brctl", "download", str(src)], capture_output=True)
        die("文件还在 iCloud 云端（dataless 占位）。已触发下载；等 Finder 里云朵图标消失后重跑。", 2)
    time.sleep(2)
    if os.stat(src).st_size != st.st_size:
        die("文件大小还在变化，手机可能仍在上传；稍后重跑。", 3)

    work = args.work.expanduser()
    work.mkdir(parents=True, exist_ok=True)
    local = work / f"source{src.suffix.lower()}"
    if not (local.exists() and local.stat().st_size == st.st_size):
        # 同一 APFS 卷上 cp -c 是写时克隆，不占额外空间
        if not IS_MAC or subprocess.run(["cp", "-c", str(src), str(local)], capture_output=True).returncode != 0:
            shutil.copy2(src, local)

    info = probe(local)
    if not args.skip_decode:
        err = run_err([tool("ffmpeg"), "-v", "error", "-i", str(local), "-f", "null", "-"]).strip()
        if err:
            die(f"整片解码有错误，素材可能不完整：\n{err[-800:]}", 4)
    if info.get("hdr"):
        info = to_sdr(local, work, info)
    wav = work / "audio16k.wav"
    run([tool("ffmpeg"), "-v", "error", "-y", "-i", str(local), "-vn", "-ac", "1", "-ar", "16000",
         "-c:a", "pcm_s16le", str(wav)])

    info.update(original=str(src), local=info["path"], audio16k=str(wav))
    save_json(info, work / "source.json")
    warn = ("  ⚠ HDR 素材且本机 ffmpeg 没有 zscale，无法转成普通 SDR，成片颜色会发灰。告诉用户："
            "Mac 运行 brew install ffmpeg-full 后重跑；或者 iPhone 设置→相机→录制视频→关闭「HDR 视频」，"
            "或用微信把视频发到电脑（会自动转成普通视频）" if info.get("hdr") else "")
    print(f"✓ {src.name}  {info['duration']:.2f}s  {info.get('width')}x{info.get('height')}@{info.get('fps')}  "
          f"{info['size'] / 1e6:.1f}MB  → {work}{warn}")


if __name__ == "__main__":
    main()
