"""仅监听本机的 Windows 桌面桥，拒绝任意程序、路径、命令和网站参数。"""
import argparse
import hmac
import ipaddress
import json
import os
import re
import secrets
import socket
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from settings import load_config


def valid_url(url, domains):
    if not isinstance(url, str) or len(url)>1200 or any(ord(c)<33 for c in url):
        return False
    try:
        p=urlsplit(url); host=(p.hostname or '').lower()
        if (p.scheme!='https' or not host or p.username or p.password or p.port not in (None,443)
                or p.query or p.fragment or not any(host==d or host.endswith('.'+d) for d in domains)):
            return False
        # 禁止把已配置域名解析到内网；浏览器后续跳转不由此服务控制。
        answers=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
        return bool(answers) and all(ipaddress.ip_address(row[4][0]).is_global for row in answers)
    except (ValueError, OSError):
        return False


def perform(data, domains, root=ROOT):
    if sys.platform != 'win32' or not isinstance(data,dict):
        raise ValueError('仅支持 Windows')
    action=data.get('action')
    system=Path(os.environ.get('SystemRoot', r'C:\Windows'))/'System32'
    if action=='open_browser' and set(data)=={'action','url'} and valid_url(data['url'],domains):
        os.startfile(data['url'])
        return {'ok':True,'opened':'默认浏览器'}
    if action=='open_calculator' and set(data)=={'action'}:
        subprocess.Popen([str(system/'calc.exe')],close_fds=True)
        return {'ok':True,'opened':'计算器'}
    if action=='open_notepad' and set(data)=={'action','task_id'}:
        task=data['task_id']
        if not isinstance(task,str) or not re.fullmatch(r'[0-9a-f]{32}',task):
            raise ValueError('任务编号无效')
        directory=root/'data'/'workspace';path=directory/(task+'.md')
        if directory.is_symlink() or path.is_symlink() or path.resolve().parent!=directory.resolve() or not path.is_file():
            raise ValueError('笔记不存在或路径无效')
        subprocess.Popen([str(system/'notepad.exe'),str(path)],close_fds=True)
        return {'ok':True,'opened':'记事本（任务笔记）'}
    raise ValueError('不允许的操作')


def make_handler(token, domains):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def reply(self, status, value):
            payload=json.dumps(value,ensure_ascii=False).encode('utf-8')
            self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(payload)));self.send_header('Cache-Control','no-store')
            self.end_headers();self.wfile.write(payload)
        def authorized(self):
            # 不接受网页跨站请求，也不记录认证值。
            return not self.headers.get('Origin') and hmac.compare_digest(self.headers.get('Authorization',''), 'Bearer '+token)
        def do_GET(self):
            if not self.authorized():return self.reply(401,{'ok':False})
            return self.reply(200,{'ok':True,'service':'desktop-bridge'}) if self.path=='/health' else self.reply(404,{'ok':False})
        def do_POST(self):
            if not self.authorized():return self.reply(401,{'ok':False})
            if self.path!='/execute':return self.reply(404,{'ok':False})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if size<=0 or size>4096:raise ValueError('请求大小无效')
                data=json.loads(self.rfile.read(size))
                return self.reply(200,perform(data,domains))
            except Exception:
                return self.reply(400,{'ok':False,'error':'操作未完成或不在允许范围'})
    return Handler


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=9882);args=parser.parse_args()
    data=ROOT/'data';data.mkdir(parents=True,exist_ok=True)
    token_file=data/'desktop-token'
    if not token_file.exists():
        try:
            with token_file.open('x',encoding='utf-8') as f:f.write(secrets.token_urlsafe(36))
        except FileExistsError:pass
    token=token_file.read_text(encoding='utf-8').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{40,100}',token):raise ValueError('电脑工具凭据无效')
    config=load_config();domains=set(config['proactive']['search_domains'])
    domains.update(urlsplit(url).hostname for url in config['proactive']['sources'])
    server=ThreadingHTTPServer(('127.0.0.1',args.port),make_handler(token,domains))
    print('桌面桥已启动，仅监听本机。',flush=True)
    server.serve_forever()


if __name__=='__main__':main()
