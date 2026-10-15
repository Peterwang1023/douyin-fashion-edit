# 配置文件格式

全部在 `<project>/config/`，UTF-8 JSON。`init_project.py` 会建好空文件。

## sources.json —— 原片（`sources.py scan` 自动写）
```json
{ "0002": "D:\\拍摄\\01_条纹针织开衫\\DJI_20261004165226_0002_D.MP4",
  "0d48": "D:\\拍摄\\草稿文件库\\06_灰绿立领夹克\\0d48f8ac93ea240eaa9e52f1489898da_raw.mp4" }
```
原片挪了位置就重新 scan（新路径会以新 key 登记；旧 key 手动删掉或改 EDL）。

## edl.json —— 每套衣服的镜头表
```json
{ "06": [["2df9", 0.2, 3.0], ["8c2d", 0.2, 2.5], ["ae76", 0.8, 2.5, 2.8]] }
```
`[源 key, 入点秒, 建议时长, 可选：最大时长, 可选：{"speed": 0.7}]`。
- 建议时长会被吸附到整拍；最大时长用来卡住后面出现路人、手机的地方。镜头编号就是数组下标：`06_0`、`06_1`……
- `speed` 小于 1 是慢动作：时长按成片秒数算，实际消耗原片「时长 × speed」秒。原片要是 50/60 fps 才流畅。

## grade.json —— 每个镜头的调色
```json
{ "06": [[0.5, 0.5, 1.2], [1, 1, 1], [1, 1, 0.8]] }
```
`[L 提亮 0–3, W 加暖 0–3, H 压高光 0.5–2.5]`，`meter.py suggest` 给初值。

## music.json —— 配乐（`music.py` 自动写）
```json
{ "warm":   {"file": "assets/bgm/src/warm_1.wav",   "bpm": 101.4, "first_beat": 0.06},
  "runway": {"file": "assets/bgm/src/runway_1.wav", "bpm": 125.0, "first_beat": 0.355} }
```
同一首曲子想在两条合集里用不同段落，就复制一条、把 `first_beat` 往后加整数小节（如 +12 拍），起个新名字。

## outfits.json —— 字幕文案、配乐选择、合集
```json
{
  "brand": "某某服饰",
  "showBrand": false,
  "endTitle": "秋冬穿搭",
  "endLine": "关注我 · 每天分享一套穿搭",
  "targetSeconds": 15,
  "outfits": {
    "06": {
      "title": "一件夹克 利落又减龄",
      "subtitle": "灰绿立领夹克 秋日通勤",
      "items": [["外套", "灰绿立领夹克"], ["内搭", "黑色打底"], ["下装", "深咖阔腿裤"]],
      "music": "breeze",
      "chipShots": [1, 2],
      "fileName": "灰绿立领夹克"
    }
  },
  "combos": {
    "A": {
      "name": "外套篇",
      "hook": ["降温了姐妹们", "这五件外套", "照着穿就对了"],
      "music": "runway",
      "hookShot": ["09_4", 0.5],
      "segments": [["02", "02_0", 0.4], ["06", "06_0", 0.3], ["03", "03_2", 0.5]],
      "beatsPerLook": 4,
      "finaleBeats": 8,
      "transition": "whip",
      "whipDirection": "left",
      "hookColor": "#ffe14a",
      "hookStroke": "#111111"
    }
  }
}
```
- `showBrand`（默认 `false`）：是否在视频里画店名、印章、品牌小字。抖音把店名 / logo 判成「引导至风险不可控渠道」会减少推荐，所以默认不画；`brand` 只用于内部记录。交付文件名也只在 `true` 时带店名。
- `endTitle`：不画店名时结尾卡的大字，默认「秋冬穿搭」。`endLine` 是结尾卡下面那句。
- `chipShots`：单品标签出现的镜头区间 `[起, 止]`（含），只放全身镜头。
- `fileName`：交付文件名里的衣服名，默认取 `items` 第一项。
- `style`：`wedding`（默认，婚礼风）或 `healing`（治愈杂志风：印章、站酷小薇逐字浮现、英文小字）。healing 还要配：
  - `en`：标题上方的英文小字
  - `lines`：`[[中文, 英文, 起始镜头, 结束镜头], ...]`，每句诗只放在全身远景镜头上
  - `itemShots`：`[起, 止]`，在这几个镜头上显示「单品 ｜ 单品」行。**不推荐**：像商品清单，带货感重；改在 `lines` 里加一句搭配心得，如 `["亮色配米白", "BRIGHT & CREAM", 6, 6]`
  - 全局还可以设 `enBrand`（英文小字）和 `seal`（印章两个字）；这两样只在 `showBrand: true` 时画出来
- `motion`：`kenburns` 表示每个镜头缓慢推进或拉出（交替进行）。
- `look`：使用 `assets/shots_look/<名字>/` 里套过参考滤镜的镜头（由 `match_look.py apply` 生成）。
- `targetSeconds`：这一套的目标时长，会自动截短到不超过音乐长度。
- `hookShot`：`[镜头 key, 镜头内偏移秒]`，开头钩子底下的画面。
- `segments`：`[衣服编号, 镜头 key, 偏移秒, 可选：标签文字]`。用甩镜时偏移必须 ≥ 0.25 秒，给转场留预卷。
- `beatsPerLook`、`finaleBeats`、`transition`（`whip` 或 `cut`）、`hookColor`、`hookStroke` 都是可选项，按参考视频调。
- `musicOffsetBeats`（可选，默认等于 `beatsPerLook`）：从曲子第几拍开始取，钩子部分用压闷的这一段。

### clones（风格克隆，在 outfits.json 里）
```json
"clones": {
  "A": {"name": "冷调街拍", "reference": "D:/模板库/306d..._raw.mp4", "outfit": "c1",
        "look": "cool306", "music": "reference", "captions": "brand+end", "threshold": 0.25}
}
```
- `outfit`：EDL 里镜头数和参考一致的那一组。每段时长要不短于参考对应段，构建时按参考剪辑点截取。
- `cuts`（可选）：手动给剪辑点秒数；默认用 `threshold` 自动检测。
- `look`：`match_look.py` 生成的 LUT 名。
- `music`：`reference` 表示沿用参考原声，也可以填 music.json 里的名字。
- `captions`：`none` / `brand` / `brand+end`。顶部品牌小字只在 `showBrand: true` 时出现；`brand+end` 的结尾卡默认写 `endTitle`。

## retouch.json —— 美颜强度（可选）
```json
{ "eye_big": 0.08, "legs": 0.03 }
```
只写要改的项，其余用默认值（见 `retouch.md`）。改完 `beautify.py` 会自动判定所有镜头过期并重做。

## avail.json —— 自动生成
每个已渲染镜头的实际可用长度（含尾部余量），`render_shots.py` 写、构建脚本读，不用手改。
