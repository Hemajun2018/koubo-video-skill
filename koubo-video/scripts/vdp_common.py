"""Shared helpers for the koubo-video scripts (stdlib + Pillow only; macOS and Windows).

Everything personal lives outside the skill folder, so reinstalling or updating the skill
never touches it:
  ~/.koubo-video/config.json   paths and switches (written by setup.py init)
  ~/.koubo-video/models, bin   whisper models and, on Windows, downloaded ffmpeg/whisper
  <workspace>/设置/             我的规则.md, 我的经验.md, 词典.txt, 封面参考/
"""

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from difflib import SequenceMatcher
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):  # Windows 控制台默认 GBK，打印 ✓ ✗ 会直接报错
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"
APPLE_SILICON = IS_MAC and platform.machine() == "arm64"
SKILL_DIR = Path(__file__).resolve().parent.parent
TOOL_HOME = Path(os.environ.get("KOUBO_TOOL_HOME") or Path.home() / ".koubo-video").expanduser()
CONFIG_PATH = TOOL_HOME / "config.json"
SF_DATALESS = 0x40000000  # macOS：iCloud 驱逐后的占位文件标志

DEFAULTS = {
    "workspace": str(Path.home() / "口播"),
    "inbox": "",          # 空 = <workspace>/素材
    "work_root": "",      # 空 = <workspace>/剪辑底稿
    "archive_root": "",   # 空 = <workspace>/成品
    "settings_dir": "",   # 空 = <workspace>/设置
    "cover_refs": "",     # 空 = <settings_dir>/封面参考
    # Apple Silicon 用 GPU 跑 large-v3 很快；Windows / Intel 只有 CPU，用 turbo（快几倍，中文略差一点）
    "model": "large-v3" if APPLE_SILICON else "large-v3-turbo",
    "model_dir": str(TOOL_HOME / "models"),
    "timezone": "Asia/Shanghai",
    "english_subtitles": True,
    "diary": {"enabled": False, "anchor": ""},          # anchor 例："2026-09-29:61"（这天是 Day 61）
    "version_labels": {"diary": "日记版", "plain": "成片"},
    "covers": ["封面"],                                  # 每期必须归档的封面名；[] = 不做封面
    "tools": {},                                         # setup.py 下载的 ffmpeg / whisper-cli 路径
    "fonts": {},                                         # 覆盖字体：{"zh": ["路径", 序号], ...}
}


def _expand(p):
    return Path(os.path.expandvars(os.path.expanduser(str(p))))


def load_config():
    cfg = json.loads(json.dumps(DEFAULTS))
    if CONFIG_PATH.exists():
        user = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    return cfg


def save_config(updates):
    """Merge updates into ~/.koubo-video/config.json (keeps keys it does not mention)."""
    cur = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.exists() else {}
    for k, v in updates.items():
        if isinstance(v, dict) and isinstance(cur.get(k), dict):
            cur[k].update(v)
        else:
            cur[k] = v
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
    return cur


CFG = load_config()
CONFIGURED = CONFIG_PATH.exists()
WORKSPACE = _expand(CFG["workspace"])
INBOX = _expand(CFG["inbox"]) if CFG["inbox"] else WORKSPACE / "素材"
WORK_ROOT = _expand(CFG["work_root"]) if CFG["work_root"] else WORKSPACE / "剪辑底稿"
ARCHIVE_ROOT = _expand(CFG["archive_root"]) if CFG["archive_root"] else WORKSPACE / "成品"
SETTINGS_DIR = _expand(CFG["settings_dir"]) if CFG["settings_dir"] else WORKSPACE / "设置"
COVER_REFS = _expand(CFG["cover_refs"]) if CFG["cover_refs"] else SETTINGS_DIR / "封面参考"
MODEL_DIR = _expand(CFG["model_dir"])
ENGLISH = bool(CFG.get("english_subtitles", True))
DIARY = CFG["diary"]
LABELS = CFG["version_labels"]


