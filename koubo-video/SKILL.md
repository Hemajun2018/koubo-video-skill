---
name: koubo-video
description: 中文口播视频剪辑：把手机录的口播视频去掉口误、重复和水词，加中英（或纯中文）字幕，导出成片，做封面、写标题，归档；按用户设置可继续发布到视频号、小红书、抖音等平台。用户给了口播视频、说「剪一下这个视频」「按上次流程做」，或要安装、设置这个剪辑流程时使用。第一次使用会先带用户装环境、做设置。
---

# 口播视频剪辑

处理用户用手机录的中文口播：读转写稿决定删哪些口误，脚本负责剪辑、字幕、导出和检查。macOS 和 Windows 都能用。

## 每次开始前

1. 运行 `py S/setup.py show` 看配置。显示「未配置」时，先按 [references/首次设置.md](references/首次设置.md) 带用户装环境、做设置，完成后再处理视频。
2. 读个人设置文件夹（`show` 里的 `settings_dir`）中的 **`我的规则.md`**：用户自己的平台、封面、发布方式、开剪前要做的事。**它和本文件冲突时，以它为准。** 遇到异常时再查同一文件夹的 `我的经验.md`。
3. 新电脑上，或脚本报找不到 ffmpeg、whisper、字体时：`py S/setup.py check`，缺什么就运行 `py S/setup.py install` 补上。

命令里的写法：

- `py`：Python 3 命令。macOS 用 `python3`；Windows 用 `python`，不行再试 `py -3`。
- `S`：本 skill 的 `scripts` 文件夹（就是这个 SKILL.md 旁边的 `scripts/`），运行时写绝对路径。
- `W`：`<work_root>/<日期>`，`work_root` 从 `setup.py show` 读；同一天第二条视频用 `<日期>_2`。
- 下面的长命令在 PowerShell 里写成一行即可。转写和导出要几分钟，耐心等脚本跑完，不要中途打断。

## 做到哪一步

- 用户只给了视频：剪辑 → 字幕 → 导出 → 检查 → 封面 → 归档，然后给出成片位置、标题和简介。**默认不发布。**
- 用户说「按上次流程做」：按 `我的规则.md` 里写的完整流程做。
- 用户只要成片、只做封面、只发布：照本次说的做。
- 发布只在用户本次明确要求时做，具体方式看 `我的规则.md` 和 [references/发布.md](references/发布.md)。

## 原则

- **机械步骤一律用 `scripts/` 里的脚本，不现写剪辑、字幕、导出代码。** 你只做需要判断的事：读转写决定删哪几段、校对字幕和翻译、写标题、做封面、发布。
- **读文字稿剪，不看画面剪。** 转写里的时间是声学对齐（DTW）得到的字起点；剪辑点由 `cut.py` 自动吸附到附近最安静的位置。
- **检查交给 `verify.py`。** 全部通过、拼图看过一眼、成片转写通读过一遍，就不再做额外检查。任何检查脚本报错或跑不起来，都算没通过，不能当作通过继续往下走。
- 不要把上一条视频的文件名、日期、标题、Day 编号、封面或发布状态带到这一条。

## 流程

```bash
py S/diary_date.py --video IN.MOV [--photo IMG.JPG] [--date 用户说的日期]
py S/prepare.py IN.MOV --work W                       # 云端占位、还在同步、解码错误会直接报错；HDR 素材自动转 SDR
py S/transcribe.py W/audio16k.wav --out W/transcript   # → W/transcript/source.md
#   读 source.md，按 references/口误规则.md 决定去留，写 W/edl.json
py S/cut.py --work W                                  # → cut.mp4（吸附、帧对齐、30ms 淡入淡出、-14 LUFS）
py S/transcribe.py W/cut.mp4 --out W/transcript --name cut      # → cut.md，通读复核接缝
py S/subs.py draft --words W/transcript/cut.words.json --out W/captions.json
#   校对 captions.json
py S/subs.py srt --captions W/captions.json --out-dir W/out --prefix <日期>
py S/render.py --work W --out W/out/plain.mp4 [--date <日期> --day <Day> --diary-out W/out/diary.mp4]
py S/verify.py --work W --transcribe                  # 看 W/check/contact.png，读 W/transcript/final.md
#   做封面（references/封面.md）
py S/archive.py --work W --date <日期> [--day <Day>] --topic <主题> --cover <封面名>=<图片> ...
```

### 素材和日期

1. 优先用用户指定的文件；没指定时，用素材文件夹（`show` 里的 `inbox`）里最新的视频，以及同一时段拍的照片（做封面用）。封面参考图在 `cover_refs` 文件夹，不要当成本次照片。
2. `diary_date.py` 按配置的时区（默认北京时间）算日期，不用电脑本地时间。依据只是视频的 `creation_time`，或者结果提示「接近零点」时，把算出的日期告诉用户并请他确认。确认之前可以先转写和剪辑，但导出带日期的版本之前日期必须确认。
3. 开了日记标识（`show` 里 `diary.enabled` 为 true）时，`diary_date.py` 会同时给出 Day 编号；用户调整过 Day 序列时，以最新确认为准，用 `setup.py init --diary-anchor 日期:Day` 更新。

