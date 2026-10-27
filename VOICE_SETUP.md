# Saber 专属声线：本地素材准备

当前 QQ 语音使用 edge-tts。GPT-SoVITS 官方源码已在本机克隆到 `D:\saber-voice\GPT-SoVITS`；尚未取得参考视频、确认音频或完成专属声线合成，因此没有切换机器人声线。

源码来源：https://github.com/RVC-Boss/GPT-SoVITS ，本次检查版本为 `b4570b876f5c086819ba84e3215472733c6a7b70`。运行环境、输入素材、基础权重与处理结果位于独立的 `D:\saber-voice`，不提交到本仓库。第三方程序和模型遵循各自许可。

## 1. 下载公开素材

本机已有独立环境与 yt-dlp 2026.10.26。PowerShell 执行：

```powershell
& 'D:\saber qq\scripts\download_voice_sources.ps1'
```

脚本只下载指定的两个公开链接的音轨，保存至 `D:\saber-voice\input`。它不读取浏览器 Cookie、不更改代理、不处理验证码；下载失败会明确退出。

2026-10-27 实测两个页面、公开元数据接口及标准 yt-dlp 命令均返回 HTTP 412，未下载到素材。遇到这种情况需要通过平台允许的方式取得本地文件，或提供已有文件路径。不能把代码已克隆当作模型已完成部署。

GPT-SoVITS 不要求关闭代理。代码与模型下载、视频网站访问分别受网络条件影响；修改全局代理不保证能解决网站风控。本项目脚本不替使用者切换网络设置。

独立环境已验证 torch 2.5.1+cu121、torchaudio 2.5.1+cu121 可调用 RTX 4060 Laptop。PyTorch 从本机已验证环境复制到新目录，未修改旧环境；其他音频准备工具版本记录在 requirements-voice-tools.txt。该环境尚不等于完整 GPT-SoVITS 推理环境，启动前仍需安装其余推理依赖并取得基础权重与参考素材。

## 2. 从本地文件提取音轨

先把本地文件放到 input 目录，将下面命令末尾替换为该文件的真实完整路径：

```powershell
& 'D:\saber-voice\.venv\Scripts\python.exe' 'D:\saber qq\scripts\prepare_voice_audio.py' 'D:\saber-voice\input\sample.mp4' --duration 600
```

这条命令处理从零秒开始的前 600 秒，默认保留原始立体声音轨，并按静音边界生成最多 20 个 3—9 秒候选单声道片段。`--start 60 --duration 120` 表示从一分钟处开始处理两分钟；单次上限 1800 秒。每次写入一个全新 processed 子目录，不覆盖或删除输入文件。

FFmpeg 只能提取音轨，不能保证移除配乐。`--separate` 会调用独立环境中的 Demucs htdemucs 做人声分离，默认关闭。本机已安装 Demucs 4.1.0 并完成 GPU 人声分离与约 3.8 秒候选切片的真实验证；缓存位于 D 盘。其他机器需先安装 requirements-voice-tools.txt 和匹配的 PyTorch。分离输出包含所有人声，不会自动识别哪个人是 Saber，也无法保证完全去除配乐。

## 3. 声线合成前的检查

在 manifest.json 中确认候选片段的说话人、准确转写、语言和情绪。日语参考合成中文需要跨语言推理，效果须实际试听。包含背景人声、角色重叠、喊叫或强烈混响的片段不适合作为日常聊天的唯一参考。

安装基础模型、启动本机推理 API、完成试听与 QQ 语音发送验证后，才能切换机器人。当前运行中的 QQ 助手继续使用已验证的中文女声；视频、音频、权重、下载缓存和登录信息不进入 Git。
