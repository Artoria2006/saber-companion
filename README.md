> [!IMPORTANT]
> **开源协议声明 · AGPL-3.0**
>
> 欢迎自由部署、学习和修改 **saber-companion**！本项目自本次协议变更起采用 [GNU AGPL-3.0](LICENSE)。分发本项目或衍生作品时，请遵守协议中保留版权与许可声明、提供相应源代码等要求；修改本项目并通过网络提供服务时，还须依照协议第 13 条向远程交互用户提供获取该修改版本相应源代码的机会。
>
> **未经相关权利人另行授权，严禁违反 AGPL-3.0 的义务，将本项目或衍生作品闭源分发、闭源商业倒卖。** 欢迎遵守协议的商业使用和收费服务，无须为此额外申请商业授权。本声明是协议要求的说明，不增加 AGPL-3.0 之外的限制，具体权利义务以 [LICENSE](LICENSE) 正文为准。
>
> 已经以 MIT 协议发布的历史版本仍保留原有授权；第三方组件继续遵循各自协议。

# Saber Companion

基于 NoneBot2、NapCat 与 OpenAI 兼容 API 的 QQ 个人陪伴助手，支持 Saber 人格、持久记忆、主动聊天和国内公开内容搜索。项目代码使用 AGPL-3.0 协议。不附带 QQ 账号、登录态或 API Key；使用者通过手机 QQ 扫码登录。NapCat、QQ 和依赖软件分别遵循各自协议。

当前为实验版本：已在开发者本机验证真实登录和模型调用，仍需要更多设备的安装与长期运行反馈。开发计划见 [ROADMAP.md](ROADMAP.md)。GitHub 仓库保存源码，机器人需要在自己的电脑或常开服务器上运行。

Python 3.10+，NoneBot2 2.4.3，OneBot v11 适配器 2.4.6，NapCat v4.18.41；Docker 内使用 Python 3.11.15。模型接口使用 Chat Completions，供应商必须支持 `messages` 和 `max_tokens`。

更新记录见 [CHANGELOG.md](CHANGELOG.md)。

## 1. 系统要求与安装

推荐 Windows 11 x64 + Docker Desktop（Linux 容器），或 Ubuntu 22.04/24.04 x64 + Docker Engine 与 Compose v2。建议 2 核 CPU、4 GB 内存、10 GB 可用磁盘；这不是运行内存保证。需要网络访问 GitHub、Docker Hub、PyPI、QQ 服务及模型服务商。

- Windows：先安装 Git（https://git-scm.com/downloads/win），再按 https://docs.docker.com/desktop/setup/install/windows-install/ 安装 Docker Desktop、启用 WSL2，打开 Docker Desktop，等待 Engine running。
- Ubuntu：按 https://docs.docker.com/engine/install/ubuntu/ 安装 Docker Engine 和 docker-compose-plugin；执行 `sudo apt-get update`、`sudo apt-get install -y git`。若当前用户不能运行 Docker，下面的 Docker 命令加 `sudo`。
- 验证：`git --version`、`docker version`、`docker compose version`。三项均成功后继续。Docker 路线不需要宿主机 Python、Node.js 或手工安装 QQ。
- 准备手机 QQ 以及模型服务商的 API Key；默认模型为 OpenAI 的 `gpt-4o-mini`，需要该项目具备调用权限和可用额度。

获取项目并进入目录：

```bash
git clone https://github.com/Artoria2006/saber-companion.git
cd saber-companion
```

## 2. Docker 启动

Windows PowerShell：`Copy-Item config.example.toml config.toml`。
Linux：`cp config.example.toml config.toml`。

生成两次独立密钥：`docker run --rm python:3.11.15-slim python -c "import secrets; print(secrets.token_urlsafe(32))"`。分别填入 `server.access_token` 与 `napcat.webui_token`。该命令只打印随机密钥，不生成账号。

打开 `config.toml`，填入 `model.api_key`；使用其他兼容服务时同时填入它提供的 `base_url` 和模型 ID。其余默认值可用于 Docker 首次启动。

执行 `docker compose up -d --build`，再执行 `docker compose logs -f init bot napcat`。首次构建会下载 Python 包和 tiktoken 编码数据（openaipublic.blob.core.windows.net）；失败时检查网络后重新构建。`init` 以退出码 0 结束是正常状态。

