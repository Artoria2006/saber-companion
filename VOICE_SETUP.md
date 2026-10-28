# 本地 GPT-SoVITS 声线

本机已部署 GPT-SoVITS v2ProPlus，使用参考音频直接合成，无需为每个句子重新训练。它不是已经训练完成的 Saber 专用模型。日语参考可能把日语发音习惯带进中文；当前方案采用普通话主参考约束发音、日语辅助参考保留部分音色。音色相似度、情绪和普通话自然度仍需试听判断，自动转写正确不能替代听感验收。

## 已验证的环境与文件

- Windows，Python 3.11.15，RTX 4060 Laptop 8 GB，torch/torchaudio 2.5.1+cu121。
- 官方源码：https://github.com/RVC-Boss/GPT-SoVITS ，固定提交 `b4570b876f5c086819ba84e3215472733c6a7b70`。
- 独立根目录 `D:\saber-voice`：`.venv` 为运行环境，`GPT-SoVITS` 为源码和基础权重，`input` 为用户提供的音轨，`processed` 为人声分离及转写，`references` 为参考与准确转写，`samples` 为试听结果，`logs` 为服务日志。
- 基础模型与校验信息见 `scripts/download_gsv_models.py`；Windows 环境版本记录见 `requirements-gsv-windows.lock`。该锁文件用于已验证环境记录，不替代匹配显卡驱动与 CUDA 版 PyTorch 的安装。
- 音轨来自用户本地提供的两个视频文件；不上传音频、参考转写、权重、聊天记录或登录数据。第三方源码、模型和素材遵循各自许可。

## 本机启动与停止

Docker Desktop 先启动。PowerShell 在项目目录执行：

```powershell
& '.\scripts\start_gsv.ps1'
Invoke-RestMethod http://127.0.0.1:9880/health
```

启动脚本要求已经存在上述独立环境和模型；第一次加载需等待，日志路径会打印。健康检查返回 `ok: true` 后再启动机器人：

```powershell
docker compose build bot
docker compose up -d --no-deps bot
```

服务仅监听 `127.0.0.1:9880`，容器通过 `http://host.docker.internal:9880` 访问。没有安装 Windows 开机自启；电脑重启后需要重新运行启动脚本。停止时执行：

```powershell
& '.\scripts\stop_gsv.ps1'
```

只停止命令行匹配本项目路径的推理进程，不按 python.exe 名称批量结束程序。

## 配置说明

在 `config.toml` 的 `[voice]` 内设置以下字段；其他字段保留示例默认值。下面示例要求对应文件真实存在：

```toml
provider = "gpt_sovits" # 示例默认 edge；本地推理选 gpt_sovits
voice = "warm" # 本地模式必须匹配 references 中的名称
gpt_sovits_url = "http://host.docker.internal:9880" # 直接运行 Python 则用 http://127.0.0.1:9880
references = { warm = { audio_path = "D:/saber-voice/references/chinese-anchor.wav", text = "我在呢。今天辛苦了，先歇一会儿吧。", language = "zh", aux_audio_paths = ["D:/saber-voice/references/warm.wav"] } }
fallback_to_edge = true # 默认 true；本地合成失败尝试通用中文女声，并在日记标明回退
timeout_seconds = 90 # 示例默认25；本机为模型加载和推理留90秒
max_bytes = 5242880 # 示例默认2097152；本机提高到5 MiB
```

`audio_path` 是 Windows 推理服务看到的路径，不是 Docker 内路径。`text` 必须准确对应主参考说话内容；`language` 支持 zh、ja、en。`aux_audio_paths` 默认空列表，最多五个文件，仅作辅助音色参考，不需要其转写。服务限制所有参考文件都位于本机 `references` 目录。支持 neutral、warm、cheerful、serious、sleepy 五个名称，不要求全部配置。

模型只选择已经配置的语气名称；参考片段的情绪并不保证能精确控制每句输出。语速继续有效，音调参数不用于本地引擎。普通回复以文字为主，明确要求声音时合成短回复，主动语音仍遵守原有概率与冷却。

### 保留选定音色并微调节奏

`lock_reference = true` 会始终使用 `voice` 选定的主参考和辅助参考，避免不同语气切换声线；默认 false，保持旧版按语气选参考的行为。`emotion_rates = { warm = -2, cheerful = 3, sleepy = -4 }` 使温柔、开心、晚安分别在基础语速上变化 -2、+3、-4 个百分点；默认空映射，所有值限制在 -10 到 10，叠加后的总语速限制在 -50 到 25。模型未给语气时用关键词及当前参考名称判断，手动试听和 `/语音测试` 使用基础语速。

`fragment_interval_seconds` 默认 0.3 秒，本机试听方案为 0.18 秒，允许 0.1—1 秒。它只影响引擎分段边界，不控制每个逗号。这些参数是节奏调整，并非已经训练的情绪控制或任意强度的声优表演。日记分别记录实际参考 profile、语气 emotion 和是否锁定参考；语音措辞采用正常短句与标点，避免堆叠省略号和舞台指示。

## 素材处理与验收

公开下载脚本为 `scripts/download_voice_sources.ps1`。平台拒绝下载时会退出，不读取浏览器 Cookie 或处理验证码。已有文件无需重复下载。提取与分离：

```powershell
& 'D:\saber-voice\.venv\Scripts\python.exe' '.\scripts\prepare_voice_audio.py' 'D:\saber-voice\input\sample.mp4' --duration 600 --separate
```

FFmpeg 提取音轨；Demucs 分离人声，不能保证完全去除配乐。每次写入新目录，保留输入文件。转写工具 `scripts/transcribe_voice_sources.py` 使用本地 faster-whisper，自动结果需校对。选择单人、少混响、3—9 秒参考，避免把喊叫作为日常语音参考。

打开面板的“记忆与设置”，保存声线后点“本机试听”，然后“发到 QQ 测试”。核对活动日记中的 provider/profile 与最终发送回执，确保没有把回退声线误认为本地合成。试听普通聊天、疑问、承诺与晚安等不同句子，尤其检查口音、漏字和长停顿。

连接被拒绝：检查健康接口与推理日志。找不到参考：检查 Windows 路径及 references 目录。首次推理超时：先完成加载再试听。显存不足：关闭占用 GPU 的程序后重启本项目服务。普通话不自然：保留日语原参考，比较中文主参考加辅助音色的方案，不以转写正确宣称完全消除口音。


## QQ 来信语音识别

接收识别独立于 9880 合成服务，使用同一个 D 盘 Python 环境、已缓存的 `cache/asr-base`，监听 `127.0.0.1:9881`。启动 `scripts/start_asr.ps1`，停止 `scripts/stop_asr.ps1`。语音识别使用 CPU/int8，不占用合成用的 CUDA 模型；仍会占用 CPU 和内存。服务不保存请求音频，支持60秒/8 MiB默认限制、静音和低分数拒绝；完整配置与 QQ 测试步骤见 README 第12节。无需新增密钥，环境中已有 faster-whisper、ctranslate2、PyAV 和 VAD 依赖。
