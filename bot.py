import json
import sys
from pathlib import Path
import nonebot
from nonebot.adapters.onebot.v11 import Adapter
from settings import load_config


def prepare(c):
    # 此目录通过 Docker 命名卷共享；每次启动重新生成，TOML 是唯一配置源。
    root = Path("/napcat-config")
    root.mkdir(parents=True, exist_ok=True)
    connection = {
        "network": {
            "httpServers": [], "httpClients": [], "websocketServers": [],
            "websocketClients": [{
                "name": "qq-ai", "enable": True,
                "url": c["napcat"]["reverse_ws_url"],
                "messagePostFormat": "array", "reportSelfMessage": False,
                "reconnectInterval": 5000, "heartInterval": 30000,
                "token": c["server"]["access_token"], "debug": False,
            }],
        },
        "musicSignUrl": "", "enableLocalFile2Url": False, "parseMultMsg": False,
    }
    # 已登录账号可能有覆盖默认值的专属文件，必须同步更新。
    targets = [root / "onebot11.json", *root.glob("onebot11_*.json")]
    for target in targets:
        target.write_text(json.dumps(connection, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "webui.json").write_text(json.dumps({
        "host": "0.0.0.0", "port": 6099,
        "token": c["napcat"]["webui_token"], "loginRate": 3,
    }), encoding="utf-8")
    print("[protocol] NapCat 配置已从 config.toml 生成", flush=True)


if __name__ == "__main__":
    config = load_config()
    if "--prepare" in sys.argv:
        prepare(config)
    else:
        s = config["server"]
        nonebot.init(_env_file=None, driver="~fastapi", host=s["host"], port=s["port"],
                     log_level=s["log_level"], onebot_access_token=s["access_token"],
                     api_timeout=15.0)
        nonebot.get_driver().register_adapter(Adapter)
        if nonebot.load_plugin("chat") is None:
            raise RuntimeError("聊天插件加载失败，请查看启动日志")
        nonebot.run()
