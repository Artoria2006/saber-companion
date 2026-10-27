"""读取唯一的 config.toml，并在启动前检查全部配置。"""

import math
import json
import sys
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


CONFIG_PATH = Path(__file__).resolve().with_name("config.toml")

# 显式列出字段，拼错字段名时立即报错，避免配置被静默忽略。
FIELDS = {
    "server": {"host", "port", "access_token", "log_level"},
    "model": {
        "base_url", "api_key", "model", "context_tokens", "max_output_tokens",
        "encoding", "token_safety", "timeout_seconds", "extra_body", "transient_retries",
    },
    "chat": {
        "history_messages", "max_sessions", "default_persona", "system_prompt",
        "max_input_chars", "max_reply_chars", "session_interval_seconds",
        "send_interval_seconds", "queue_size", "queue_ttl_seconds", "workers", "companion_qq",
    },
    "napcat": {"webui_token", "reverse_ws_url"},
    "storage": {"path", "max_memories", "max_memory_chars"},
    "proactive": {"enabled", "idle_minutes", "check_seconds", "max_daily_attempts",
                  "quiet_start_hour", "quiet_end_hour", "sources", "fetch_timeout_seconds",
                  "max_page_bytes", "max_page_chars", "search_enabled", "search_domains", "interests"},
    "dashboard": {"enabled", "access_token", "activity_limit"},
    "stickers": {"enabled", "builtin_dir", "upload_dir", "max_bytes", "min_interval_seconds"},
}

DEFAULTS = {
    "dashboard": {"enabled": True, "access_token": "", "activity_limit": 1000},
    "stickers": {"enabled": True, "builtin_dir": "assets/stickers", "upload_dir": "data/stickers",
                 "max_bytes": 1048576, "min_interval_seconds": 300.0},
    "storage": {"path": "data/assistant.sqlite3", "max_memories": 20, "max_memory_chars": 300},
    "proactive": {"enabled": True, "idle_minutes": 60, "check_seconds": 60,
                  "max_daily_attempts": 4, "quiet_start_hour": 22, "quiet_end_hour": 8,
                  "sources": ["https://sspai.com/feed", "https://www.gcores.com/rss", "https://www.ithome.com/rss/"],
                  "search_enabled": False,
                  "search_domains": ["sspai.com", "gcores.com", "ithome.com", "zhihu.com", "guokr.com", "douban.com", "36kr.com", "huxiu.com", "thepaper.cn", "people.com.cn", "xinhuanet.com", "163.com", "sohu.com", "ifeng.com", "bilibili.com", "baidu.com", "qq.com"],
                  "interests": "国内生活、饮食、自然、科技、阅读、文化与有趣的小知识。不要因为 Saber 身份默认追踪 Fate、FGO 或周边商品；除非用户自己提起。",
                  "fetch_timeout_seconds": 12.0, "max_page_bytes": 262144, "max_page_chars": 3500},
}


class ConfigError(ValueError):
    """配置不存在、无法解析或未通过校验。"""


def _fail(field: str, message: str) -> None:
    # 错误中只输出字段名，不回显密钥内容。
    raise ConfigError(f"配置错误：{field}：{message}")