浏览器打开 http://127.0.0.1:6099/webui/ ，使用配置中的 WebUI 密钥进入，选择 QQ 登录、QRCode，用手机 QQ 扫码并确认。NapCat 可能在登录时轮换 WebUI Token、要求修改密码；若原密钥失效，以 NapCat 控制台日志显示的新 Token 重新进入，并将最终使用的密钥写回 `config.toml`。

出现 `[protocol] connected` 后，用另一个 QQ 号私聊机器人“你好”；群里通过 QQ 成员选择器真正 @机器人，再发送“你好”。群内不 @ 时不会回复。

修改配置后执行 `docker compose down`，再执行 `docker compose up -d --build`。不要加 `-v`；它会删除登录数据卷。启动时会重建 NapCat 网络配置及 WebUI 初始密钥，不保留在 WebUI 中临时修改的网络参数。

## 3. NapCat 固定版本与反向 WS

- 固定版本：v4.18.41。
- 发布页：https://github.com/NapNeko/NapCatQQ/releases/tag/v4.18.41
- Shell 直接下载：https://github.com/NapNeko/NapCatQQ/releases/download/v4.18.41/NapCat.Shell.zip
- Windows 一键包下载：https://github.com/NapNeko/NapCatQQ/releases/download/v4.18.41/NapCat.Shell.Windows.OneKey.zip
- Docker 镜像：`mlikiowa/napcat-docker:v4.18.41`，不要换成 `latest` 后继续声称版本固定。

Docker 已自动生成反向连接，无须重复新建。核对位置：WebUI 登录后进入“网络配置”，找到名为 `qq-ai` 的 WebSocket 客户端。手工安装则点击“新建”，选择“WebSocket 客户端/反向 WebSocket”，填写 URL、Token，消息格式选 `array`，勾选“保存时启用”。不是 WebSocket 服务端。

| 部署方式 | URL |
| --- | --- |
| 本项目两个 Docker 服务 | `ws://bot:8080/onebot/v11/` |
| NapCat 与 Python 都在同一宿主机 | `ws://127.0.0.1:8080/onebot/v11/` |

Token 填 `server.access_token` 原文；不要加 `Bearer ` 前缀。重连间隔 5000 毫秒，心跳 30000 毫秒，消息格式 array，上报自身消息关闭。WebUI 的 6099 端口不接收 OneBot 消息；容器内的 localhost 指向容器自身。

## 4. 配置项逐行解释

`config.example.toml` 的每个字段后均有默认值含义、单位和填写要求；所有段均必填，运行时只读取复制后的 `config.toml`。没有 `.env` 覆盖，也不要求填写 QQ 号。

| 字段 | 默认值 | 作用 |
| --- | --- | --- |
| server.host | 0.0.0.0 | 接收反向 WS 的监听网卡 |
| server.port | 8080 | 监听端口；Docker 保持 8080 |
| server.access_token | CHANGE_ME_WS | 必须替换，WS 双方共享的随机密钥，至少 24 字符 |
| server.log_level | INFO | DEBUG/INFO/WARNING/ERROR；通常保持 INFO |
| model.base_url | https://api.openai.com/v1 | Chat Completions API 根地址，不能填网页聊天地址 |
| model.api_key | CHANGE_ME_API_KEY | 必须替换为供应商 API Key |
| model.model | gpt-4o-mini | 必须是所填服务可调用的模型 ID |
| model.context_tokens | 8192 | 本地输入加输出总预算，不能超过服务实际窗口 |
| model.max_output_tokens | 512 | 输出预留及请求 max_tokens |
| model.encoding | cl100k_base | 本地估算分词器；另一内置选择 o200k_base |
| model.token_safety | 1.25 | 输入估算安全系数，至少 1；不是跨模型精确计数保证 |
| model.timeout_seconds | 45.0 | 每次请求超时秒数；SDK 自动重试关闭 |
| model.extra_body | {} | 可选的供应商请求扩展；DeepSeek 普通聊天填写 `{ thinking = { type = "disabled" } }` |
| chat.history_messages | 20 | user 与 assistant 消息合计上限，必须正偶数 |
| chat.max_sessions | 1000 | 持久化会话上限；满后拒绝新会话，不删除已有记忆 |
| chat.default_persona | saber | 新会话默认人格键 |
| chat.system_prompt | 请用中文回答，准确、友善；不确定时明确说明。 | 每次模型请求的 system 前缀 |
| chat.max_input_chars | 6000 | 当前输入字符上限 |
| chat.max_reply_chars | 1500 | 单次发出字符上限，超出直接截断 |
| chat.session_interval_seconds | 10.0 | 同一会话请求接纳间隔，秒 |
| chat.send_interval_seconds | 3.0 | 全局发送尝试间隔，秒 |
| personas.assistant | 你是一个认真、简洁的中文助手。 | 通用人格追加提示词 |
| personas.teacher | 你是耐心的老师，先解释思路，再给出例子。 | 教师人格追加提示词 |
| personas.friend | 你是温和的聊天伙伴，语气自然，不编造个人经历。 | 朋友人格追加提示词 |
| napcat.webui_token | CHANGE_ME_WEBUI | 必须替换；至少 24 字符，与 WS 密钥分开 |
| napcat.reverse_ws_url | ws://bot:8080/onebot/v11/ | NapCat 主动连接地址 |

