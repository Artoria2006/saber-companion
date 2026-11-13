"""电话授权准备只使用已绑定的私聊及配置指定的数据库。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import prepare_qq_call
from storage import Store


class CallPreparationTests(unittest.TestCase):
    def test_uses_configured_database_and_keeps_existing_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = Store(root / 'data' / 'alternate.sqlite3')
            store.touch('100:u:12345', '100', 12345, None, 'saber')
            store.set_preference('companion_qq', 12345)
            config = {'storage': {'path': 'data/alternate.sqlite3'}, 'chat': {'companion_qq': 0}}
            with patch.object(prepare_qq_call, 'ROOT', root), patch.object(prepare_qq_call, 'load_config', return_value=config):
                prepare_qq_call.main()
                token = (root / 'data/qq-call/access-token').read_text()
                prepare_qq_call.main()
            self.assertEqual((root / 'data/qq-call/allowed-uin').read_text(), '12345')
            self.assertEqual((root / 'data/qq-call/access-token').read_text(), token)
            self.assertGreaterEqual(len(token), 32)
            self.assertFalse((root / 'data/qq-call/armed').exists())

    def test_rejects_account_without_private_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = {'storage': {'path': 'data/db.sqlite3'}, 'chat': {'companion_qq': 12345}}
            with patch.object(prepare_qq_call, 'ROOT', root), patch.object(prepare_qq_call, 'load_config', return_value=config):
                with self.assertRaises(SystemExit):
                    prepare_qq_call.main()
            self.assertFalse((root / 'data/qq-call/access-token').exists())


if __name__ == '__main__':
    unittest.main()
