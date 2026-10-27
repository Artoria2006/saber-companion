# 内置测试表情

`hug.png`（抱抱）、`happy.png`（好开心）、`miss.png`（想你啦）、`goodnight.png`（晚安）是随项目提供的简单金发骑士示意图，由 `scripts/make_stickers.py` 绘制，按项目 AGPL-3.0 协议提供，不是官方角色立绘。

运行机器人直接使用已有 PNG，无须重新绘图。重新绘图需安装 requirements.txt 中的 Pillow；脚本优先使用系统微软雅黑粗体，Linux 缺少该字体时使用 DejaVu Sans。字体文件不随项目分发。

`index.json` 的每一项包含 `id`（英文小写、数字、下划线或短横线，最多 40 字符）、`label`（向模型说明的表情名称）和 `file`（同目录图片文件名）。自定义图片通过面板上传，保存在 data/stickers；不要把私人图片或无权分发的素材提交到仓库。
