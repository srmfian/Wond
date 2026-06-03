# Wond

Wond 是一个本机优先的个人上下文系统。它把 Mac 上的日常活动、文件内容、移动端录音、位置和照片/媒体分析写入本地 SQLite，然后生成日报、长期摘要、邮件 digest，并提供 dashboard、doctor 和同步服务来检查运行状态。

系统默认走本地 AI：文本/视觉模型通过 Ollama，语音转写通过 MLX Audio。OpenAI 相关配置仍然保留为可选后端，但当前主路径不依赖 OpenAI。

## 主要能力

- Mac 上下文采集：日历、提醒事项、浏览器历史、最近文件、前台应用、邮件元数据、照片/媒体线索等。
- 文件与媒体分析：扫描配置目录中的新文件，分析文档、图片、音频和视频，并把结果写回数据库。
- 音频处理：用本地 ASR 转写录音，生成摘要、speaker 线索和 `no_speech` 标记；可在处理成功后删除原始音频。
- 移动端采集：iPhone 可以录音、打点、添加 quick tag、记录位置，并通过加密同步上传到 Mac；Apple Watch 录音支持已经移除，Watch target 只保留占位 companion。
- 移动端问答：iPhone 可以通过 Wond sync server 调用本地搜索问答，答案和引用仍由 Mac 上的本地索引/模型生成。
- 地址级位置：移动端不只记录经纬度，也会保存反向地理编码结果，例如街区、路名、门牌号、行政区、市、国家等字段。
- 报告与检索：日报、长期摘要、邮件摘要、全文搜索索引和本地 dashboard。
- 运行诊断：`doctor`、`status`、`dashboard` 和 sync server `/health` 用来检查当前运行状态。

## 快速开始

### 一键安装包

从 GitHub Release 下载 `Wond-0.1.0-macos.zip`，解压后双击 `install.command`。

安装器会把 Wond 复制到 `~/Applications/Wond`，创建专用 Python virtualenv，初始化 `config.json`，并可选择一次性加载 dashboard、sync server 和后台 monitor 的 LaunchAgent。重复安装会保留已有 `config.json`、`.venv/` 和 `data/`。

如果需要指定安装目录：

```bash
WOND_INSTALL_DIR=/path/to/Wond ./install.command
```

安装后常用入口：

- `~/Applications/Wond/Start Wond Dashboard.command`
- `~/Applications/Wond/Install Wond Services.command`
- `~/Applications/Wond/Run Wond Doctor.command`

### 源码运行

```bash
python3 -m wond init
python3 -m wond collect
python3 -m wond summarize
```

常用检查命令：

```bash
python3 -m wond status
python3 -m wond doctor
python3 -m wond dashboard --open
```

`python3 -m wond` 是当前入口；旧项目名下的 Python module、LaunchAgent label 和移动端同步标识已移除。

常用后台服务：

```bash
python3 -m wond install-agent --load
python3 -m wond install-sync-agent --load
python3 -m wond install-dashboard-agent --load
python3 -m wond monitor --once
```

同步服务也可以手动启动：

```bash
python3 -m wond sync-server
```

默认 dashboard 地址是 `http://127.0.0.1:8787`，移动端同步服务默认监听 `0.0.0.0:8765`。

## 数据目录

默认数据都在 `data/` 下：

- `data/wond.sqlite3`：主数据库。
- `data/reports/`：日报和移动端导入报告。
- `data/summaries/`：长期摘要和 compact 输出。
- `data/mobile_sync/inbox/`：移动端同步包落盘目录。
- `data/mobile_sync/imports/`：解包后的移动端媒体与导入内容。
- `data/file_analysis_workspace/`：用户目录文件分析前的工作副本区，原文件不会被移动。
- `data/recycle_bin/`：移动端清理文件和文件分析工作副本会先进入回收区。
- `data/speaker_samples/`：speaker review 保存的样本。
- `data/search_index/`：全文搜索索引。