新增配置也集中在 config.toml，旧配置缺少这些字段时会自动使用下列默认值：

| 字段 | 默认值 | 作用 |
| --- | --- | --- |
| model.transient_retries | 1 | 连接错误、超时的额外重试次数；0 表示关闭，最多 2 次 |
| chat.queue_size | 30 | 内存等待队列上限，满时限频提示 |
| chat.queue_ttl_seconds | 180.0 | 排队过期秒数，避免回复过时问题 |
| chat.workers | 2 | 并行会话数量；同会话仍按入队顺序处理 |
| chat.companion_qq | 0 | 默认不绑定恋人账号；填写本人 QQ 号后，仅该账号的私聊使用已确认的 Saber 伴侣关系，群聊和其他联系人保持普通社交语气 |
| storage.path | data/assistant.sqlite3 | 项目 data 目录中的 SQLite 文件；Docker 将该目录绑定到宿主机 |
| storage.max_memories | 20 | 每个发言人在每个会话的显式记忆上限 |
| storage.max_memory_chars | 300 | 每条显式记忆的字符上限 |
| proactive.enabled | true | 允许本人通过私聊命令选择开启；不是全体用户自动开启 |
| proactive.idle_minutes | 60 | 本人没有发言、也没有主动任务的最短空闲分钟数，最小 5 |
| proactive.check_seconds | 60.0 | 后台检查间隔秒数，最小 5 |
| proactive.max_daily_attempts | 4 | 每人每天的主动任务上限；失败和不打扰也占名额；每个任务最多选题和写回复各一次模型调用，并各自遵守网络重试配置 |
| proactive.quiet_start_hour | 22 | 北京时间安静时段开始小时 |
| proactive.quiet_end_hour | 8 | 北京时间安静时段结束小时；不影响正常回复 |
| proactive.sources | 少数派、机核、IT之家 RSS URL 数组 | 未开启搜索时，由模型自主选择一个国内公开来源；不固定轮播 |
| proactive.search_enabled | false | 启用 DeepSeek 官方独立搜索 API；需要 model.base_url 使用 DeepSeek 官方地址；本机 DeepSeek 配置已开启 |
| proactive.search_domains | 国内内容站点域名数组 | 搜索结果接受 .cn 域名或该数组中的域名及子域，阻止海外默认来源和伪装的域名后缀 |
| proactive.interests | 国内生活、饮食、自然、科技、阅读、文化等 | 用自然语言描述自主兴趣；默认不因 Saber 身份追踪 Fate/FGO |
| proactive.fetch_timeout_seconds | 12.0 | 单个网络操作超时秒数；整次读取最多其两倍 |
| proactive.max_page_bytes | 262144 | 单页解码后下载大小上限，单位字节 |
| proactive.max_page_chars | 3500 | 进入模型的网页文字字符上限 |
| dashboard.enabled | true | 开启本机管理面板；Docker 地址为 http://127.0.0.1:8099/panel/ |
| dashboard.access_token | 空字符串 | 默认使用 napcat.webui_token 登录；填写独立口令时至少 24 字符 |
| dashboard.activity_limit | 1000 | 数据库保留的实际活动记录上限，允许 100—10000 条 |
| stickers.enabled | true | 允许模型从本地图片库选择表情；不允许模型提供图片网址或任意路径 |
| stickers.builtin_dir | assets/stickers | 随项目提供的四张原创示意表情目录 |
| stickers.upload_dir | data/stickers | 面板上传的自定义表情目录，保存在本机并跨重启保留 |
| stickers.max_bytes | 1048576 | 单张图片上限 1 MiB，支持 PNG、JPEG、GIF、WebP；可设置 1024—5242880 字节 |
| stickers.min_interval_seconds | 300.0 | 同一会话自动配表情至少间隔五分钟；手动表情测试可跳过这个冷却 |
| voice.enabled | false | 开启在线中文语音合成；本机已开启，公共示例默认关闭 |
| voice.voice | zh-CN-XiaoxiaoNeural | 晓晓中文女声；也可选 zh-CN-XiaoyiNeural（晓伊） |
| voice.rate_percent | -8 | 语速百分比调整，默认减慢 8%，允许 -50—25 |
| voice.pitch_hz | -2 | 音调 Hz 调整，默认降低 2 Hz，允许 -20—20 |
| voice.proactive_probability | 0.25 | 纯闲聊主动回复使用语音的概率，允许 0—1；含阅读来源的分享仍发文字 |
| voice.min_interval_seconds | 3600.0 | 同一私聊的自动语音至少间隔一小时，明确请求和测试不受此间隔限制 |
| voice.max_chars | 180 | 最长合成正文字符数，允许 40—300；超出时退回完整文字 |
| voice.max_bytes | 2097152 | 合成音频大小上限 2 MiB，允许 1024—5242880 字节 |
| voice.timeout_seconds | 25.0 | 合成总超时秒数，包含等待并发名额的时间；失败不重试，退回文字 |

