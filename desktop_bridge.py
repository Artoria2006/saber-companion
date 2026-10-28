"""电脑工具边界：只打开被用户目标明确点名的网页或指定 Windows 软件。"""
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
import httpx


class DesktopBridge:
    def __init__(self, root, domains, enabled, automatic_enabled=lambda: False, automatic_guard=lambda task: False):
        self.root = Path(root)
        self.domains = domains
        self.enabled = enabled
        self.automatic_enabled = automatic_enabled
        self.automatic_guard = automatic_guard
        self.url = 'http://127.0.0.1:9882' if os.name == 'nt' else 'http://host.docker.internal:9882'

    def allowed(self, action, task):
        if not self.enabled():
            raise ValueError('电脑工具未启用')
        automatic=task.get('automatic',False)
        if automatic:
            if not self.automatic_enabled() or not self.automatic_guard(task):
                raise ValueError('自主桌面操作已暂停或空闲条件发生变化')
            if any(x.get('status')=='done' and x.get('tool') in ('open_browser','open_notepad','open_calculator') for x in task.get('steps',[])):
                raise ValueError('每次自主任务最多启动一个桌面窗口')
            if not task.get('file') or not any(x.get('status')=='done' and x.get('tool') in ('read_page','search') for x in task.get('steps',[])):
                raise ValueError('自主桌面任务须先完成公开阅读并保存笔记')
        goal = task['goal']
        name = action.get('tool')
        if name == 'open_browser':
            url = action.get('url')
            if not isinstance(url,str) or len(url)>1200:
                raise ValueError('网址无效')
            urls = {item.rstrip('.,，。；;！？!?)）]') for item in re.findall(r'https://[^\s<>"\']+', goal)}
            read_urls={s.get('output',{}).get('url') for s in task.get('steps',[])
                       if s.get('status')=='done' and s.get('tool') in ('read_page','search')}
            allowed_url = url in read_urls if automatic else bool(re.search(r'打开|浏览器|open|browser', goal, re.I) and url in urls)
            if not allowed_url:
                raise ValueError('请在任务中明确要求打开用户提供的网址')
            parts = urlsplit(url)
            host = (parts.hostname or '').lower()
            if (parts.scheme != 'https' or not host or parts.username or parts.password or
                    parts.port not in (None, 443) or parts.query or parts.fragment or
                    not any(host == d or host.endswith('.'+d) for d in self.domains)):
                raise ValueError('仅支持配置来源范围内、不带参数的 HTTPS 网页')
            return {'action':'open_browser','url':url}
        if name == 'open_notepad':
            if not automatic and not re.search(r'记事本|notepad', goal, re.I):
                raise ValueError('请在任务中明确写出使用记事本')
            if not task.get('file'):
                raise ValueError('请先用 write_note 为本任务保存内容')
            return {'action':'open_notepad','task_id':task['id']}
        if name == 'open_calculator':
            if automatic or not re.search(r'计算器|calculator', goal, re.I):
                raise ValueError('请在任务中明确写出打开计算器')
            return {'action':'open_calculator'}
        raise ValueError('未知电脑工具')

    async def execute(self, action, task):
        payload = self.allowed(action, task)
        try:
            token = (self.root/'data'/'desktop-token').read_text(encoding='utf-8').strip()
        except OSError:
            raise ValueError('本机电脑工具未启动，请检查 desktop 服务') from None
        if not re.fullmatch(r'[A-Za-z0-9_-]{40,100}', token):
            raise ValueError('本机电脑工具凭据格式无效')
        async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
            response = await client.post(self.url+'/execute', json=payload,
                                         headers={'Authorization':'Bearer '+token})
            if response.status_code != 200:
                raise ValueError('本机电脑工具拒绝或无法完成此操作')
            result = response.json()
            if result.get('ok') is not True:
                raise ValueError('本机电脑工具未确认执行')
            return {'opened':str(result.get('opened',''))[:100]}