`config.json` 是当前机器的真实配置，`config.example.json` 是模板。提交或分享配置前请检查 token、邮箱地址、模型路径和本地目录。

## 配置重点

核心字段：

```json
{
  "data_dir": "data",
  "timezone": "Asia/Tokyo",
  "watch_paths": ["~/Desktop", "~/Documents", "~/Downloads"],
  "collectors": {
    "foreground_app": true,
    "calendar": true,
    "reminders": true,
    "browsers": true,
    "recent_files": true,
    "messages": true,
    "apple_mail": true,
    "photo_locations": true
  },
  "ai_backend": {
    "provider": "local"
  }
}
```

本地 AI 常用字段：

```json
{
  "local_ai": {
    "ollama_base_url": "http://127.0.0.1:11434",
    "text_model": "qwen3.5:35b",
    "vision_model": "qwen3.5:35b",
    "search_embedding_candidates": [
      "bge-m3:latest",
      "bge-m3",
      "qwen3-embedding:4b"
    ],
    "transcription_backend": "mlx_audio",
    "transcription_model": "mlx-community/Qwen3-ASR-1.7B-8bit",
    "speaker_diarization_enabled": true,
    "speaker_diarization_backend": "vibevoice_mlx",
    "speaker_diarization_model": "mlx-community/VibeVoice-ASR-4bit",
    "vad_presegment": true,
    "vad_presegment_diarization": true,
    "diarization_vad_max_chunk_seconds": 120,
    "diarization_vad_max_chunks": 32
  }
}
```

音频预处理常用字段：

```json
{
  "audio_preprocessing": {
    "enabled": true,
    "asr_enabled": true,
    "diarization_enabled": true,
    "speaker_samples_enabled": true,
    "speech_filter": "highpass=f=80,lowpass=f=7800,afftdn=nf=-25,dynaudnorm=f=150:g=15,loudnorm=I=-18:TP=-1.5:LRA=11",
    "overlap_separation_enabled": true,
    "overlap_separation_backend": "speechbrain_sepformer",
    "overlap_separation_fallback_enabled": true,
    "overlap_separation_fallback_backend": "ffmpeg_bandpass",
    "overlap_sepformer_model": "speechbrain/sepformer-whamr16k",
    "overlap_sepformer_model_dir": "models/speechbrain_sepformer",
    "overlap_create_new_speakers": false
  }
}
```

如果 Hugging Face / MLX 模型目录被移动到外置盘或做了重定向，要保证后台 LaunchAgent 运行时也能看到同一个路径。外置盘未挂载、`HF_HOME` 不一致或 symlink 失效时，音频分析可能会变慢、失败或重新下载模型。
正文转写默认走较快的 `mlx_audio` / Qwen3 ASR；speaker 标注是独立的辅助阶段，优先用 `vibevoice_mlx` / `mlx-community/VibeVoice-ASR-4bit` 只给 speech window 打 Speaker 1 / Speaker 2 标签。VibeVoice 失败或超时时不会丢掉正文转写，只会让该条音频保留为待修复的 speaker 状态。
ASR、diarization 和 speaker sample 会优先使用增强后的临时音频；原始音频仍保留作修复窗口和审计。多人重叠说话片段会被标记为 overlap，系统会优先用 SpeechBrain SepFormer 生成候选 stem，并通过音量、时长、削波等质量门控后才纳入 speaker matching；SepFormer 不可用时会降级到 `ffmpeg_bandpass`。默认不会只凭重叠候选创建全新说话人，避免污染声纹库；如果接入其他外部分离器，可以开启 `overlap_create_new_speakers` 或配置 `overlap_separation_command`。

## Dashboard 与 Doctor

Dashboard 是日常查看入口：

```bash
python3 -m wond dashboard --open
python3 -m wond install-dashboard-agent --load
```

它包含 overview、doctor、audio queue、search、timeline、reports、sources、speakers、sync 和 settings 等页面。适合查看最近采集、音频队列、speaker review、移动端同步状态和配置概览。

Doctor 用于命令行诊断：

```bash
python3 -m wond doctor
```

