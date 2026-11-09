#!/usr/bin/env python3
"""Environment check, dependency install and first-time configuration (macOS / Windows).

  python setup.py check                     # 只检查，几秒；有 ✗ 时退出码 1
  python setup.py install [--model NAME]    # 装缺的：Pillow、ffmpeg、whisper-cli、whisper 模型、字体
  python setup.py init --workspace ~/口播 [选项]   # 写配置、建文件夹、放个人规则模板（已有的不覆盖）
  python setup.py show                      # 打印当前配置和实际路径

install 需要联网，会写 ~/.koubo-video/；macOS 用 Homebrew 装 ffmpeg 和 whisper-cpp，
Windows 直接下载官方构建到 ~/.koubo-video/bin/（不需要管理员权限）。
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vdp_common as C  # noqa: E402

UA = {"User-Agent": "koubo-video-setup"}
HF_HOSTS = ("https://huggingface.co", "https://hf-mirror.com")   # 国内连不上 huggingface 时用镜像
FFMPEG_WIN = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
WHISPER_API = "https://api.github.com/repos/ggml-org/whisper.cpp/releases/latest"
NOTO_URL = ("https://github.com/notofonts/noto-cjk/raw/main/Sans/OTF/SimplifiedChinese/"
            "NotoSansCJKsc-Bold.otf")
TEMPLATES = C.SKILL_DIR / "templates"

fails = 0


def check(name, ok, detail="", optional=False):
    global fails
    if not ok and not optional:
        fails += 1
    mark = "✓" if ok else ("·" if optional else "✗")
    print(f"{mark} {name}{('：' + detail) if detail else ''}")
    return ok


def human(n):
    return f"{n / 1e9:.1f} GB" if n > 1e9 else f"{n / 1e6:.0f} MB"


def download(url, dest, label=None):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got, last = 0, -1
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            pct = int(got * 100 / total) if total else -1
            if pct >= 0 and pct // 10 != last:
                last = pct // 10
                print(f"  {label or dest.name}：{pct}%（{human(got)} / {human(total)}）", flush=True)
    if total and got != total:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"下载不完整：{got}/{total}")
    part.replace(dest)
    return dest


def model_file(name):
    return C.MODEL_DIR / f"ggml-{name}.bin"


def whisper_flags_ok(path):
    p = subprocess.run([path, "--help"], capture_output=True, encoding="utf-8", errors="replace")
    text = (p.stdout or "") + (p.stderr or "")
    return "-dtw" in text, "-nfa" in text


# ---------------------------------------------------------------- check
def cmd_check(_args):
    print(f"系统：{sys.platform}  Python {sys.version.split()[0]}  配置：{C.CONFIG_PATH}"
          f"{'' if C.CONFIGURED else '（还没有，运行 setup.py init）'}")
    check("Python ≥ 3.9", sys.version_info >= (3, 9), sys.version.split()[0])
    for t in ("ffmpeg", "ffprobe", "whisper-cli"):
        p = C.find_tool(t)
        check(t, bool(p), p or "未找到 → setup.py install")
    if C.find_tool("ffmpeg"):
        enc = C.run([C.find_tool("ffmpeg"), "-hide_banner", "-encoders"], check=False)
        check("ffmpeg 带 libx264", "libx264" in enc)
    if C.find_tool("whisper-cli"):
        dtw, _ = whisper_flags_ok(C.find_tool("whisper-cli"))
        check("whisper-cli 支持 DTW 字级时间", dtw, "" if dtw else "版本太旧，重新 install")
    try:
        import PIL
        check("Pillow", True, PIL.__version__)
    except ImportError:
        check("Pillow", False, "setup.py install")
    if C.IS_WIN:
        for mod, label in (("tzdata", "tzdata（Windows 时区数据）"), ("zhconv", "zhconv（繁转简）")):
            try:
                __import__(mod)
                check(label, True)
            except ImportError:
                check(label, False, "setup.py install")
    m = model_file(C.CFG["model"])
    check(f"whisper 模型 {C.CFG['model']}", m.exists(), str(m) if m.exists() else f"{m} 不存在 → setup.py install")
    for kind, label in (("zh", "中文字幕字体"), ("en", "英文字幕字体"), ("header_zh", "日记标识字体")):
        spec = C.find_font(kind)
        check(label, bool(spec), spec[0] if spec else "未找到 → setup.py install")
    for label, p in (("工作文件夹", C.WORKSPACE), ("素材文件夹", C.INBOX), ("剪辑底稿", C.WORK_ROOT),
                     ("成品文件夹", C.ARCHIVE_ROOT), ("个人设置", C.SETTINGS_DIR)):
        ok = p.is_dir()
        if ok:
            probe = p / ".koubo_rw_test"
            try:
                probe.write_text("x")
                probe.unlink()
            except OSError:
                ok = False
        check(f"{label}可读写", ok, str(p) if ok else f"{p}（不存在或不可写 → setup.py init）")
    if C.WORKSPACE.exists():
        free = shutil.disk_usage(C.WORKSPACE).free / 1e9
        check("磁盘空间", free > 5, f"{free:.0f} GB 可用")
    eb = shutil.which("ego-browser") or (str(Path.home() / ".local/bin/ego-browser")
                                         if (Path.home() / ".local/bin/ego-browser").exists() else None)
    check("ego-browser（可选：自动发布才需要）", bool(eb), eb or "未安装", optional=True)
    print("✓ 环境正常" if not fails else f"✗ {fails} 项有问题")
    sys.exit(1 if fails else 0)


# ---------------------------------------------------------------- install
def pip_install(pkgs):
    base = [sys.executable, "-m", "pip", "install", "--user", "--upgrade", *pkgs]
    p = subprocess.run(base, capture_output=True, encoding="utf-8", errors="replace")
    if p.returncode != 0 and "externally-managed" in (p.stderr or ""):
        p = subprocess.run(base + ["--break-system-packages"], capture_output=True, encoding="utf-8", errors="replace")
    if p.returncode != 0 and "No module named pip" in (p.stderr or ""):
        subprocess.run([sys.executable, "-m", "ensurepip", "--user"], capture_output=True)
        p = subprocess.run(base, capture_output=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout)[-800:])


def brew():
    return shutil.which("brew") or next((b for b in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew")
                                         if Path(b).exists()), None)


def win_ffmpeg():
    dest = C.TOOL_HOME / "bin" / "ffmpeg"
    z = download(FFMPEG_WIN, C.TOOL_HOME / "downloads" / "ffmpeg-win64.zip", "ffmpeg")
    shutil.rmtree(dest, ignore_errors=True)
    with zipfile.ZipFile(z) as f:
        f.extractall(dest)
    z.unlink()
    ff = next(dest.rglob("ffmpeg.exe"))
    C.save_config({"tools": {"ffmpeg": str(ff), "ffprobe": str(ff.with_name("ffprobe.exe"))}})
    return ff


def win_whisper():
    req = urllib.request.Request(WHISPER_API, headers=UA)
    rel = json.loads(urllib.request.urlopen(req, timeout=60).read())
    asset = next((a for a in rel["assets"] if a["name"] == "whisper-bin-x64.zip"), None)
    if not asset:
        raise RuntimeError(f"whisper.cpp {rel.get('tag_name')} 没有 whisper-bin-x64.zip，请到 "
                           "https://github.com/ggml-org/whisper.cpp/releases 手动下载")
    dest = C.TOOL_HOME / "bin" / "whisper"
    z = download(asset["browser_download_url"], C.TOOL_HOME / "downloads" / asset["name"], f"whisper {rel['tag_name']}")
    shutil.rmtree(dest, ignore_errors=True)
    with zipfile.ZipFile(z) as f:
        f.extractall(dest)
    z.unlink()
    exe = next(iter(sorted(dest.rglob("whisper-cli.exe"))), None)
    if not exe:
        raise RuntimeError("压缩包里没有 whisper-cli.exe")
    C.save_config({"tools": {"whisper-cli": str(exe)}})
    return exe


def cmd_install(args):
    model = args.model or C.CFG["model"]
    todo_user = []

    # 1) Python 包
    need = []
    try:
        import PIL  # noqa: F401
    except ImportError:
        need.append("Pillow")
    if C.IS_WIN:
        for mod in ("tzdata", "zhconv"):    # Windows 没有系统时区库；zhconv 把偶尔出现的繁体转成简体
            try:
                __import__(mod)
            except ImportError:
                need.append(mod)
    if need:
        print(f"· 安装 Python 包：{' '.join(need)}")
        try:
            pip_install(need)
            print("✓ Python 包已安装")
        except RuntimeError as e:
            todo_user.append(f"Python 包安装失败：{e}")

    # 2) ffmpeg / whisper-cli
    missing = [t for t in ("ffmpeg", "ffprobe", "whisper-cli") if not C.find_tool(t)]
    wcli = C.find_tool("whisper-cli")
    if wcli and not whisper_flags_ok(wcli)[0]:
        missing.append("whisper-cli")          # 太旧，没有 DTW
    if C.IS_MAC and missing:
        b = brew()
        if not b:
            todo_user.append("这台 Mac 没有 Homebrew。请在「终端」里粘贴运行 https://brew.sh 首页那一行安装命令"
                             "（需要输入开机密码），装好后再运行 setup.py install")
        else:
            pkgs = sorted({"ffmpeg" if t in ("ffmpeg", "ffprobe") else "whisper-cpp" for t in missing})
            print(f"· brew install {' '.join(pkgs)}（几分钟）", flush=True)
            r = subprocess.run([b, "install", *pkgs])
            if r.returncode != 0:
                todo_user.append(f"brew install {' '.join(pkgs)} 失败，请看上面的输出")
            elif "whisper-cpp" in pkgs and wcli:
                subprocess.run([b, "upgrade", "whisper-cpp"])
    elif C.IS_WIN and missing:
        try:
            if "ffmpeg" in missing or "ffprobe" in missing:
                print("✓ ffmpeg →", win_ffmpeg())
            if "whisper-cli" in missing:
                print("✓ whisper-cli →", win_whisper())
        except Exception as e:  # noqa: BLE001
            todo_user.append(f"下载 ffmpeg / whisper 失败（多半是连不上 GitHub）：{e}")
    elif missing:
        todo_user.append(f"请用系统包管理器安装：{' '.join(missing)}（whisper-cli 来自 whisper.cpp）")

    # 3) whisper 模型
    mf = model_file(model)
    if not mf.exists():
        size = {"large-v3": "3.1 GB", "large-v3-turbo": "1.6 GB", "small": "490 MB", "tiny": "78 MB"}.get(model, "")
        print(f"· 下载 whisper 模型 {model}（{size}）→ {mf}", flush=True)
        err = None
        for host in HF_HOSTS:
            try:
                download(f"{host}/ggerganov/whisper.cpp/resolve/main/ggml-{model}.bin", mf, model)
                err = None
                break
            except Exception as e:  # noqa: BLE001
                err = e
                print(f"  {host} 不可用：{e}，换下一个源")
        if err:
            todo_user.append(f"模型下载失败：{err}。可以手动下载 ggml-{model}.bin 放到 {C.MODEL_DIR}")
        elif args.model and args.model != C.CFG["model"] and C.CONFIGURED:
            C.save_config({"model": model})

    # 4) 字体（Mac / Windows 自带，基本用不上）
    if not C.find_font("zh"):
        try:
            print("· 下载中文字体 Noto Sans CJK SC Bold", flush=True)
            download(NOTO_URL, C.TOOL_HOME / "fonts" / "NotoSansCJKsc-Bold.otf")
        except Exception as e:  # noqa: BLE001
            todo_user.append(f"中文字体下载失败：{e}")

    print()
    if todo_user:
        print("还需要处理：")
        for t in todo_user:
            print(f"  ✗ {t}")
        sys.exit(1)
    print("✓ 依赖都装好了。接着运行 setup.py check 确认一遍。")


# ---------------------------------------------------------------- init / show
def cmd_init(args):
    updates = {}
    ws = Path(os.path.expanduser(args.workspace)).resolve() if args.workspace else C.WORKSPACE
    updates["workspace"] = str(ws)
    for key in ("inbox", "work_root", "archive_root", "cover_refs", "model", "model_dir", "timezone"):
        v = getattr(args, key)
        if v:
            updates[key] = str(Path(os.path.expanduser(v)).resolve()) if key not in ("model", "timezone") else v
    if args.english is not None:
        updates["english_subtitles"] = args.english
    if args.diary_anchor:
        updates["diary"] = {"enabled": True, "anchor": args.diary_anchor}
    elif args.no_diary:
        updates["diary"] = {"enabled": False}
    if args.labels:
        updates["version_labels"] = dict(x.split("=", 1) for x in args.labels.split(","))
    if args.covers is not None:
        updates["covers"] = [x.strip() for x in args.covers.split(",") if x.strip()]
    cfg = C.save_config(updates)

    # 用新配置重新解析路径
    def path_of(key, default):
        return Path(os.path.expanduser(cfg[key])) if cfg.get(key) else default
    settings = path_of("settings_dir", ws / "设置")
    dirs = [ws, path_of("inbox", ws / "素材"), path_of("work_root", ws / "剪辑底稿"),
            path_of("archive_root", ws / "成品"), settings, path_of("cover_refs", settings / "封面参考")]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    for name in ("我的规则.md", "我的经验.md", "词典.txt"):
        dest = settings / name
        if not dest.exists() and (TEMPLATES / name).exists():
            shutil.copy2(TEMPLATES / name, dest)
            print(f"✓ 新建 {dest}")
    print(f"✓ 配置已写入 {C.CONFIG_PATH}")
    for d in dirs:
        print(f"  {d}")


def cmd_show(_args):
    if not C.CONFIGURED:
        print(f"未配置：{C.CONFIG_PATH} 不存在。按 references/首次设置.md 和用户确认后运行 setup.py init。")
    print(json.dumps({
        "config_file": str(C.CONFIG_PATH), "configured": C.CONFIGURED,
        "workspace": str(C.WORKSPACE), "inbox": str(C.INBOX), "work_root": str(C.WORK_ROOT),
        "archive_root": str(C.ARCHIVE_ROOT), "settings_dir": str(C.SETTINGS_DIR),
        "cover_refs": str(C.COVER_REFS), "model": C.CFG["model"], "model_dir": str(C.MODEL_DIR),
        "timezone": C.CFG["timezone"], "english_subtitles": C.ENGLISH, "diary": C.DIARY,
        "version_labels": C.LABELS, "covers": C.CFG["covers"],
        "personal_rules": [str(C.SETTINGS_DIR / n) for n in ("我的规则.md", "我的经验.md", "词典.txt")
                           if (C.SETTINGS_DIR / n).exists()],
    }, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    i = sub.add_parser("install")
    i.add_argument("--model", help="large-v3（最准，3.1GB）/ large-v3-turbo（快，1.6GB）/ small / tiny")
    n = sub.add_parser("init")
    n.add_argument("--workspace", help="工作文件夹，默认 ~/口播")
    n.add_argument("--inbox", help="新素材放哪，默认 <工作文件夹>/素材")
    n.add_argument("--work-root", dest="work_root")
    n.add_argument("--archive-root", dest="archive_root")
    n.add_argument("--cover-refs", dest="cover_refs", help="封面参考图文件夹，默认 <工作文件夹>/设置/封面参考")
    n.add_argument("--model")
    n.add_argument("--model-dir", dest="model_dir")
    n.add_argument("--timezone", help="日期按哪个时区算，默认 Asia/Shanghai")
    n.add_argument("--english", dest="english", action="store_true", default=None, help="中英双语字幕")
    n.add_argument("--no-english", dest="english", action="store_false", help="只要中文字幕")
    n.add_argument("--diary-anchor", help="开启日记标识与 Day 编号，例 2026-09-29:61")
    n.add_argument("--no-diary", action="store_true")
    n.add_argument("--labels", help="成片文件名标签，例 diary=视频号,plain=小红书抖音")
    n.add_argument("--covers", help="每期要做的封面名，逗号分隔，例 视频号,小红书抖音；空字符串 = 不做封面")
    sub.add_parser("show")
    args = ap.parse_args()
    {"check": cmd_check, "install": cmd_install, "init": cmd_init, "show": cmd_show}[args.cmd](args)


if __name__ == "__main__":
    main()