def die(msg, code=1):
    print(f"✗ {msg}", file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------- 外部工具
def find_tool(name):
    """Path of ffmpeg / ffprobe / whisper-cli, or None. Order: config → PATH → Homebrew → ~/.koubo-video/bin."""
    p = CFG["tools"].get(name)
    if p and _expand(p).exists():
        return str(_expand(p))
    p = shutil.which(name)
    if p:
        return p
    for d in ("/opt/homebrew/bin", "/usr/local/bin"):
        if Path(d, name).exists():
            return str(Path(d, name))
    exe = name + (".exe" if IS_WIN else "")
    if (TOOL_HOME / "bin").exists():
        hits = sorted((TOOL_HOME / "bin").rglob(exe))
        if hits:
            return str(hits[0])
    return None


def tool(name):
    p = find_tool(name)
    if not p:
        die(f"找不到 {name}。先运行：python {SKILL_DIR / 'scripts' / 'setup.py'} install")
    return p


def run(cmd, capture=True, check=True, cwd=None):
    """Run a command list; return stdout text. Raise with stderr tail on failure."""
    p = subprocess.run([str(c) for c in cmd], capture_output=capture, cwd=cwd,
                       encoding="utf-8", errors="replace")
    if check and p.returncode != 0:
        tail = (p.stderr or "")[-1500:]
        raise RuntimeError(f"命令失败 ({p.returncode}): {' '.join(map(str, cmd[:6]))} …\n{tail}")
    return p.stdout if capture else ""


def run_err(cmd):
    """Run and return stderr text (ffmpeg prints its measurements there)."""
    return subprocess.run([str(c) for c in cmd], capture_output=True,
                          encoding="utf-8", errors="replace").stderr or ""


# ---------------------------------------------------------------- 字体
_WINFONTS = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
_NOTO = TOOL_HOME / "fonts" / "NotoSansCJKsc-Bold.otf"
FONT_CANDIDATES = {
    # 字幕中文：粗一点的黑体
    "zh": [("/System/Library/Fonts/Hiragino Sans GB.ttc", 2), (_WINFONTS / "msyhbd.ttc", 0),
           (_WINFONTS / "msyh.ttc", 0), (_WINFONTS / "simhei.ttf", 0),
           ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 2), (_NOTO, 0)],
    # 字幕英文：西文字体（中文字体里的英文字母字宽和字距会别扭）
    "en": [("/System/Library/Fonts/HelveticaNeue.ttc", 0), (_WINFONTS / "segoeui.ttf", 0),
           (_WINFONTS / "arial.ttf", 0), ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0)],
    # 日记标识
    "header_zh": [("/System/Library/Fonts/STHeiti Medium.ttc", 0), (_WINFONTS / "msyhbd.ttc", 0),
                  (_WINFONTS / "simhei.ttf", 0), ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 2),
                  (_NOTO, 0)],
    "header_en": [("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 0), (_WINFONTS / "arialbd.ttf", 0),
                  ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0)],
}


def find_font(kind):
    o = CFG["fonts"].get(kind)
    if o:
        path, idx = (o, 0) if isinstance(o, str) else (o[0], o[1] if len(o) > 1 else 0)
        if _expand(path).exists():
            return str(_expand(path)), int(idx)
    for path, idx in FONT_CANDIDATES[kind]:
        if Path(path).exists():
            return str(path), idx
    if kind in ("en", "header_en"):     # 没有西文字体时退回中文字体（里面也有英文字母）
        return find_font("zh" if kind == "en" else "header_zh")
    return None


def font_spec(kind):
    spec = find_font(kind)
    if not spec:
        die(f"找不到可用的中文字体（{kind}）。运行 setup.py install 会下载一个，或在配置 fonts.{kind} 里指定字体文件")
    return spec


