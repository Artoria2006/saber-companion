# QQ 电话桥来源与许可

`bridge/` 来源于 https://github.com/ClaudiaGardner/maibot-qq-voice-call ，基准提交为 `22f30c021cd3170f75af9dff66cc959a07ebda4b`，上游许可为 GPL-3.0-only，见本目录 LICENSE。保留上游文件及声明；此目录不改变主项目 AGPL-3.0 的许可声明。

`bridge/napcat-plugin/index.mjs` 和 `bridge/tests/bridge.test.mjs` 包含本项目的修改：限制初始化重试，并在自动接听前检查来电身份、启用标记和音频工作进程状态。`patch-napcat.py` 与 `saber-call-setup.sh` 是本项目为实验镜像添加的配置代码。使用前请分别确认 NapCat、QQ、上游桥及相关素材的许可和使用条件。此桥是非官方实验，不保证 QQ 版本升级后仍可用。
