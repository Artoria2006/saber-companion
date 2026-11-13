# QQ 电话实验记录

> 仓库现已包含电话桥所需的上游桥源码和本地修改，来源及许可见 [NOTICE](third_party/qq-call/NOTICE.md)。此功能是非官方实验，构建镜像不代表真实 QQ 通话已通过；不会自动发送电话或替用户登录。

从项目根目录构建独立实验镜像（需要 Docker、网络和较多下载时间）：

```powershell
docker build -f Dockerfile.qq-call -t saber-qq-call:lab .
```

基础文字聊天不需要构建该镜像。使用实验配置前需要自己的 QQ 登录、先在面板绑定私聊、启动本地识别与合成服务，再准备授权文件；仅在本人明确希望接听时启用。不同系统、NapCat 或 QQ 版本的真实通话仍需单独验收。以下旧记录保留了当时的测试状态，不代表当前启用状态。

## 新用户的 Windows Docker 操作顺序

1. 先按 README 跑通文字私聊，确认手机使用的是另一个 QQ 账号；在管理面板选择该私聊并绑定为伴侣。电话只接受绑定的私聊号码。
2. 按 [本地声线教程](VOICE_SETUP.md)准备 GPT-SoVITS、参考音频和 Whisper base；在 `config.toml` 设置 `[voice]` 的 `enabled = true`、`provider = "gpt_sovits"` 和正确参考，在 `[asr]` 设置 `enabled = true`。按该教程启动两个本机服务，分别访问 `http://127.0.0.1:9880/health` 和 `http://127.0.0.1:9881/health`，确认均返回 `ok: true`。
3. 在项目目录执行下面的 PowerShell 命令。这会重建机器人镜像并重启 bot，保留 NapCat；电话授权文件由容器内程序生成，不需要在宿主机另装 Python。

```powershell
docker compose build bot
docker compose up -d --no-deps bot
docker compose exec -T bot python scripts/prepare_qq_call.py
docker build -f Dockerfile.qq-call -t saber-qq-call:lab .
```

如果提示没有绑定私聊，先向机器人私聊一条消息，再在面板绑定正确的会话并重新执行准备命令。如果提示已有授权号码不一致，不要覆盖文件；先核对并妥善处理 `data/qq-call` 内的本机授权数据。

4. 准备命令不会自动开启接听。确认确实希望该账号的 QQ 私聊来电被自动接听后，在项目目录执行：

```powershell
docker compose exec -T bot python -c "from pathlib import Path; p=Path('/app/data/qq-call'); assert not (p/'disabled').exists(), '电话实验处于禁用状态，请先检查 disabled 标记'; assert (p/'allowed-uin').is_file() and (p/'access-token').is_file(), '先执行授权准备'; (p/'armed').touch(); print('已允许绑定账号的电话自动接听')"
docker compose -f docker-compose.yml -f docker-compose.qq-call.yml up -d --no-deps bot napcat
```

切换 NapCat 镜像会重启协议端，可能需要重新扫码。先在 WebUI 确认 QQ 登录并检查 `docker compose logs --tail 100 bot napcat`；本机两个语音健康检查也要保持通过。然后由已绑定的账号主动发起私聊语音，确认接听和双方声音；插件、QQ 版本、模型与网络都可能使测试失败。日志不要公开账号、口令或对话。

5. **停止自动接听**：在项目目录执行下列命令，再等待当前电话结束。该操作只删除启用标记，不删除授权文件或聊天数据：

```powershell
docker compose exec -T bot python -c "from pathlib import Path; Path('/app/data/qq-call/armed').unlink(missing_ok=True); print('已停止后续电话自动接听')"
```

如果存在 `data/qq-call/disabled`，说明本机曾明确暂停实验；先排查并由使用者自行决定是否移除该标记，脚本不会自动解除暂停。无需电话时可按下文恢复基础镜像。

当前为本机实验功能，已完成一次真实 QQ 电话接通和语音回复测试，速度及打断效果仍需持续验证。它依赖 Linux NapCat 的内部 AVSDK 接口，升级 QQ 或 NapCat 后需要重新验证。使用者必须自行登录自己的 QQ；建议只做私聊测试。来电号码未经解析或未匹配本机绑定伴侣账号、音频工作进程未就绪时，桥拒绝自动接听。不要把授权文件、口令、QQ 登录数据提交到版本库。

