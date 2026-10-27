"""只读取配置中的公开网页，不登录、不执行网页脚本、不跟随外链。"""

import asyncio
import hashlib
import ipaddress
import socket
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit, urljoin
import httpx


def domestic_result(url, domains):
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or parsed.username or parsed.password or not host:
            return False
        if host.endswith(".cn"):
            return True
        return any(host == domain or host.endswith("." + domain) for domain in domains)
    except ValueError:
        return False


async def search_domestic(query, model, config):
    # 只向 DeepSeek 官方发送现有 DeepSeek 密钥，不能把其他供应商的密钥转发过去。
    base = urlsplit(model["base_url"])
    if base.scheme != "https" or base.hostname != "api.deepseek.com":
        raise ValueError("国内搜索目前需要 DeepSeek 官方 API 配置")
    query = re.sub(r"\d{5,}", "", query).strip()[:100]
    if not query:
        raise ValueError("搜索词不能为空")
    async with httpx.AsyncClient(timeout=config["fetch_timeout_seconds"], trust_env=False) as client:
        response = await client.post("https://api.deepseek.com/v1/tools/search",
            headers={"Authorization": "Bearer " + model["api_key"]},
            json={"query": query + " lang:zh", "count": 5, "need_content": False})
        response.raise_for_status()
        for item in response.json().get("results", []):
            url = item.get("url", "")
            if not isinstance(url, str) or not domestic_result(url, config["search_domains"]):
                continue
            text = item.get("summary") or item.get("snippet") or ""
            if not isinstance(text, str) or not text.strip():
                continue
            text = text[:config["max_page_chars"]]
            return {"url": url, "text": text, "title": str(item.get("title", ""))[:200],
                    "published_at": item.get("date"), "kind": "search_excerpt",
                    "digest": hashlib.sha256(text.encode()).hexdigest()}
    raise ValueError("没有找到可用的国内公开内容")


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "template"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "template"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(data.strip())


async def public_url(url, allowed_hosts):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in allowed_hosts
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError("仅允许配置中主机的 HTTPS 页面")
    answers = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(
        parsed.hostname, 443, type=socket.SOCK_STREAM), timeout=8)
    if not answers or any(not ipaddress.ip_address(row[4][0]).is_global for row in answers):
        raise ValueError("网页地址不能解析到本地、内网或保留地址")


async def read_page(url, config):
    allowed_hosts = {urlsplit(source).hostname for source in config["sources"]}
    original = url
    async with httpx.AsyncClient(timeout=config["fetch_timeout_seconds"],
                                 follow_redirects=False, trust_env=False) as client:
        for _ in range(4):
            await public_url(url, allowed_hosts)
            async with client.stream("GET", url, headers={
                "User-Agent": "QQ-AI-Starter/0.2 (public-page-reader)",
                "Accept": "text/html,text/plain,application/xml,text/xml",
            }) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers.get("location", ""))
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                if not any(x in content_type for x in ("text/", "xml", "xhtml")):
                    raise ValueError("不读取非文本网页")
                payload = bytearray()
                async for chunk in response.aiter_bytes():
                    payload.extend(chunk)
                    if len(payload) > config["max_page_bytes"]:
                        raise ValueError("网页超过允许的下载大小")
                encoding = response.encoding or "utf-8"
                parser = TextParser()
                parser.feed(bytes(payload).decode(encoding, errors="replace"))
                text = " ".join(parser.parts)[:config["max_page_chars"]]
                if not text:
                    raise ValueError("网页没有可读取的公开文字")
                return {"url": original, "text": text,
                        "digest": hashlib.sha256(text.encode()).hexdigest()}
    raise ValueError("网页重定向次数超限")