它会检查 collector、sync server、本地 AI、音频工具、聊天来源和数据目录。若后台任务行为异常，先看：

```bash
python3 -m wond status
python3 -m wond doctor
```

## 文件、媒体与音频分析

扫描新文件：

```bash
python3 -m wond analyze-new-files
```

处理已导入的移动端音频队列：

```bash
python3 -m wond analyze-audio
python3 -m wond analyze-audio --date today --limit 20
python3 -m wond analyze-audio --force
```

分析图片、视频或其他媒体：

```bash
python3 -m wond analyze-media /path/to/file
```

自动新文件分析不会移动 `Desktop`、`Documents`、`Downloads` 等用户目录里的原文件；它会先复制到 `data/file_analysis_workspace/`，分析副本，之后只回收这个副本。只有 `data/mobile_sync/` 下的导入媒体在 `mobile_sync.delete_audio_after_analysis` 开启时允许清理原文件。回收区命令：

移动端音频会先完成转写和 speaker 处理再删除原始文件。若转写出了 speech segment 但没有 speaker label，系统会写入 `speaker_processing.status=skipped_no_speaker_labels`，并按 `mobile_sync.delete_audio_after_analysis_repair_window_hours` 保留原始音频一段时间，方便之后用更好的 diarization 模型重跑或修复样本。

```bash
python3 -m wond recycle-bin list
python3 -m wond recycle-bin restore <trash-path>
python3 -m wond recycle-bin purge
```

短录音、静音片段和无有效语音的片段会被标记为 `no_speech`。这不是错误；它表示 ASR 没有检测到可用文本。

## iPhone 采集与 Watch 占位

iOS 工程在 `ios/Wond/Wond.xcodeproj`。

当前实际采集入口是 iPhone app：

- iPhone 可以连续分段录音、打点、添加 quick tag、记录位置、查看同步状态，并用后台 URLSession 上传加密包。
- iPhone 可以在 Ask 页面向 Mac 发起本地搜索问答请求，使用同一个 sync URL 和 token。
- Quiet Hours / schedule 可以在夜间或指定时间自动停止 iPhone 录音，避免静默时间采集。
- Watch app 目前只显示“Watch recording removed”，不再暴露录音、麦克风权限、后台 audio、WatchConnectivity 传输或 iPhone fallback 控制。

移动端会导出这些事件类型：

- `audio_segment`：录音片段。
- `bookmark`：用户打点。
- `quick_tag`：重要、待办、想法、会议、忽略等快速标签。
- `location_sample`：位置样本。

### 位置与地址

位置功能已经不只是经纬度。iPhone 会用 Core Location 获取坐标，并通过反向地理编码保存大致地址字段：

- `address`：系统格式化后的地址。
- `placeName`：地点名。
- `country` / `isoCountryCode`：国家。
- `administrativeArea` / `subAdministrativeArea`：都道府县、省、市等行政区。
- `locality` / `subLocality`：市区町村、区、街区等。
- `thoroughfare` / `subThoroughfare`：道路名和门牌号。
- 经纬度、高度、精度、速度和方向仍会保留，方便后续排错或重新解析。

所以在日本可能会显示类似“六本木 1 丁目 2 番 11 号”的区域信息，在中国也可以记录到“XX 市 XX 区 XX 路 XX 号”这类地址层级。实际粒度取决于 iOS 定位权限、网络、地图数据和当前位置。

如果 iPhone 端 Location 区域显示 `kCLErrorDomain error 1`，通常是定位权限被拒绝。请在 iOS 设置里允许 Wond 使用定位；如果需要后台或连续记录，建议允许更高等级的位置权限。

## 移动端加密同步

Mac 端启动同步服务：

```bash
python3 -m wond sync-server
```

移动端同步使用：

- AES-GCM 加密 `.pcsync` 包。
- PBKDF2-HMAC-SHA256 派生密钥。
- HMAC 请求认证。
- `/ask` 问答接口复用同一套 HMAC token，请求在 Mac 上完成检索和本地模型回答。
- per-event fingerprint 去重。
- background URLSession，允许 iPhone app 进入后台后继续完成上传。

