# 踩过的坑

| 现象 | 原因 / 解决 |
|---|---|
| MediaPipe 报 `Unable to open file at D:/����/...` | 模型路径里有中文。脚本统一用 `model_asset_buffer` 从内存加载；模型放在 `~/.cache/douyin-fashion-edit/models`（可用环境变量 `DFE_MODEL_DIR` 改） |
| MusicGen `AttributeError: 'MusicgenDecoderConfig' object has no attribute 'decoder'` | transformers 4.5x 的 bug：`MusicgenForConditionalGeneration.config_class` 指错了类。`music.py` 已显式加载 `MusicgenConfig` |
| `ffmpeg ... mjpeg Non full-range YUV is non-standard` 截图失败 | 10-bit HEVC（大疆）转 jpg 时出错。滤镜链末尾加 `format=yuvj420p`，或者直接输出 rawvideo（脚本已这样做） |
| HyperFrames lint `multiple_root_compositions` | 项目根目录下只能有一个带 `data-composition-id` 的 html（index.html）。叠层文件要放在 `compositions/` |
| lint `video_nested_in_timed_element` | 外层容器和里面的 `<video>` 都带了 `data-start`。甩镜组件已去掉外层容器的计时 |
| lint `root_missing_dimensions`（甩镜组件） | 组件根节点要补上 `data-width/height`，`build_combo.py` 已处理 |
| lint `gsap_timeline_set_initial_hide` | 初始隐藏写在 CSS 里（`opacity:0`），不要用 `tl.set(..., 0)` |
| lint `overlapping_gsap_tweens`（#shade） | 字幕时间窗太近时，压暗层的动画会重叠。模板已把间隔小于 1.2 秒的时间窗合并 |
| 对比度检查报字幕对比不足 | 白字压在亮天空上。对比度检查只是参考；以审片图里实际看得清为准。看不清就加深 `#shade` 渐变，或把钩子换到天空少的镜头 |
| 脸部颜色变青 | 已经过曝的皮肤被压高光后红通道不够。`grade_filter` 的 H 参数会同时给高光加暖，抵消这个问题 |
| 暗光镜头的口红太亮、太红 | 口红颜色要随脸部亮度收敛（脚本已按脸部亮度缩放）。验收时单独挑一个暗光镜头看 |
| 拉腿后头顶进了字幕区 | 拉伸的空间向下给，头不上移（`lifts` 逻辑）；合集钩子会自动检查头顶位置 |
| Windows 下 Python 脚本里的 `\0` | 字符串里写 `'\0[1-5]'` 会变成空字符，导致 `SyntaxError: source code string cannot contain null bytes`。路径用 `os.path.join` 拼 |
| bash 里用 `rm -f "$S"/*` 被安全检查拦截 | 变量为空时会变成删根目录。写成 `"${S:?}"/*` 或用字面路径 |
| 渲染很慢 | 已经是硬件 GPU 截图模式（看日志第二行确认）；一条约 1–1.5 分钟。不要并行渲染：每个项目只有一个 index.html |
| `UnicodeDecodeError: 'gbk' codec can't decode` | 中文 Windows 上 `subprocess(text=True)` 默认按 GBK 解码 ffmpeg 输出。所有调用都要显式写 `encoding='utf-8', errors='replace'`（脚本已统一处理） |
| 生成的音乐覆盖了已登记的曲子 | 生成的文件统一叫 `<情绪>_gen<种子>.wav`，遇到同名会自动加后缀，不会覆盖 |
| 合集报 `shot is 4.00s, needs 4.14s` | 最后一套要停留 8 拍。换一个可用长度更长的镜头当压轴，或者把偏移调小 |
| 成片音乐比原曲早约 21 ms | AAC 编码器的前置延迟。克隆用的原声存成 WAV（`build_clone.py` 已这样做），对齐误差降到约 5 ms |
| `analyze_reference` 报 0 个剪辑点 | 一镜到底，或者是很软的转场（同一动作换机位、叠化）。加 `--threshold 0.12` 再跑，并看 sheet.jpg 确认 |
| LUT 让我们的画面整体过暗 | 参考暗是因为内容（黑衣、暗树、夜景），不是滤镜。`match_look.py build --tone 0.5` 降低明暗曲线的跟随程度 |
| 参考视频「有音轨」但完全没声音 | 音轨被静音了（元数据里 `te_composition_video_track_volume=0`）。`analyze_reference` 现在会报 SILENT，不再从静音里测出一个假 BPM |
| 调色后蓝天变灰黄、灰路面变蓝 | 只按亮度分段的偏色处理不了「橙青」滤镜。`match_look` 现在按色相分区匹配，近灰色往参考底色融合，不会被饱和度放大 |
| 字幕压在头上（近景、4K 竖拍） | 改用竖排的 healing 风格（自动选左右两侧）；婚礼风会报 `WARNING caption on head`，这时换远一点的镜头 |
| 克隆模板滤镜后，阴天变成黄绿色 | 参考的高光被油菜花、树叶染成黄绿色。底色偏移已限幅，偏蓝和接近白的灰色受保护（见 imitate.md） |
| 新素材在总览图里是横的、被拉扁 | 手机和 Mimo 的文件是横着存的，带 -90° 旋转标记。`video_size` 现在会读取旋转标记 |
| `python` 命令直接退出、返回码 49 | Windows 应用商店的 python 别名坏了。直接用 `%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe` 这类真实路径 |
| 结尾卡一闪而过 | 最后一个镜头被音乐长度截短了。结尾卡现在至少停留 2.4 秒，并且从倒数 2.4 秒开始 |
| ffmpeg `lut3d` 找不到 .cube | Windows 盘符的冒号会破坏滤镜参数。`match_look.py apply` 在项目目录下用相对路径调用 |
| 剪映导出的模板视频 | `analyze_reference.py` 通过元数据里的 `TEEditor` 认出剪映，4K 60fps 也能正常拆解 |
