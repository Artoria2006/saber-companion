"""为 QQ 电话桥生成只供本机使用的来电授权和专用密钥。"""
import os
import secrets
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from settings import load_config
from storage import Store

ROOT = Path(__file__).resolve().parent.parent

def main():
    config = load_config()
    store = Store(ROOT / 'data' / 'assistant.sqlite3')
    user = store.preference('companion_qq', config['chat'].get('companion_qq', 0))
    if not user or not any(s['group_id'] is None and s['user_id'] == user for s in store.sessions()):
        raise SystemExit('请先在面板中将你的 QQ 私聊设为伴侣账号。')
    number = str(user)
    if not number.isascii() or not number.isdigit() or not 5 <= len(number) <= 15 or number.startswith('0'):
        raise SystemExit('伴侣 QQ 号格式无效，未创建授权文件。')
    target = ROOT / 'data' / 'qq-call'
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    token_path = target / 'access-token'
    if not token_path.exists():
        fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            out.write(secrets.token_hex(32))
    if len(token_path.read_text(encoding='utf-8').strip()) < 32:
        raise SystemExit('已有通话密钥长度不足，未修改该文件。')
    number_path = target / 'allowed-uin'
    if number_path.exists() and number_path.read_text(encoding='utf-8').strip() != number:
        raise SystemExit('已有授权账号与当前绑定不一致，未覆盖旧授权文件。')
    number_path.write_text(number, encoding='utf-8')
    print('通话授权文件已准备，未显示账号或密钥。')

if __name__ == '__main__': main()