# ---------------------------------------------------------------- 媒体
def probe(path):
    out = run([tool("ffprobe"), "-v", "error", "-print_format", "json",
               "-show_format", "-show_streams", str(path)])
    data = json.loads(out)
    v = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    info = {"path": str(path), "duration": float(data["format"].get("duration", 0)),
            "size": int(data["format"].get("size", 0)), "tags": data["format"].get("tags", {})}
    if v:
        w, h = int(v["width"]), int(v["height"])
        rot = 0
        for sd in v.get("side_data_list", []):
            if "rotation" in sd:
                rot = int(sd["rotation"])
        if abs(rot) in (90, 270):
            w, h = h, w
        num, den = (v.get("avg_frame_rate") or v.get("r_frame_rate") or "30/1").split("/")
        fps = float(num) / float(den) if float(den) else 30.0
        info.update(width=w, height=h, fps=round(fps, 3), vcodec=v.get("codec_name"),
                    color_transfer=v.get("color_transfer"), pix_fmt=v.get("pix_fmt"),
                    v_duration=float(v.get("duration", 0) or 0))
        info["hdr"] = v.get("color_transfer") in ("arib-std-b67", "smpte2084")
    if a:
        info.update(sample_rate=int(a.get("sample_rate", 44100)), channels=int(a.get("channels", 2)),
                    a_duration=float(a.get("duration", 0) or 0))
    return info


def fmt_ts(t, sep=","):
    ms = max(0, round(t * 1000))
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02}{sep}{ms % 1000:03}"


def write_srt(items, path, lang="both"):
    """items: [{start,end,zh,en}] → SRT. lang: zh / en / both（中文在上、英文在下）。"""
    blocks = []
    for i, c in enumerate(items, 1):
        if lang == "zh":
            text = c["zh"]
        elif lang == "en":
            text = c.get("en", "")
        else:
            text = c["zh"] + ("\n" + c["en"] if c.get("en") else "")
        blocks.append(f"{i}\n{fmt_ts(c['start'])} --> {fmt_ts(c['end'])}\n{text}")
    Path(path).write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(obj, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- 口误／残留扫描
FILLERS = set("嗯呃额啊哎诶唉哦噢欸")
LEAD_FILLERS = ("就是", "那个", "呃", "额", "嗯")  # 「然后」「所以」是正常连接词，不提示


def scan_issues(sentences, window=12.0):
    """sentences: [{id,start,end,text}]. Return heuristic warnings for the agent to judge.

    Heuristics only — they point at places worth reading, they do not decide cuts.
    """
    out = []
    clean = [(s, re.sub(r"[，。,.!?！？、\s]", "", s["text"])) for s in sentences]
    for idx, (s, t) in enumerate(clean):
        # 1) 句首水词
        for f in LEAD_FILLERS:
            if t.startswith(f) and len(t) > len(f) + 2:
                out.append({"type": "句首水词", "at": s["start"], "sid": s["id"], "text": f})
                break
        # 2) 句内重复：「这个视这个视频」「所以小所以」「那个那个」
        m = re.search(r"(.{2,6}?)(.{0,3}?)\1", t)
        if m and not re.fullmatch(r"(.)\1+", m.group(1)) and not m.group(1).isdigit():
            out.append({"type": "句内重复", "at": s["start"], "sid": s["id"], "text": m.group(0)})
        # 3) 相邻句（含隔一句）开头相同 → 疑似重录
        for j in (idx + 1, idx + 2):
            if j < len(clean):
                s2, t2 = clean[j]
                common = os.path.commonprefix([t, t2])
                if len(common) >= 4 and s2["start"] - s["end"] < window:
                    out.append({"type": "疑似重录", "at": s["start"], "sid": f"{s['id']}→{s2['id']}",
                                "text": common})
    # 4) 相似短句短时间内出现两次：「甚至我后面在想啊」…「甚至我在想啊」（口头禅或重录）
    for idx, (s, t) in enumerate(clean):
        for s2, t2 in clean[idx + 1:]:
            if s2["start"] - s["end"] > window * 1.5:
                break
            short = min(len(t), len(t2))
            if short < 4 or short > 14 or max(len(t), len(t2)) > short + 4:
                continue
            same = sum(b.size for b in SequenceMatcher(None, t, t2, autojunk=False).get_matching_blocks())
            if same / short >= 0.8:
                out.append({"type": "相似句重复", "at": s2["start"], "sid": f"{s['id']}→{s2['id']}",
                            "text": f"{t} / {t2}"})
    # 去重：同一句同类型只保留最长的提示
    best = {}
    for w in out:
        key = (w["type"], w["sid"])
        if key not in best or len(w["text"]) > len(best[key]["text"]):
            best[key] = w
    return sorted(best.values(), key=lambda w: w["at"])