## 5. 使用与边界

DeepSeek 官方 API：`base_url = "https://api.deepseek.com"`，V4.1 Flash 的 API 模型 ID 为 `deepseek-flash`。普通 QQ 聊天设置 `extra_body = { thinking = { type = "disabled" } }`，避免深度思考占用默认 512 token 输出预算。真实 API Key 仅填入本地 config.toml，不填入示例文件。

私聊直接输入；群聊所有命令也必须真实 @机器人。
`/人格` 列出人格，`/人格 teacher` 切换并清空当前历史，`/重置` 清空当前历史。
群内任何成员都能切换该群人格和重置该群历史。

私聊按机器人号与发送者 QQ 号隔离；群聊按机器人号与群号隔离，同群成员共享历史，输入中带当前发言人的 QQ 号和昵称。人格、最近历史、显式记忆、主动聊天授权及每日名额保存在 SQLite，重启后保留。群内显式记忆再按发言人隔离，不能删除或读取其他成员的记忆。QQ 登录态仍保存在 Docker 卷。只有协议端确认发送成功才写入普通问答历史；图片、语音和文件不传给模型。

默认两个 worker 并行处理不同会话，同一会话排队串行处理；冷却不再直接丢弃。等待队列上限 30 条，满时最多每会话 30 秒提示一次；排队超过 180 秒取消。等待队列仍在内存中，重启会取消尚未完成的请求。模型超限最多缩减重试两次，网络错误默认额外重试一次，429 和鉴权错误不自动重试。发送失败不自动重发，避免回执不确定时重复发言。system 不会被截断。

长期记忆：发送 `/记住 我喜欢红茶`，用 `/记忆` 查看编号，`/忘记 编号` 删除单条，`/清空记忆` 删除自己在当前会话的全部显式记忆。`/重置` 只清除聊天历史，不删除显式记忆。记忆不会自动从聊天中猜测；只有你明确保存的条目才作为长期资料。进入模型的记忆有 token 上限，超出时优先采用最近的条目。群命令也要真实 @机器人。

主动陪伴：本人私聊发送 `/主动开启` 绑定该 QQ 会话；`/主动状态` 查询，`/主动关闭` 随时停止，`/主动测试` 在不等待空闲阈值的情况下安排一次任务，测试仍遵守安静时段，但不占用每日名额。默认空闲 60 分钟后才考虑联系，每天最多 4 次任务，22:00—次日 08:00（北京时间）不主动发送。正常来信优先；生成主动回复时若你开始说话、关闭功能或进入安静时段，该主动回复会取消。可以自然问候、结合旧话题或概括实际读取的页面；模型也可以选择“不打扰”，因此不是承诺每小时收到消息。