实验容器使用 `saber-qq-call:lab`，桥来源于 GPL-3.0-only 开源项目 [maibot-qq-voice-call](https://github.com/ClaudiaGardner/maibot-qq-voice-call)，固定提交及本地修改见 NOTICE。NapCat 4.18.41 默认只加载官方白名单插件；实验镜像对其加载器增加一项精确例外，仅接受路径与 SHA-256 都匹配的电话桥，其他插件的白名单检查保持原样。这是本地兼容补丁，不是 NapCat 官方支持。

完成授权文件和启用标记后，使用上面的 Compose 双文件命令启动实验配置。

需要取消实验配置时，运行 `docker compose -f docker-compose.yml up -d --no-deps bot napcat`，即可恢复原机器人镜像；QQ 数据卷和对话数据库仍保留。由实验安装器添加的 NapCat 插件启用条目可能仍保留在配置卷中，原镜像不包含该插件。`data/qq-call` 中存有专用口令和授权账号，属于私有数据。

语音链路目前使用 VAD 分句、本地 Whisper、现有模型和 GPT-SoVITS，支持检测用户插话后停止播放；QQ 电话可流式接收模型文本并逐句合成语音，但并非端到端实时音频流；音质、回声、延迟及挂机后的释放仍需持续验证。

## 当前状态（2026-10-28）

已验证登录后插件能加载，但 AVSDK 启动后出现高频初始化重试，原因尚未确定。已停止 AV Host 和语音工作进程，清除就绪标记，并在本机写入 `data/qq-call/disabled` 使后续重建默认暂停电话实验；普通 QQ 聊天保持在线。不要删除该暂停标记或发起 QQ 电话测试，直到完成故障排查和受限重试验证。上游实验源码中已限制自动初始化次数，但修复原因和真实来电验收仍未完成。

## 初始化重试修复（2026-10-28）

在无网络、无 QQ 登录态的隔离 AV Host 中观察到 20050 和 120043 事件，因此不能凭这两个事件判断登录失败。实验桥已移除由这两个事件触发的自动重复登录，并限制网络错误重试次数；AV Host 异常退出不自动重启，自动接听需要初始化回执、正常音频服务、来电号码与人工启用标记同时满足。模拟测试已通过；真实账号上的初始化和 QQ 来电仍等待验证。当前没有创建 `data/qq-call/armed`，因此暂不会自动接听。

## 电话响应优化

电话回复按短句逐段合成，第一段准备好就播放，后续句子依次播放；句尾检测约等待 0.6 秒。用户开口时停止正在播放的声音，识别出有效语音后取消上一轮生成并接话，降低杂音误打断。保留现有语音参考、语速配置和伴侣会话记忆。QQ 电话边接收模型文本边按短句合成，网页电话仍等待完整回复；语音合成按句进行，不是端到端实时音频流；打断实际效果取决于 QQ 音频缓冲、识别速度和环境噪声。

## 后续部署说明

上面的初始化排查章节记录当时状态，不代表当前启停状态。QQ 电话使用最近 8 条对话、滚动摘要和显式记忆生成回复，原有会话历史仍按配置保存。实际能否接听取决于 QQ 登录、工作进程和启用标记；模型、语音合成及网络速度会影响延迟。

QQ 电话的收音使用 WebRTC VAD（`webrtcvad-wheels==2.0.14`）结合音量门槛判断是否开始录音；句尾静音约 0.8 秒。它可以减少部分非人声触发，但不能识别说话者或保证消除外放回声；耳机和安静环境仍有帮助。电话文本分句稍长，可能让首句略慢，保留原有声线参考和合成参数。依赖位于 `requirements-qq-call.txt`，实验镜像构建时还需为其 Linux Python 版本准备对应 wheel。

本机识别服务可通过 `D:\saber-voice\asr-model.txt` 选择 `base` 或 `small`，文件不存在时使用 `base`。修改后运行 `scripts/stop_asr.ps1`，再运行 `scripts/start_asr.ps1`，用 `http://127.0.0.1:9881/health` 确认模型。`small` 在两条本机样本中识别更准确，但 CPU 识别约多花 0.7—1 秒；真实通话效果和实际延迟仍需要测试。
