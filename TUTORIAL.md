# 从零到首次 QQ 对话

1. **准备设备**：Windows 11 x64 或 Ubuntu 22.04/24.04 x64，建议 2 核、4 GB 内存、10 GB 空闲磁盘；手机已安装 QQ。截图位置：系统版本与空闲磁盘，隐藏设备标识。
2. **安装 Git 和 Docker**：使用 README 第 1 节官方链接完成安装。Windows 启用 WSL2，重启后打开 Docker Desktop，使用 Linux 容器。截图位置：Docker Engine running 状态。
3. **验证环境**：终端执行 `git --version`、`docker version`、`docker compose version`，任何一个失败都先修复对应安装。截图位置：三个命令的成功输出。
4. **获取项目**：执行 `git clone https://github.com/Artoria2006/saber-companion.git`，再执行 `cd saber-companion`，确认 docker-compose.yml 存在。截图位置：文件目录列表。
5. **创建配置**：PowerShell 执行 `Copy-Item config.example.toml config.toml`；Linux 执行 `cp config.example.toml config.toml`。截图位置：两个文件并存。
6. **生成密钥**：执行 README 的 Docker 随机密钥命令两次，分别填入 WS 和 WebUI 字段。截图位置：编辑器中的字段名；必须遮住密钥内容。
7. **填写模型配置**：在服务商控制台取得 API Key，填写 base_url、api_key、model；默认 OpenAI 地址和 gpt-4o-mini 仅适用于有对应权限与额度的 OpenAI API Key。截图位置：三个字段；Key 完全遮挡。
8. **第一次启动**：执行 `docker compose up -d --build`。等待下载、构建完成，再执行 `docker compose ps -a`，确认 init 为 Exited (0)，bot 与 napcat 为运行中。截图位置：服务列表。
9. **进入 WebUI**：浏览器打开 `http://127.0.0.1:6099/webui/`，输入 WebUI 密钥。截图位置：登录页，遮住 Token 与地址查询参数。
10. **扫码登录**：进入 QQ 登录，选择 QRCode，手机 QQ 扫码确认；二维码过期就刷新。若提示 Token 轮换或强制改密，查看 napcat 日志重新进入并将最终密钥同步回 TOML。截图位置：已登录状态；不发布二维码、QQ 号或登录 Token。
11. **核对反向 WS**：进入网络配置，找到 qq-ai WebSocket 客户端，确认启用、URL 为 `ws://bot:8080/onebot/v11/`、消息格式 array、Token 与 TOML 相同；不要重复新建。截图位置：连接编辑面板，Token 全遮挡。
12. **确认连接**：执行 `docker compose logs -f bot napcat`，找到 `[protocol] connected`。截图位置：连接成功行，遮住账号。
13. **私聊验收**：用另一个账号给机器人发“你好”，等待回复。截图位置：一问一答，隐去头像和账号。
14. **群聊验收**：先在群里发普通消息，确认不回复；再通过 QQ 成员选择器真正 @机器人并提问，确认回复。每次有效测试间隔至少 10 秒。截图位置：两种触发结果。
15. **人格与历史验收**：私聊发送 `/人格 teacher`，等 10 秒后提问；发送 `/重置` 清空历史。群聊命令也要 @机器人。同群共享历史与人格，不同群、不同私聊隔离。截图位置：切换和重置回执。
16. **观察排队**：在一次模型调用尚未结束时再发消息，检查 `[message] queued`；同会话按顺序处理，超过队列上限或等待时限时会提示。截图位置：排队日志。
17. **保存与停止**：执行 `docker compose down`；下次 `docker compose up -d --build`。登录卷和 data 目录保留，最近历史、人格及显式记忆会恢复；尚未处理的内存队列不会恢复。修改 TOML 后也执行这组命令。截图位置：停止后的服务状态。
18. **排错**：按 README 第 6 节先定位 protocol、model 或 message 层，再核对对应字段；提交问题时只提供版本号、错误类型、状态码及脱敏日志。截图位置：脱敏后的错误行。

19. **记忆验收**：私聊发送 `/记住 我喜欢红茶`，用 `/记忆` 查看，再重启 bot 确认条目保留；用 `/忘记 编号` 删除。截图位置：重启前后的记忆列表，隐藏个人资料。
20. **主动陪伴验收**：本人私聊发送 `/主动开启`，查看 `/主动状态`；用 `/主动测试` 安排一次测试。模型可能决定不打扰，查看 proactive 日志确认；`/主动关闭` 可停止。安静时段和每日名额对测试也有效。截图位置：开启回执、来源链接、关闭回执。

最终验收清单：私聊能答；群聊真 @才答；会话隔离与发送者标记有效；人格可切换；忙时排队；超长文本裁剪；历史和显式记忆跨重启保留；主动模式本人授权、可关闭、守安静时段和每日限额。真实登录、模型调用、群权限和账号状态由使用者在自己的环境验收。