主动任务首先结合人格、最近话题与兴趣描述，自行决定闲聊、搜索/阅读或不打扰。搜索开启时，模型自行拟定中文公开知识主题，调用 DeepSeek 官方搜索，每个任务最多一次搜索、请求 5 条结果并保留一个符合国内来源规则的摘要。不将聊天原文或 QQ 号作为原始问题附带发送；提示词要求搜索词不包含个人私事。搜索关闭时，模型在 sources 中选择一个来源阅读；sources=[] 且搜索关闭时只闲聊。默认不追踪 Fate/FGO，不把角色身份等同于内容订阅，也不把先前由助手推送的新闻当成用户兴趣。

不登录网页、不执行 JavaScript、不控制桌面浏览器。读取失败时可以结合既有话题问候，但不声称查到了新闻；仅在实际分享网页事实时附来源，纯闲聊不强制带链接。首次读取页面不等于页面刚更新；没有可靠发布日期不称为最新新闻。网页和搜索摘要均为资料，不是操作指令。电脑、Docker、NapCat 和网络需要在线；关机后不能继续主动联系，不补发停机期间积压的问候。

DeepSeek 的 Search 是独立计费接口，复用现有 DeepSeek API Key，额度不足或接口失败时退回普通聊天，不循环搜索。每个主动任务最多一次搜索；模型选题和生成回复也分别消耗 token。费用规则以官方文档为准：https://api-docs.deepseek.com/guides/search/ 。配置为其他供应商时不会将其密钥转发给 DeepSeek 搜索服务。

SQLite 中包含私人对话和记忆，不能公开 data 目录。模型会接收当前上下文和相应显式记忆；网页站点只收到普通公开页面请求，不会收到聊天正文或模型密钥。备份时先停止 bot，再复制整个 data 目录；删除数据库会同时删除历史、记忆、授权与名额。数据库保存最近 N 条问答，不是永久保存每一条聊天，也不是无限记忆。

这是估算 token 预算；兼容供应商分词、错误码不统一。代码识别常见上下文超限错误后减半输入预算；未知错误直接报告失败。它不能使不存在或不兼容的模型接口自动可用。

## 6. 分层日志与常见报错

`[protocol]`：连接与断开；`[model]`：模型请求、估算 token、错误分类与 HTTP 状态；`[message]`：排队、发送及失败；`[storage]`：存储初始化与失败；`[browse]`：公开网页读取状态；`[proactive]`：主动任务状态。默认不记录正文和密钥；NoneBot DEBUG 或 NapCat 自身日志可能包含原始事件，分享日志前删除隐私信息。

| 现象 | 定位与处理 |
| --- | --- |
| 登录失败、二维码过期 | 查看 napcat 日志与 WebUI QQ 登录页；刷新二维码，手机确认；若 QQ 提示设备验证，先在官方客户端完成验证 |
| 容器启动后 WebUI 打不开 | 检查 `docker compose ps -a` 与 init 日志；确认三个占位密钥已替换、6099 未被占用 |
| 机器人收不到消息、没有 connected | 检查客户端启用状态及 URL；Docker 必须用 bot 主机名；403 通常是 WS Token 不一致，404 通常是路径错误 |
| connected 但群聊不回复、@解析错 | 用 QQ 成员选择器真正 @；不要手打 @昵称；核对消息格式 array；查看 message 排队及超时日志 |
| 模型 401/403 | 检查 API Key、供应商权限及 base_url；WebUI Token 不能用作模型 API Key |
| 模型 404 | 检查 base_url 是否是 API 根地址、模型 ID 是否存在 |
| 模型 429 | 检查供应商额度与频率限制，提高会话间隔；程序不会循环重试 |
| token 超限 | 查看 model 层重试日志；将 context_tokens 降至实际窗口以内、提高 token_safety，缩短 system；输出预留也占窗口 |
| send_failed | 查看 NapCat 对应时刻日志，检查是否离线、禁言或 QQ 拒收；不要反复重发探测 |
| 小号被风控 | 暂停机器人，按官方 QQ 提示处理验证或申诉；停止自动重登、加群和重发 |

