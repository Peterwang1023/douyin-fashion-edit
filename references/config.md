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
`[源 key, 入点秒, 建议时长, 可选：最大时长]`。建议时长会被吸附到整拍；最大时长用来卡住后面出现路人、手机的地方。镜头编号就是数组下标：`06_0`、`06_1`……

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
  "endLine": "关注我们 · 看更多秋冬穿搭",
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
- `chipShots`：单品标签出现的镜头区间 `[起, 止]`（含），只放全身镜头。
- `fileName`：交付文件名里的衣服名，默认取 `items` 第一项。
- `hookShot`：`[镜头 key, 镜头内偏移秒]`，开头钩子底下的画面。
- `segments`：`[衣服编号, 镜头 key, 偏移秒, 可选：标签文字]`。用甩镜时偏移必须 ≥ 0.25 秒，给转场留预卷。
- `beatsPerLook`、`finaleBeats`、`transition`（`whip` 或 `cut`）、`hookColor`、`hookStroke` 都是可选项，按参考视频调。
- `musicOffsetBeats`（可选，默认等于 `beatsPerLook`）：从曲子第几拍开始取，钩子部分用压闷的这一段。

## retouch.json —— 美颜强度（可选）
```json
{ "eye_big": 0.08, "legs": 0.03 }
```
只写要改的项，其余用默认值（见 `retouch.md`）。改完 `beautify.py` 会自动判定所有镜头过期并重做。

## avail.json —— 自动生成
每个已渲染镜头的实际可用长度（含尾部余量），`render_shots.py` 写、构建脚本读，不用手改。