Mac 端导入命令：

```bash
python3 -m wond ingest-mobile data/mobile_sync/imports/<id>/mobile-export.json
```

或由 sync server 自动导入。`skip_existing_uploads` 与 event fingerprint 会避免重复导入已经接受过的事件；如果只新增了少量录音或位置样本，新的事件仍会被上传和导入。

清理移动端同步缓存：

```bash
python3 -m wond mobile-sync-cleanup
```

## Apple Watch 状态

Apple Watch 录音支持已经移除。仓库里仍保留 watchOS target，是为了让已有配对安装可以更新到一个安全的占位 companion；它不再请求麦克风权限，也不再处理后台录音、WatchConnectivity 音频传输或 iPhone fallback。

如果已经安装过 Watch app，重新安装 iPhone app 后，配对 Watch 上应只看到录音已移除的提示。需要采集音频时，请使用 iPhone app。

## Speaker Review

查看 speaker：

```bash
python3 -m wond speakers list
```

review、重命名、合并和样本检查：

```bash
python3 -m wond speakers review
python3 -m wond speakers rename <speaker-id> <name>
python3 -m wond speakers merge <source-id> <target-id>
python3 -m wond speakers merge-many <target-id> <source-id> [<source-id> ...]
python3 -m wond speakers samples <speaker-id>
python3 -m wond speakers matches <speaker-id>
python3 -m wond speakers profile <speaker-id>
```

整理和修复 speaker 样本：

```bash
python3 -m wond speakers auto-organize --apply --threshold 0.68
python3 -m wond speakers confirm <speaker-id> [<speaker-id> ...]
python3 -m wond speakers unhide <speaker-id> [<speaker-id> ...]
python3 -m wond speakers delete-many --apply <speaker-id> [<speaker-id> ...]
python3 -m wond speakers detach-sample <sample-id>
python3 -m wond speakers repair-samples
python3 -m wond speakers repair-sample-text --apply
python3 -m wond speakers repair-sample-clips --apply
python3 -m wond speakers reset-regroup-samples --apply --threshold 0.68 --max-merges 500
```

Speaker 结果来自本地音频分析和样本匹配，适合做人工校正，不应当当作绝对身份判断。`reset-regroup-samples` 会重置样本分组，适合大规模重整前有数据库备份时使用。

## 报告、长期摘要与邮件

生成日报：

```bash
python3 -m wond summarize
```

压缩长期上下文：

```bash
python3 -m wond compact
```

保留策略：

```bash
python3 -m wond retention
```

邮件摘要：

```bash
python3 -m wond email-summary
python3 -m wond email-due
```

## 搜索索引

构建或刷新全文搜索索引：

```bash
python3 -m wond search-index
```

之后可以在 dashboard 的 search 页面查找已经导入和分析过的内容。

## 常见排查

- `status` 显示 agent 未运行：重新执行 `install-agent --load` 或检查 LaunchAgent 日志。
- sync server 不通：先打开 `http://127.0.0.1:8765/health` 或执行 `python3 -m wond status`。
- dashboard 不通：重新执行 `install-dashboard-agent --load`，再打开 `http://127.0.0.1:8787`。
- 音频分析失败：检查外置模型盘、`HF_HOME`、`ffmpeg`、MLX Audio、Ollama 和 LaunchAgent 的 PATH。
- Location 报 `kCLErrorDomain error 1`：iOS 定位权限被拒绝或未授予足够权限。
- Watch 仍显示旧录音界面：重新安装/更新 iPhone app 和配对 Watch app；当前 Watch target 只应显示录音已移除。
- 新文件分析卡住：检查是否有临时锁文件，例如 Office 的 `~$...pptx`，这类文件经常不是完整文档；正常文件会先复制到 `data/file_analysis_workspace/` 再分析。

## License

Wond is released under the MIT License. See [LICENSE](LICENSE) for details.
