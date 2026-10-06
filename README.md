# douyin-fashion-edit

一个 [Claude Code](https://claude.com/claude-code) skill：把服装店模特试穿的原片，剪成可以直接发抖音的竖屏穿搭短视频。还能「照着」一条你喜欢的参考视频，用自己的素材仿出同款换装合集。

> A Claude Code skill that turns raw fashion try-on footage into Douyin-ready vertical outfit videos, and can imitate a reference video's editing as an outfit-change compilation.

## 它能做什么

| | |
|---|---|
| **整理素材** | 认出大疆相机 / Mimo 草稿库里的原片，清理预览和缩略图，按衣服自动分组归档 |
| **挑镜头** | 出带时间码的条带图，按「全身走来、脸看得清、不入镜路人和手机」等标准选 5–7 个镜头 |
| **调色** | 按脸部测光给建议：暗的提亮、偏蓝的加暖、被太阳打白的脸压回来，各镜头统一 |
| **美颜与身形** | 逐帧追踪人脸和人体，前后帧平滑、不闪：磨皮去皱（保留纹理）、美白、自然红口红、腮红、眼线、大眼、瘦脸、瘦腰、拉腿 |
| **字幕** | 婚礼片风格的白色衬线字，无底框；永远放在人头顶上方，不挡衣服；结尾品牌卡 |
| **配乐** | 本地生成无版权音乐（MusicGen），或用你自己的曲子；自动测速度和鼓点，剪辑点卡在拍上 |
| **单套视频** | 一套衣服一条，约 15 秒 |
| **模仿参考视频** | 拆解参考视频的剪辑点、节奏、钩子字幕、转场和音乐，生成同款「换装合集」（黄字钩子 + 甩镜卡点换装） |
| **交付** | 按「单套视频 / 换装合集」分文件夹、规范命名，核对分辨率和响度，附发布清单 |

审美取向（选镜、调色、字幕版式、文案口吻、美颜分寸）写在 [`references/aesthetic.md`](references/aesthetic.md)。它来自一位女装店主的真实反馈，目标观众是 30–50 岁的女性。

## 安装

```bash
git clone https://github.com/Peterwang1023/douyin-fashion-edit.git ~/.claude/skills/douyin-fashion-edit
python ~/.claude/skills/douyin-fashion-edit/scripts/setup_check.py --install
```

需要准备：
- Python 3.10+
- ffmpeg / ffprobe（放在 PATH 上）
- Node.js 18+（字幕叠层用 [HyperFrames](https://hyperframes.heygen.com) 渲染，会通过 `npx` 自动拉取）

`setup_check.py --install` 会装好 Python 依赖，并下载 MediaPipe 模型（约 50 MB）。生成音乐时还会下载 MusicGen-small（约 300 MB），有 NVIDIA 显卡会快很多。

## 用法

装好后直接跟 Claude 说，比如：

- 「这个文件夹里是同一批试穿视频，帮我按衣服分类，每套剪一条 15 秒的抖音视频，加字幕显示是 XX服饰的衣服」
- 「草稿文件库里只有部分是原片，其余的删掉，然后像昨天那样剪」
- 「模板库里这条视频我很喜欢，照着它用我的素材做两条换装合集」
- 「脸有点过曝」「眼线再淡一点」「字幕不要底框」

Claude 会按 [`SKILL.md`](SKILL.md) 的流程跑脚本，并在每一步看截图把关。

## 目录

```
SKILL.md               流程总览（Claude 读这个）
scripts/               setup_check, init_project, sources, contact_sheet, meter, render_shots,
                       beautify, music, fonts, build_single, build_combo, analyze_reference,
                       render, review, finalize
assets/                字幕叠层模板（单套、合集、外壳）
references/            aesthetic 审美手册 · config 配置格式 · retouch 美颜参数
                       imitate 模仿参考视频 · publishing 发布清单 · troubleshooting 踩坑记录
```

## 隐私与版权

- 仓库里只有脚本和说明，不含任何视频素材或人像。
- 字幕字体是思源宋体 / 思源黑体（SIL Open Font License，可商用），按需从 Google Fonts 下载子集。
- 生成的音乐只是无版权占位。发布时建议换成抖音热门音乐，可以拿到流量加成。
