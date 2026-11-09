# 口播剪辑 Skill（koubo-video）

给 Codex 用的中文口播视频剪辑流程。把手机录的口播视频交给它，它会：

1. 把语音转成带时间的文字稿（本地运行 whisper，不上传视频）；
2. 读文字稿，去掉口误、重录、说一半的句子、句首的「就是」「呃」；
3. 剪辑点自动对齐到最安静的位置，音量统一到 -14 LUFS；
4. 加中英双语（或纯中文）字幕；
5. 自动检查成片：时长、音画同步、响度、字幕完整、接缝处有没有残字；
6. 截帧、生成封面（Codex 自带生图，用你的 ChatGPT 额度）；
7. 归档成片、字幕、封面，写好标题和简介；
8. 可选：自动发布到视频号、小红书、抖音、B 站（需要另装 ego lite 浏览器）。

macOS 和 Windows 都能用。用得越久越顺手：你纠正过的地方会记进你自己的规则文件，下次照做。

## 需要什么

- ChatGPT 账号（Plus 及以上），装好 Codex（桌面 App、命令行、VS Code 插件都行）
- macOS（推荐 Apple Silicon，M1 及以后）或 Windows 10/11
- 约 5 GB 空闲空间（语音识别模型 1.6–3 GB）
- Python 3.9 以上：Mac 一般自带；Windows 没有的话，在 PowerShell 运行 `winget install Python.Python.3.12`

## 安装

在 Codex 里发这段话：

```text
请用 skill-installer 安装这个 skill：https://github.com/Hemajun2018/koubo-video-skill/tree/main/koubo-video
装好后读它的 SKILL.md，按 references/首次设置.md 带我完成环境安装和设置。
```

Codex 会下载 ffmpeg、whisper 和语音识别模型（10–30 分钟，期间会请你同意联网和写文件），然后问你几个问题：工作文件夹放哪、字幕要不要英文、封面做几张、发哪些平台。全部用默认值也可以。

如果 Codex 说找不到这个 skill，重启 Codex 再发一次。

## 使用

把手机录的视频放进素材文件夹（默认 `~/口播/素材`），然后在 Codex 里说：

```text
剪一下最新的口播视频
```

建议在工作文件夹（默认 `~/口播`）里打开 Codex，读写文件时就不用反复确认权限。

其他说法：「只出成片，不用做封面」「标题给我 3 个候选」「按上次流程做」（按你在 `我的规则.md` 里写的完整流程）。

## 你的个人设置在哪

| 位置 | 内容 |
|---|---|
| `~/.koubo-video/config.json` | 文件夹路径、字幕语言、日记标识、封面名等开关（`setup.py init` 写的） |
| `~/.koubo-video/models/` | 语音识别模型 |
| `<工作文件夹>/设置/我的规则.md` | 你的习惯：平台、封面风格、发布方式……AI 每次都会读，和默认做法冲突时以它为准 |
| `<工作文件夹>/设置/我的经验.md` | 踩过的坑、被你纠正过的地方 |
| `<工作文件夹>/设置/词典.txt` | 你常说的专有名词，让转写更准 |
| `<工作文件夹>/剪辑底稿/` | 每条视频的剪辑过程文件 |
| `<工作文件夹>/成品/` | 成片、封面、字幕 |

这些都不在 skill 文件夹里，所以更新 skill 不会丢。

## 更新

在 Codex 里说：

```text
把 koubo-video skill 更新到 GitHub 上的最新版：删掉 Codex skills 文件夹里的 koubo-video，再用 skill-installer 重新安装 https://github.com/Hemajun2018/koubo-video-skill/tree/main/koubo-video
```

## 在 Claude Code 里用

把仓库里的 `koubo-video` 文件夹复制（或软链接）到 `~/.claude/skills/koubo-video`。Claude Code 没有内置生图，封面要么用浏览器打开 ChatGPT 生成，要么由你自己生成后放回去。

## 常见问题

- **模型下载很慢或失败**：脚本会自动从 huggingface 换到国内镜像 hf-mirror.com；还不行就换个网络或开代理重试。
- **Windows 上转写比较慢**：Windows 只用 CPU，默认用 large-v3-turbo 模型，3 分钟的视频大约要 3–6 分钟。电脑很慢时可以让 Codex 换成 small 模型。
- **成片颜色发灰**：iPhone 默认录的是 HDR 视频。Windows 上会自动转换；Mac 上需要 `brew install ffmpeg-full`，或者在 iPhone「设置 → 相机 → 录制视频」里关掉「HDR 视频」。
- **想自动发布**：需要装 ego lite 浏览器（https://lite.ego.app/ ），并在里面登录各平台的创作者后台。详见 `koubo-video/references/发布.md`。
- **隐私**：视频只在你自己的电脑上处理；只有生成封面时会把截图发给 ChatGPT。

## 开发

`tests/smoke.py` 用一段合成语音把整个流程跑一遍（不碰真实配置），GitHub Actions 在 Windows 和 macOS 上各跑一次：

```bash
KOUBO_TOOL_HOME=/tmp/koubo-test python3 koubo-video/scripts/setup.py install --model tiny
KOUBO_TOOL_HOME=/tmp/koubo-test python3 tests/smoke.py --model tiny
```