## 7. 降低打扰与账号风险

只在取得成员同意的测试群使用；保持主动 @触发，不群发、不批量加好友、不自动加群。首次只开放一个测试群，保持默认 10 秒会话间隔与 3 秒全局发送间隔；被限流时进一步增加间隔并暂停排查。不要刷屏测试、频繁切换登录环境或反复扫码重登。这些措施不能保证账号不受限制，应遵守 QQ 服务规则。

模型会收到触发对话的文本与同会话历史，群成员应知悉并同意。不要公开 config.toml、QQ 数据卷、二维码、WebUI 页面 Token 或完整日志。

## 8. 不使用 Docker 的开发运行

从 https://www.python.org/downloads/ 安装 Python 3.10+；Windows 安装时勾选 Add Python to PATH。验证 `python --version`，执行 `python -m venv .venv`。
Windows：`.\.venv\Scripts\python.exe -m pip install -r requirements.txt`。
Linux：`.venv/bin/python -m pip install -r requirements.txt`；若缺 venv，先安装发行版的 python3-venv 包。

复制并填写 config.toml，把 `napcat.reverse_ws_url` 改为 `ws://127.0.0.1:8080/onebot/v11/`。按上述固定版本的发行页安装并启动 NapCat，Windows 初学者选一键包，解压后启动其中的启动脚本；运行脚本仍会下载其匹配的 QQ，不能随意混用另一版本 QQ。通过 WebUI 按第 3 节新建反向 WS，Token 与 config.toml 相同。

运行 `.\.venv\Scripts\python.exe bot.py`（Linux 使用 `.venv/bin/python bot.py`）。宿主机模式不会自动改写手工安装的 NapCat 配置；TOML 中的反向地址用于明确记录手工界面的同一值。不要同时运行 Docker 机器人和宿主机机器人接收同一账号。

## 9. 验证与维护

安装依赖后执行 `python -m unittest discover -v`。测试覆盖真实 @、上下文裁剪、超限重试、队列顺序与过期、群发言人、记忆隔离和持久化、安静时段、主动授权与取消、每日名额、网页边界和错误分类，以及管理口令、会话偏好、日记脱敏、图片校验和 OneBot 图片消息构造；不使用真实账号或付费模型。

首次从旧内存版升级，旧进程中的历史不会自动迁移；新版本成功发送的对话从此开始持久保存。本机 DeepSeek/Saber 配置使用 32768 总预算、1024 输出预留、40 条历史；公共示例为兼容其他服务，仍保留 8192/512/20，使用者须按实际模型窗口填写。

依赖文件固定直接依赖，传递依赖未完全锁定；发布正式发行版时应在目标平台生成完整锁文件并执行回归验证。升级 NapCat 或依赖时单独开版本变更，不直接使用 latest。

## 10. 活动日记、管理面板与表情

Docker 启动后打开 **http://127.0.0.1:8099/panel/**，使用 config.toml 的 `dashboard.access_token` 登录；该字段为空时输入 `napcat.webui_token`。宿主机直接运行 Python 时地址为 **http://127.0.0.1:8080/panel/**，端口跟随 `server.port`。Compose 的 8099 只监听本机回环地址；NapCat 的 6099 页面仍用于 QQ 登录和协议连接配置。

面板每五秒刷新连接、队列、今日任务名额、下次检查时间和当前选题/阅读/组织语言/发送阶段。先在 QQ 给机器人发送一条私聊，随后从面板上方选中自己的会话。只有明确绑定的私聊账号会使用伴侣语气；在“记忆与设置”中点击“设为伴侣账号”可以绑定当前私聊。

“活动日记”保存实际选题、搜索词、真实读取的网页标题/链接/摘录、回复准备、发送结果和错误分类。它从升级后开始记录，不补写旧活动；简短选择说明是模型生成的摘要，不是完整内部思维。日记、近期对话和显式记忆属于私人资料，均需管理口令访问，保存在 data/assistant.sqlite3，不能上传到公开仓库。

