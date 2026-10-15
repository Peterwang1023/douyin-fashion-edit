---
name: douyin-fashion-edit
description: >
  抖音/小红书服装穿搭短视频的全流程剪辑：把一堆模特试穿的原片（大疆 DJI / Mimo 草稿库 / 手机）按衣服分类，
  挑镜头、调色压高光、逐帧自然美颜与身形修饰、婚礼风字幕、节拍卡点配乐，产出每套衣服一条约 15 秒的竖屏视频；
  并能拆解一条参考/模板视频（剪辑点、节奏、钩子字幕、转场、音乐），用自己的素材仿制成「换装合集」，
  或做「风格克隆」——同长度、同剪辑点、同慢动作、同滤镜（自动生成 LUT）、直接沿用原视频背景音乐。
  只要用户提到服装店/女装/穿搭视频、试穿素材、按衣服分类视频、抖音带货短视频、换装卡点、仿照/模仿/照着某个视频剪、
  模仿某条视频的滤镜/色调/风格/音乐、
  给模特美颜瘦身、去原声配乐加字幕，就使用本 skill——即使没说「skill」或「HyperFrames」。
  Use for Douyin / Xiaohongshu / Reels fashion try-on footage: sort clips by outfit, grade, retouch, caption,
  beat-cut to music, and imitate a reference video's editing as an outfit-change compilation.
---

# 抖音服装穿搭短视频剪辑

两种成品，**分开交付，不要混在一起**（用户明确要求过）：

| 成品 | 内容 | 长度 |
|---|---|---|
| 单套视频 | 一套衣服一条：5–7 个镜头卡拍硬切，婚礼风白色衬线字，结尾卡（默认不放店名） | ~15 s |
| 换装合集 | 仿参考视频：开头黄色粗体钩子 → 每 4 拍甩镜换一套 → 结尾卡 | ~13–15 s |
| 仿模板视频 | 风格克隆：一套衣服，照参考的剪辑点、慢动作、滤镜（LUT）和原声音乐 | 同参考 |

这个 skill 的价值一半在脚本，一半在审美。**开工前先读 `references/aesthetic.md`**：选什么镜头、字放哪、文案怎么写、美颜到什么程度为止，都在里面，且都来自真实用户（30–50 岁女装店主）的反馈。

## 准备

```bash
python scripts/setup_check.py --install          # ffmpeg、Node、Python 依赖、MediaPipe 模型
python scripts/init_project.py <工作目录>/edit --brand "店铺名" --end-line "关注我 · 每天分享一套穿搭"
```

以下命令都在 skill 目录下运行，并加 `--project <工作目录>/edit`（下文省略）。所有配置在 `<project>/config/`，格式见 `references/config.md`。成片用 HyperFrames CLI 渲染（字幕叠层），按本 skill 的脚本走即可，不需要再跑 HyperFrames 的意图访谈；只有改字幕模板时才需读 `/hyperframes-core`。

## 流程

### 1. 盘点素材
`python scripts/sources.py scan <素材文件夹>...` 给每个原片一个短 key（DJI 片号 `0002`、Mimo 哈希前 4 位 `0d48`）。
Mimo 草稿库里每段有 4 个文件，只有 `<hash>_raw.mp4` 是原片；`sources.py junk <目录>` 列出预览小视频和缩略图。**只有用户要求清理时**才加 `--recycle`（进回收站，可恢复），并告诉用户删了多少、多大。

### 2. 按衣服分类
`contact_sheet.py overview` 生成每段两帧的总览图 → 逐张看 → 分组。颜色相近的外套（灰绿 vs 灰色、古铜皮衣 vs 深棕机车夹克）用 `contact_sheet.py torso KEY@秒 ...` 并排看领口、拉链、门襟再下结论。
把原片**移动**（不删除）到 `NN_衣服描述` 文件夹，编号接着已有的往下排；横屏、过短的片段照样归类，只是不进成片。分类后重新 `sources.py scan` 更新路径。

### 3. 选镜头（EDL）
`contact_sheet.py strips KEY...` 出 2 fps 带时间码的条带图，按 aesthetic.md 的选镜标准挑 5–7 段，写进 `config/edl.json`：`"06": [["2df9", 0.2, 3.0], ["8c2d", 0.2, 2.5, 2.8], ...]`（源 key、入点秒、建议时长、可选的最大时长——后面有路人/掏手机时用它卡住）。`contact_sheet.py edl 06` 复核每段中间帧。

### 4. 调色
`meter.py suggest 06` 测亮度、色温、脸部过曝比例，给每个镜头填建议的 `[提亮 L, 暖 W, 压高光 H]`；`meter.py sheet 06` 出前后对比图，看了再微调 `grade.json`。原则：脸和衣服看得清、不发白，各镜头统一。然后 `render_shots.py 06 07 --jobs 3`。