### 剪辑决策（转写 → edl.json）

1. 读 `source.md`：每行一个短句，带时间、词号和停顿标记，末尾是「待查提示」（疑似重录、相似句、句首水词、句内重复、有声无字）。提示只是指出值得看的位置，去留按 [references/口误规则.md](references/口误规则.md) 判断。转写只用来定位，不当作口播原文。
2. 写 `edl.json`：`keep` 是要保留的原片区间（秒），起点取第一个保留字的起始时间，终点取下一个被删字的起始时间（或句后停顿的中间）；`cuts` 记下每处删除和理由，方便复核。片头开录前、片尾说完后的空白和收尾词（如「好」）一并去掉。

   ```json
   {"keep": [{"start": 0.42, "end": 7.13, "note": "S01-S04"}, {"start": 9.40, "end": 31.2, "note": "S06-S12"}],
    "cuts": [{"start": 7.13, "end": 9.40, "reason": "重录：S05 被 S06 完整重说"}]}
   ```

3. `cut.py` 跑完后读 `cut.md`，重点看每个接缝前后：有没有残字（「这个视」「就」）、重复、没说完的句子、前后接不上。有问题就改 `edl.json` 重剪，**最多 3 轮**；还不干净的位置如实告诉用户。可疑的地方用 `transcribe.py` 对一小段单独复核，不必看画面。

### 字幕

- 字幕按**成片里实际说出的内容**做，时间来自成片转写；不要用润色过的字幕掩盖没剪掉的口误。
- `subs.py draft` 出草稿后逐条校对：`zh` 只修识别错误（专有名词以个人 `词典.txt` 和 `references/词典.txt` 为准），不增删说过的话；断行不能把词拆开（如「随／时」），需要时在相邻两条之间挪字。
- 配置里开了英文字幕（默认开）时，给每条补上自然、忠于原意的 `en`；关了就让 `en` 留空。
- 中文在上、英文在下；保留原声，不加配乐。字幕卡默认在画面 75% 高度处，压到脸时用 `render.py --y 0.8` 之类调整。

### 版本

- **普通版**（`--out`）：只有字幕，所有平台都能用。
- **日记版**（`--diary-out`，开了日记标识才做）：全片顶部显示「视频日记 + 日期 + Day」标识。两版共用同一份剪辑和字幕，发布时不要传错；`verify.py` 会检查日记版开头、中段、结尾都有标识，普通版没有。
- 横版视频的日记标识会被拉伸，先只出普通版，问用户要不要标识。

## 标题与封面

- 根据本次实际内容写标题和简介；用户要挑的话给几个准确的候选，用户已经定了标题就照用。平台字数有限制时缩短展示标题，完整意思放到正文。
- 封面怎么做见 [references/封面.md](references/封面.md)。配置里 `covers` 列出的封面全部做好、归档之前，不进入发布（缺了 `archive.py` 会报错退出）。

## 归档

`archive.py` 把成片、封面、字幕复制到 `<archive_root>/<日期>/`（`视频/`、`封面/`、`字幕/`），同名不覆盖（自动加 `_v2`），逐个核对能读取，并更新同目录的 `制作发布记录.json`。剪辑底稿 `W` 保留剪辑依据（`edl.json`、`cut.json`、`captions.json`、`check/`），不要删。

## 发布

- 是否发布、发到哪些平台，以用户本次的指示为准；本文件不构成发布授权。
- 自动发布需要能操作浏览器的工具（比如 ego-browser，见 [references/发布.md](references/发布.md)）。没有这类工具时，把每个平台要用的视频文件、封面、标题、简介、话题整理成清单交给用户自己发。
- 默认在点「发布」前把清单给用户确认；用户在 `我的规则.md` 里写了「不用确认、直接发布」时，按他的规则来。账户不对、要替换已发布的作品、平台提示违规或限流、上传多次失败时，一律停下来问用户。

## 记住用户的纠正

用户纠正你时（「这里没剪干净」「这个不该删」「封面太暗」），把规律写进个人设置文件夹，**不要改本 skill 的文件**（更新 skill 时会被覆盖）：

- 剪辑、封面、发布的习惯 → `我的规则.md`
- 踩到的坑（症状 → 原因 → 现在的做法）→ `我的经验.md`
- 识别错的专有名词 → `词典.txt`（每行一个，最常用的放前面）

脚本本身有 bug 时，告诉用户具体现象，建议他到这个 skill 的 GitHub 仓库提 issue。

## 参考文件

- [references/首次设置.md](references/首次设置.md)：第一次使用时的安装和设置
- [references/口误规则.md](references/口误规则.md)：删什么、留什么、剪辑点怎么定（剪辑前必读）
- [references/封面.md](references/封面.md)：封面怎么做
- [references/发布.md](references/发布.md)：各平台的发布操作与核实
- [references/踩坑.md](references/踩坑.md)：转写、剪辑、导出、发布时遇到过的问题（遇到异常先查）
- [references/词典.txt](references/词典.txt)：基础热词