def _text(value: Any, field: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        _fail(field, "必须是字符串，请使用英文双引号包围")
    if not allow_empty and not value.strip():
        _fail(field, "不能为空")
    return value


def _integer(value: Any, field: str, minimum: int, maximum: int | None = None) -> None:
    # bool 是 int 的子类，因此不能用 isinstance(value, int) 判断。
    if type(value) is not int:
        _fail(field, "必须是整数，不能使用小数、布尔值或带引号的数字")
    if value < minimum or (maximum is not None and value > maximum):
        limit = f"{minimum} 到 {maximum}" if maximum is not None else f"不小于 {minimum}"
        _fail(field, f"取值必须为{limit}")


def _number(value: Any, field: str, minimum: float) -> None:
    if type(value) not in (int, float):
        _fail(field, "必须是数字，不能使用布尔值或带引号的数字")
    try:
        valid = math.isfinite(value) and value >= minimum
    except OverflowError:
        valid = False
    if not valid:
        _fail(field, f"必须是有限数字，且不小于 {minimum}")


def _secret(value: Any, field: str, minimum: int) -> None:
    value = _text(value, field)
    markers = ("CHANGE_ME", "YOUR_API_KEY", "YOUR_TOKEN", "REPLACE_ME")
    if any(marker in value.upper() for marker in markers):
        _fail(field, "仍是示例占位符，必须替换后才能启动")
    if value != value.strip() or any(ch.isspace() for ch in value):
        _fail(field, "不能包含空格、换行或制表符")
    if len(value) < minimum:
        _fail(field, f"长度不能少于 {minimum} 个字符")


def _url(value: Any, field: str, schemes: tuple[str, ...]) -> None:
    value = _text(value, field)
    if any(ch.isspace() for ch in value):
        _fail(field, "URL 不能包含空白字符")
    try:
        parsed = urlsplit(value)
        port = parsed.port
        valid = parsed.scheme in schemes and bool(parsed.hostname)
        if port is not None:
            valid = valid and 1 <= port <= 65535
        valid = valid and parsed.username is None and parsed.password is None
        valid = valid and not parsed.query and not parsed.fragment
    except ValueError:
        valid = False
    if not valid:
        _fail(field, f"必须是有效的 {' 或 '.join(schemes)} URL，不能带用户名、密码、查询参数或片段")


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    """校验已解析的字典；成功时返回原字典，保持与机器人代码兼容。"""
    for section, defaults in DEFAULTS.items():
        values = config.setdefault(section, {})
        if not isinstance(values, dict):
            _fail(section, "必须是配置段")
        for key, value in defaults.items():
            values.setdefault(key, value)
    expected = set(FIELDS) | {"personas"}
    missing = expected - config.keys()
    unknown = config.keys() - expected
    if missing:
        _fail("根节点", "缺少配置段：" + "、".join(sorted(missing)))
    if unknown:
        _fail("根节点", "存在未知配置段：" + "、".join(sorted(unknown)))

    for section, fields in FIELDS.items():
        values = config[section]
        if not isinstance(values, dict):
            _fail(section, f"必须使用 [{section}] 配置段")
        if section == "model":
            # 默认不附加供应商专属参数，兼容原有配置文件。
            values.setdefault("extra_body", {})
            values.setdefault("transient_retries", 1)
        if section == "chat":
            for key, value in {"queue_size": 30, "queue_ttl_seconds": 180.0, "workers": 2, "companion_qq": 0}.items():
                values.setdefault(key, value)
        missing = fields - values.keys()
        unknown = values.keys() - fields
        if missing:
            _fail(section, "缺少字段：" + "、".join(sorted(missing)))
        if unknown:
            _fail(section, "存在未知字段：" + "、".join(sorted(unknown)))

    s, m, h, n = (config[k] for k in ("server", "model", "chat", "napcat"))

    _text(s["host"], "server.host")
    try:
        ip_address(s["host"])
    except ValueError:
        _fail("server.host", "必须是有效的 IPv4 或 IPv6 监听地址，例如 0.0.0.0")
    _integer(s["port"], "server.port", 1, 65535)
    _secret(s["access_token"], "server.access_token", 24)
    if s["log_level"] not in ("DEBUG", "INFO", "WARNING", "ERROR"):
        _fail("server.log_level", "只能填写 DEBUG、INFO、WARNING 或 ERROR")

    _url(m["base_url"], "model.base_url", ("http", "https"))
    _secret(m["api_key"], "model.api_key", 1)
    _text(m["model"], "model.model")
    _integer(m["context_tokens"], "model.context_tokens", 1)
    _integer(m["max_output_tokens"], "model.max_output_tokens", 1)
    if m["context_tokens"] - m["max_output_tokens"] < 129:
        _fail("model.context_tokens", "减去 max_output_tokens 后必须至少剩余 129 个输入 token")
    if m["encoding"] not in ("cl100k_base", "o200k_base"):
        _fail("model.encoding", "只能填写 cl100k_base 或 o200k_base")
    _number(m["token_safety"], "model.token_safety", 1.0)
    _number(m["timeout_seconds"], "model.timeout_seconds", 0.1)
    _integer(m["transient_retries"], "model.transient_retries", 0, 2)
    if not isinstance(m["extra_body"], dict):
        _fail("model.extra_body", "必须是 TOML 内联表，例如 {}")
    reserved = {"model", "messages", "max_tokens", "stream"}
    if reserved.intersection(m["extra_body"]):
        _fail("model.extra_body", "不能覆盖 model、messages、max_tokens 或 stream")
    try:
        json.dumps(m["extra_body"], allow_nan=False)
    except (TypeError, ValueError):
        _fail("model.extra_body", "必须是可转换为 JSON 的有限数值、文本、布尔值、数组或表")

    for key in ("history_messages", "max_sessions", "max_input_chars", "max_reply_chars"):
        _integer(h[key], f"chat.{key}", 1)
    if h["history_messages"] % 2:
        _fail("chat.history_messages", "必须是正偶数，以保存完整的 user/assistant 问答")
    _text(h["system_prompt"], "chat.system_prompt", allow_empty=True)
    _text(h["default_persona"], "chat.default_persona")
    for key in ("session_interval_seconds", "send_interval_seconds"):
        _number(h[key], f"chat.{key}", 0.0)
    _integer(h["queue_size"], "chat.queue_size", 1, 1000)
    _integer(h["workers"], "chat.workers", 1, 8)
    _integer(h["companion_qq"], "chat.companion_qq", 0, 999999999999)
    _number(h["queue_ttl_seconds"], "chat.queue_ttl_seconds", 1.0)

    personas = config["personas"]
    if not isinstance(personas, dict) or not personas:
        _fail("personas", "必须是非空配置段，至少定义一个人格")
    for name, prompt in personas.items():
        if not name or any(ch.isspace() for ch in name):
            _fail("personas", "人格名称不能为空，也不能包含空白字符")
        _text(prompt, f"personas.{name}")
    if h["default_persona"] not in personas:
        _fail("chat.default_persona", "必须与 personas 中的一个人格名称完全一致")

    _secret(n["webui_token"], "napcat.webui_token", 24)
    if n["webui_token"] == s["access_token"]:
        _fail("napcat.webui_token", "不能与 server.access_token 相同，请分别生成两个密钥")
    _url(n["reverse_ws_url"], "napcat.reverse_ws_url", ("ws", "wss"))
    storage = config["storage"]
    _text(storage["path"], "storage.path")
    path = Path(storage["path"])
    if path.is_absolute() or ".." in path.parts or len(path.parts) < 2 or path.parts[0] != "data":
        _fail("storage.path", "必须是项目 data 目录内的相对路径，例如 data/assistant.sqlite3")
    _integer(storage["max_memories"], "storage.max_memories", 1, 100)
    _integer(storage["max_memory_chars"], "storage.max_memory_chars", 1, 1000)
    pro = config["proactive"]
    if type(pro["enabled"]) is not bool:
        _fail("proactive.enabled", "必须为 true 或 false")
    if type(pro["search_enabled"]) is not bool:
        _fail("proactive.search_enabled", "必须为 true 或 false")
    _text(pro["interests"], "proactive.interests")
    if not isinstance(pro["search_domains"], list) or len(pro["search_domains"]) > 50:
        _fail("proactive.search_domains", "必须是最多包含 50 个国内站点域名的数组")
    for domain in pro["search_domains"]:
        if not isinstance(domain, str) or not domain or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-." for ch in domain) or "." not in domain:
            _fail("proactive.search_domains", "必须是小写域名，不要填写协议、路径或端口")
    _integer(pro["idle_minutes"], "proactive.idle_minutes", 5, 1440)
    _number(pro["check_seconds"], "proactive.check_seconds", 5.0)
    _integer(pro["max_daily_attempts"], "proactive.max_daily_attempts", 1, 24)
    for key in ("quiet_start_hour", "quiet_end_hour"):
        _integer(pro[key], f"proactive.{key}", 0, 23)
    if pro["quiet_start_hour"] == pro["quiet_end_hour"]:
        _fail("proactive.quiet_end_hour", "不能与 quiet_start_hour 相同")
    if not isinstance(pro["sources"], list) or len(pro["sources"]) > 20:
        _fail("proactive.sources", "必须是最多包含 20 个 HTTPS 地址的数组；空数组表示不直接读取固定来源")
    for url in pro["sources"]:
        _url(url, "proactive.sources", ("https",))
        if urlsplit(url).port not in (None, 443):
            _fail("proactive.sources", "仅支持 HTTPS 默认 443 端口")
    _number(pro["fetch_timeout_seconds"], "proactive.fetch_timeout_seconds", 1.0)
    _integer(pro["max_page_bytes"], "proactive.max_page_bytes", 1024, 1048576)
    _integer(pro["max_page_chars"], "proactive.max_page_chars", 100, 10000)
    panel = config["dashboard"]
    if type(panel["enabled"]) is not bool:
        _fail("dashboard.enabled", "必须为 true 或 false")
    _text(panel["access_token"], "dashboard.access_token", allow_empty=True)
    if panel["access_token"]:
        _secret(panel["access_token"], "dashboard.access_token", 24)
    _integer(panel["activity_limit"], "dashboard.activity_limit", 100, 10000)
    stickers = config["stickers"]
    if type(stickers["enabled"]) is not bool:
        _fail("stickers.enabled", "必须为 true 或 false")
    for key, root in (("builtin_dir", "assets"), ("upload_dir", "data")):
        _text(stickers[key], f"stickers.{key}")
        path = Path(stickers[key])
        if path.is_absolute() or ".." in path.parts or len(path.parts) < 2 or path.parts[0] != root:
            _fail(f"stickers.{key}", f"必须位于项目 {root} 目录内")
    _integer(stickers["max_bytes"], "stickers.max_bytes", 1024, 5242880)
    _number(stickers["min_interval_seconds"], "stickers.min_interval_seconds", 0.0)
    return config


def load_config() -> dict[str, Any]:
    """固定读取 settings.py 同目录的 config.toml，不读取 .env。"""
    try:
        with CONFIG_PATH.open("rb") as file:
            config = tomllib.load(file)
    except FileNotFoundError as exc:
        raise ConfigError(
            f"配置文件不存在：{CONFIG_PATH}。请先将 config.example.toml 复制为 config.toml。"
        ) from exc
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        # 不回显 TOML 原文，防止语法报错时泄露密钥。
        raise ConfigError(
            "config.toml 语法或编码错误：请使用 UTF-8，检查英文引号、配置段名称及数值格式。"
        ) from None
    except OSError as exc:
        raise ConfigError(f"无法读取配置文件：{CONFIG_PATH}，请检查文件权限。") from exc
    return validate_config(config)


if __name__ == "__main__":
    try:
        load_config()
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    print("配置校验通过。")
