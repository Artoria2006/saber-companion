# 参与开发

1. 克隆仓库，先阅读 README.md、PRODUCT_DESIGN.md 与 TECHNICAL_DESIGN.md。
2. 从最新主分支创建功能分支，使用 Python 3.10—3.12；复制示例配置，真实配置不要提交。
3. 安装 `python -m pip install -r requirements.txt -r requirements-qq-call.txt`；运行 `python -m unittest discover -v`。电话桥改动还需 Node.js 22，执行 `node --test third_party/qq-call/bridge/tests/bridge.test.mjs`。
4. 静态检查使用 `python -m pip install ruff==0.15.22`，再运行 `ruff check --select F .`。现有风格问题逐步整理，功能变更应补充有意义的测试。
5. 提交前检查差异和测试结果，更新 CHANGELOG；提交 PR 时写清问题、方案、测试及未覆盖范围。

不要提交 QQ 账号信息、二维码、配置密钥、对话数据库、个人音频、模型权重或下载缓存。第三方代码及素材需保留来源和许可证。