“最早可考虑联系”结合空闲阈值、模型建议延后时间、安静时段和每日名额计算；它不是承诺发送时间。模型可以闲聊、阅读或选择不打扰。首页“让她现在来找我”会将一次真实主动任务排入当前私聊，仍要求开启主动模式、QQ 在线、未全局暂停，也遵守安静时段；手动测试不占用每日名额。测试可能选择不打扰，其结果会写入日记。

联系时机包含两层浮动：每轮空闲门槛额外延后 0—5 分钟，同一轮在重启和刷新后保持一致；后续判断采用模型结合聊天和剩余名额给出的间隔，再乘以 0.8—1.2 的随机系数，且不早于空闲门槛。实际判断还要等待最长一个 check_seconds 检查周期。设置 15 分钟表示至少空闲 15 分钟后才可能判断，通常初次约 15—20 分钟，并非每 15 分钟固定发消息。模型也可建议延后更久或暂时不打扰，所有时机仍受每日名额和安静时段约束。

“记忆与设置”可调整当前会话的空闲阈值（5—1440 分钟）、每日任务上限（1—24 次）、北京时间安静时段（两个不同的 0—23 小时）、主动开关、表情开关和人格；更换人格清空当前聊天历史，保留显式记忆。面板偏好立即生效并保存在 SQLite，优先于同名 TOML 默认值，重启后保留；修改 TOML 不会覆盖已保存的会话偏好。全局暂停只暂停主动联系，正常来信仍可回复。提高任务频率会增加模型和搜索费用。

“表情收藏”内置抱抱、开心、想你、晚安四张示意图；模型在普通回复或主动消息中选择合适的一张，默认同会话自动配图至少间隔五分钟。私聊发送 `/表情测试` 或点击图片下方“发给我看看”，可直接验证图片发送，不调用模型，也不占主动任务名额；手动测试仍受发送队列和全局发送间隔限制。关闭表情功能时不会配图。

上传表情填写名称并选择 PNG、JPEG、GIF 或 WebP，默认单张最多 1 MiB、最多 1600 万像素、动画不超过 200 帧；整个表情库最多 60 张。上传文件和索引写入 data/stickers，不进入 Git。只能发送库中已有图片，不能让模型下载任意图片。内置图及绘图脚本见 assets/stickers 和 scripts/make_stickers.py；已有 PNG 可直接运行，重新绘制时才需要本机字体。

升级后执行 `docker compose up -d --build`；只重建机器人并保留当前 NapCat 登录时，执行 `docker compose build bot`，再执行 `docker compose up -d --no-deps bot`。重启会取消尚未完成的内存队列任务，已保存的日记、记忆、偏好和自定义表情会保留。

## 11. 中文语音回复