### 5. 美颜与身形
先预览：`beautify.py --preview 06_0 06_3`（挑一个近景、一个全身），看 `review/beauty_*_face.jpg` 放大图——本人要一眼认得出、皮肤有纹理、口红在暗光下不发亮。再全量：`beautify.py --jobs 3`（只处理过期的镜头）。默认强度和每项含义见 `references/retouch.md`；用户要调某项，写 `config/retouch.json` 后重跑。

### 6. 配乐
默认去掉原声。没有曲库时本地生成无版权音乐：`music.py generate warm --register`（预设：warm/chic/dusk/breeze/jazz 适合单套，runway 125 BPM 适合合集）；用户给了音乐就 `music.py add 名字 文件`。生成的曲子只是占位，交付时要建议换抖音热门音乐。

### 7. 字幕文案
在 `config/outfits.json` 写每套的标题、副标题、单品标签、配乐、哪几个镜头是全身镜头（单品标签只出现在全身镜头上）。口吻与禁用词见 aesthetic.md。

### 8. 渲染单套
`render.py single 06 07 ...` = 生成 → lint → 渲染 → 出审片图（`review/render_06.jpg`）。**每张审片图都要看**：字在头顶上方、不压衣服、脸不发白、没有路人和手机。有问题改配置重渲。

### 9. 换装合集（模仿参考视频）
`analyze_reference.py 参考视频.mp4` 拆出剪辑点、每镜时长、BPM、是否卡拍、音乐何时进；再看 `sheet.jpg` 和 `cut_*.jpg` 判断转场和字幕样式。按 `references/imitate.md` 映射成 `outfits.json` 的 `combos` 配置（可混用不同日期拍的素材），`render.py combo A B`。脚本会在钩子字可能挡住头时报警。

### 9b. 风格克隆（照着一条视频原样做）
用户想要参考视频的滤镜、拍法和音乐时：`analyze_reference.py` + `contact_sheet.py pace`（判断慢动作）→ EDL 里建一个镜头数和参考一致的 outfit（如 `c1`，镜头可带 `{"speed": 0.7}`）→ 调色、`render_shots`、`beautify` → `match_look.py build/apply` 生成并套用参考的 LUT → `outfits.json` 的 `clones` → `render.py clone A`。音乐用 `"music": "reference"` 原样沿用，但要提醒用户版权风险和「使用同款音乐」。详见 `references/imitate.md` 后半部分。

### 10. 交付
`finalize.py --out <工作目录>/成片` 按「单套视频 / 换装合集 / 仿模板视频」分文件夹、按「编号_衣服名」命名（`showBrand: true` 才带店名），并核对 1080×1920 和 -14 LUFS；加 `--covers` 导出封面图。再按 `references/publishing.md` 写一份发布清单放进成片文件夹（换热门音乐的方法、每条文案和话题、发布时间）。

## 隐私

- 这个 skill 仓库只放脚本、模板和说明。**素材、成片、封面、审片图、`cache/` 里的人脸追踪数据、参考视频都不进仓库**，也不要放进 README 当示例图。`.gitignore` 已经挡住常见的视频、图片、音频、缓存格式；提交前用 `git status` 再看一眼。
- 店名、人名、家庭关系、本机路径不要写进脚本和文档；示例统一用「某某服饰」。

## 跟用户说实话

- 渲染后看过截图再说「好了」；看不到的（比如音乐好不好听）直说没法判断。
- 做不到的修饰不要声称做了：侧脸、远景的小脸不会做眼部修饰；横屏素材没进成片要说明。
- 美颜拉腿瘦身会让衣服在画面里比实物修长，提醒在商品页放平铺图和尺码表。
- 再在剪映里开美颜会叠加变假——要调哪项，改参数重跑。

## 时间预估（RTX 级显卡 / 普通 CPU）

| 步骤 | 每套（6 镜头） |
|---|---|
| render_shots | ~1 分钟 |
| beautify（首次含追踪） | ~5 分钟；`--jobs 3` 并行 |
| 渲染单套 / 合集 | ~1.5 分钟 / 条 |
| music generate | ~3 分钟 / 20 秒曲（CPU），GPU 快得多 |

长任务放后台跑，期间做下一步（写文案、看审片图）。

## 参考文件

- `references/aesthetic.md` — 审美手册：选镜、调色、节奏、字幕版式、文案口吻、验收清单（**必读**）
- `references/config.md` — 所有配置文件格式与示例
- `references/retouch.md` — 美颜/身形参数、默认值、边界情况
- `references/imitate.md` — 拆解参考视频：映射为换装合集，或做风格克隆（慢动作、LUT 调色、原声）
- `references/publishing.md` — 发布清单模板
- `references/troubleshooting.md` — 踩过的坑（中文路径、MusicGen 报错、lint 错误等）
