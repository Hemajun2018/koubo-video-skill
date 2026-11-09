#!/usr/bin/env python3
"""End-to-end smoke test of the scripts on a synthetic clip (TTS speech with a deliberate re-take).

  KOUBO_TOOL_HOME=<临时目录> python tests/smoke.py --model tiny [--model-dir DIR] [--keep]

Uses its own config (KOUBO_TOOL_HOME) and a workspace with Chinese folder names under a temp
dir, so it never touches a real setup. Runs: init → diary_date → prepare (normal + HDR clip)
→ transcribe → cut → subs → render (diary + plain) → verify → frames/cover → archive.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
S = ROOT / "koubo-video" / "scripts"
FIXTURE = ROOT / "tests" / "fixtures" / "speech.m4a"
PY = sys.executable


def sh(*args, ok=(0,), quiet=False):
    cmd = [str(a) for a in args]
    print("$", " ".join(Path(cmd[1]).name if i == 1 else c for i, c in enumerate(cmd)), flush=True)
    p = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
    if not quiet:
        out = (p.stdout or "") + (p.stderr or "")
        print("\n".join("    " + l for l in out.strip().splitlines()[-25:]), flush=True)
    if p.returncode not in ok:
        raise SystemExit(f"✗ 退出码 {p.returncode}")
    return p.stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="tiny")
    ap.add_argument("--model-dir")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()
    if not os.environ.get("KOUBO_TOOL_HOME"):
        raise SystemExit("先设置 KOUBO_TOOL_HOME 到一个临时目录，避免改动真实配置")

    tmp = Path(tempfile.mkdtemp(prefix="koubo-smoke-"))
    ws = tmp / "口播测试"
    init = [PY, S / "setup.py", "init", "--workspace", ws, "--model", args.model,
            "--diary-anchor", "2026-01-01:1", "--covers", "封面", "--labels", "diary=日记版,plain=通用版"]
    if args.model_dir:
        init += ["--model-dir", args.model_dir]
    sh(*init)
    sh(PY, S / "setup.py", "show")
    sh(PY, S / "setup.py", "check", ok=(0, 1))

    sys.path.insert(0, str(S))
    import vdp_common as C  # noqa: E402  —— 读取刚写好的配置
    ff = C.tool("ffmpeg")

    # 竖版测试视频：彩色测试图 + TTS 语音，带拍摄时间（UTC 02:00 = 北京 10:00）
    video = C.INBOX / "测试 口播.mp4"
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30",
                    "-i", str(FIXTURE), "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-metadata", "creation_time=2026-01-05T02:00:00Z", str(video)], check=True)

    d = json.loads(sh(PY, S / "diary_date.py", "--video", video))
    assert d["date"] == "2026-01-05" and d["day"] == 5, d
    W = C.WORK_ROOT / d["date"]

    sh(PY, S / "prepare.py", video, "--work", W)
    sh(PY, S / "transcribe.py", W / "audio16k.wav", "--out", W / "transcript")
    words = json.loads((W / "transcript" / "source.words.json").read_text(encoding="utf-8"))
    sents = words["sentences"]
    print("    转写：", " | ".join(s["text"] for s in sents))
    # 删掉第一句（被第二句完整重说的「今天我想聊一聊」）之外的部分保留；句子太少就整段保留
    if len(sents) >= 3:
        keep = [{"start": sents[0]["start"], "end": sents[1]["start"], "note": "S01"},
                {"start": sents[2]["start"], "end": sents[-1]["end"], "note": "S03-"}]
    else:
        keep = [{"start": sents[0]["start"], "end": sents[-1]["end"]}]
    (W / "edl.json").write_text(json.dumps({"keep": keep, "cuts": []}, ensure_ascii=False), encoding="utf-8")
    sh(PY, S / "cut.py", "--work", W)
    sh(PY, S / "transcribe.py", W / "cut.mp4", "--out", W / "transcript", "--name", "cut")
    sh(PY, S / "subs.py", "draft", "--words", W / "transcript" / "cut.words.json", "--out", W / "captions.json")
    caps = json.loads((W / "captions.json").read_text(encoding="utf-8"))
    for c in caps["items"]:
        c["zh"] = c["zh"] or "测试"
        c["en"] = "Smoke test caption"
    (W / "captions.json").write_text(json.dumps(caps, ensure_ascii=False), encoding="utf-8")
    sh(PY, S / "subs.py", "srt", "--captions", W / "captions.json", "--out-dir", W / "out", "--prefix", d["date"])
    sh(PY, S / "render.py", "--work", W, "--date", d["date"], "--day", d["day"],
       "--diary-out", W / "out" / "diary.mp4", "--out", W / "out" / "plain.mp4")
    sh(PY, S / "verify.py", "--work", W, "--transcribe", ok=(0, 1))
    check = json.loads((W / "check" / "check.json").read_text(encoding="utf-8"))
    hard = [r for r in check["results"] if r["status"] == "FAIL" and "响度" not in r["check"]]
    assert not hard, hard

    sh(PY, S / "frames.py", "--video", W / "cut.mp4", "--out", W / "cover")
    sh(PY, S / "frames.py", "--video", W / "cut.mp4", "--out", W / "cover", "--at", "1.5", "--fix-skin")
    sh(PY, S / "cover.py", "fit", W / "cover" / "frame_1.50.png", "--out", W / "cover" / "封面.png")
    sh(PY, S / "archive.py", "--work", W, "--date", d["date"], "--day", d["day"], "--topic", "冒烟测试",
       "--cover", f"封面={W / 'cover' / '封面.png'}")
    day_dir = C.ARCHIVE_ROOT / d["date"]
    names = sorted(p.relative_to(day_dir).as_posix() for p in day_dir.rglob("*") if p.is_file())
    print("    成品：", names)
    for want in (f"视频/{d['date']}_Day5_冒烟测试_日记版.mp4", f"视频/{d['date']}_冒烟测试_通用版.mp4",
                 f"封面/{d['date']}_封面.png", f"字幕/{d['date']}_中英双语.srt"):
        assert want in names, want

    # HDR（HLG 10-bit）素材：有 zscale 就应转成 SDR，没有就应给出警告
    hdr = C.INBOX / "hdr.mov"
    r = subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=720x1280:rate=30:duration=2",
                        "-f", "lavfi", "-i", "sine=duration=2", "-c:v", "libx265", "-pix_fmt", "yuv420p10le",
                        "-x265-params", "log-level=error:colorprim=bt2020:transfer=arib-std-b67:colormatrix=bt2020nc",
                        "-color_primaries", "bt2020", "-color_trc", "arib-std-b67",
                        "-colorspace", "bt2020nc", "-c:a", "aac", "-tag:v", "hvc1", str(hdr)])
    if r.returncode == 0:
        assert C.probe(hdr)["hdr"], "测试片段没有被识别成 HDR"
        out = sh(PY, S / "prepare.py", hdr, "--work", tmp / "hdr")
        info = json.loads((tmp / "hdr" / "source.json").read_text(encoding="utf-8"))
        print(f"    HDR：{'已转 SDR' if not info.get('hdr') else '未转换（本机 ffmpeg 无 zscale）'}")
        assert info.get("hdr_converted_from") or (info.get("hdr") and "HDR" in out), info
    else:
        print("    （本机 ffmpeg 没有 libx265，跳过 HDR 测试）")

    print("✓ 冒烟测试通过", tmp if args.keep else "")
    if not args.keep:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