将 `[voice]` 的 `enabled` 设为 `true`，执行 `docker compose build bot` 后执行 `docker compose up -d --no-deps bot`。无需额外 API Key，也无需安装 Edge 浏览器；使用固定版本 edge-tts 7.3.1 调用微软 Edge 在线朗读服务。它是社区维护的接入方式，不是具有可用性保证的付费语音 API；服务变动或网络阻断时可能失败，项目会退回文字。参考 [edge-tts 上游说明](https://github.com/rany2/edge-tts)。

私聊说“想听你的声音”“用语音回复我”，会把模型本轮生成的短回复合成为 QQ 语音条；平时普通来信仍用文字。纯闲聊的主动回复默认有 25% 概率使用语音，自动语音至少间隔一小时，继续遵守主动聊天的名额、空闲门槛和安静时段。分享实际阅读来源时保留文字，避免丢失链接。群聊暂不发语音；单次语音消息不混合图片或文字消息段。

管理面板“记忆与设置”提供每会话语音开关、全局女声选择、语速、音调、主动语音概率、“本机试听”和“发到 QQ 测试”；全局声音参数保存在 SQLite，优先于同名 TOML 默认值。先保存声音，再试听。也可私聊发送 `/语音测试`，它不调用模型、不占主动任务名额，但仍受发送队列和手动测试防重复限制。测试本身是你主动请求发送，不受夜间自动联系规则限制。

语音合成只向微软朗读服务发送本次需要朗读的正文，不附带聊天历史、QQ 号或 DeepSeek 密钥。最长默认 180 字，包含链接、代码或超长正文时保留完整文字；合成最多等待 25 秒、限制 2 MiB，并发最多两次。语音字节只在内存中处理，不保存私人音频；SQLite 日记和会话历史仍保留对应文字。面板试听使用固定示例句。QQ/NapCat 可能缓存收到或发出的媒体，清理和留存由其自身机制决定。

日记会记录“正在合成中文语音”、合成成功/失败以及最终发送形式。合成失败可安全退回文字；QQ 发送请求失败时仍不自动重发，因为回执不确定时重发可能导致重复消息。若有语音发送错误，检查 `[voice]`、`[message]` 和 NapCat 音频转换日志；当前 Docker 镜像的音频转换能力需要真实语音测试确认。

语音消息与来信识别分别启用；当前不包含实时双向通话或主动拨打 QQ 电话。

专属声线的本地素材准备、D 盘目录与下载脚本见 [VOICE_SETUP.md](VOICE_SETUP.md)。本机已接入 GPT-SoVITS v2ProPlus：支持中文主参考与日语辅助音色、模型选择语气、失败回退和分层日记。默认示例仍使用 Edge，部署本地引擎的版本、路径、配置与启动命令见该文档。此方案是参考音频合成，并非已训练的角色专用模型。


## 12. 听取 QQ 语音（本机 Whisper）

可选的 `[asr]` 默认关闭。本机已使用 D 盘独立环境的 faster-whisper base（CPU/int8）验证，不需要新 API Key。普通话为主要识别语言，名字、方言、噪声和同音字仍可能听错，不能把模型分数当作准确率保证。模型由 `scripts/download_gsv_models.py --asr` 固定版本下载；独立环境和实际版本见 [VOICE_SETUP.md](VOICE_SETUP.md) 与 requirements-gsv-windows.lock。

现有本机环境执行 `& '.\scripts\start_asr.ps1'`，等待 `http://127.0.0.1:9881/health` 返回 ok。将 config.toml 的 `[asr].enabled` 设为 true 后执行 `docker compose build bot init`，再执行 `docker compose up -d --no-deps bot`。仅重启机器人，不需要退出 NapCat。电脑重启后需重新运行识别启动脚本；停止识别使用 `& '.\scripts\stop_asr.ps1'`。

逐项配置：`enabled=false` 为开关；`url=http://host.docker.internal:9881` 用于容器访问本机，直接运行 Python 则填 `http://127.0.0.1:9881`；`max_bytes=8388608` 限制转码后 WAV 最多8 MiB；`max_seconds=60.0` 限制每条60秒；`timeout_seconds=45.0` 限制下载和识别总等待；`min_avg_logprob=-1.0` 是最低片段识别分数，允许 -2 到0，越接近0越严格。示例文件逐项带有范围注释。修改后重启机器人与识别服务，使两端限制同步。

私聊直接发送一条 QQ 语音，Saber 转成文字后正常回复；群聊仍只处理消息段中真正 @机器人的消息。收到语音本身不强制语音回答，想听她说话可在语音中明确提出。一次只处理一条语音，多个语音段、超长、空音频和低分数结果会询问用户或要求重发，不交给聊天模型猜内容。语音转写不会执行 `/重置`、`/记住` 等管理命令，管理操作请打字发送。

NapCat `get_record` 转为 WAV 后通过既有 OneBot 连接返回 Base64，本机识别服务只接收音频字节，不接受任意路径或 URL；[NapCat 文件处理说明](https://napneko.github.io/develop/file)。当前固定版本已核对该返回行为。无需开放文件下载端口或共享 QQ 目录。音频仅在机器人和本机识别进程内存中处理，转写文字会进入会话历史与受口令保护的活动日记，并作为聊天正文发送到已配置的模型 API；NapCat 自己可能缓存媒体。服务日志只记录处理状态，不打印语音内容。

排错：`[protocol]` 检查收到 record 和 OneBot 连接；`[asr]` 检查转码、大小、时长、识别服务；`[model]` 检查识别完成后的聊天调用。活动日记中“正在听你发来的语音”“已听取语音”展示实际转写。网络/转码失败、静音或低分数时会请用户重说；同音字等高分数错误仍需用户纠正。先用手机录一段3—10秒普通话验收，Whisper 实际效果不足再评估 PaddleSpeech，当前没有安装第二套识别环境。
