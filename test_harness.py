"""任务执行器的权限、停止、持久化与工具循环测试，不连接真实模型。"""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from harness import Harness
from storage import Store
from test_chat import chat


def response(action):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(action)))])


class HarnessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root/'test.db')
        self.request = AsyncMock()
        self.h = Harness(self.store, {'sources':['https://example.com/'], 'search_enabled':False},
                         self.root, {'context_tokens':8192}, self.request, Mock())

    async def test_read_write_finish_and_no_arbitrary_filename(self):
        self.request.side_effect = [response({'tool':'read_page','url':'https://example.com/'}),
            response({'tool':'write_note','text':'笔记 https://example.com/', 'path':'../../config.toml'}),
            response({'tool':'finish','text':'已完成笔记。'})]
        with patch('harness.read_page', AsyncMock(return_value={'url':'https://example.com/','text':'文章'})):
            task = self.h.start('读一篇文章写笔记', 'owner')
            await self.h.active
        self.assertEqual(task['status'], 'done')
        self.assertEqual(self.h.artifact(task['id']).read_text(encoding='utf-8'), '笔记 https://example.com/')
        self.assertFalse((self.root/'config.toml').exists())
        self.assertEqual(len(task['steps']), 3)

    async def test_denies_shell_and_search_without_opt_in(self):
        for action in ({'tool':'shell','command':'del D:'}, {'tool':'search','query':'测试'}):
            with self.assertRaises(ValueError):
                await self.h.tool(action, {'id':'a'*32})
        with self.assertRaises(ValueError):
            self.h.artifact('../../config.toml')

    async def test_stop_cancels_inflight_model_and_single_task(self):
        entered = asyncio.Event()
        async def wait(*a, **kw):
            entered.set()
            await asyncio.Event().wait()
        self.request.side_effect = wait
        task = self.h.start('测试停止', 'owner')
        await entered.wait()
        with self.assertRaises(ValueError):
            self.h.start('第二项任务', 'owner')
        self.h.stop(task['id'])
        await self.h.active
        self.assertEqual(self.h.items()[0]['status'], 'cancelled')

    async def test_restart_marks_interrupted_without_replay(self):
        self.h.save({'id':'a'*32,'status':'running'})
        self.h.recover()
        self.assertEqual(self.h.items()[0]['status'], 'interrupted')
        self.request.assert_not_called()

    async def test_step_limit_and_no_overwrite(self):
        self.request.return_value = response({'tool':'shell','command':'whoami'})
        task = self.h.start('测试工具权限', 'owner')
        await self.h.active
        self.assertEqual(task['status'], 'limited')
        self.assertEqual(self.request.await_count, 6)
        await self.h.tool({'tool':'write_note','text':'第一份'}, task)
        with self.assertRaises(ValueError):
            await self.h.tool({'tool':'write_note','text':'覆盖'}, task)


class AutonomousTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_tool_receipts_ground_share_and_user_activity_cancels(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp)/'db.sqlite3')
            store.touch('100:u:300','100',300,None,'saber')
            store.set_preference('companion_qq',300)
            store.set_preference('harness:auto',True)
            engine = chat.Engine(store)
            request = AsyncMock(side_effect=[
                response({'tool':'read_page','url':'https://example.com/article'}),
                response({'tool':'write_note','text':'一份有来源的笔记'}),
                response({'tool':'finish','text':'完成'})])
            engine.harness = Harness(store, {'sources':['https://example.com/'],'search_enabled':False,'max_page_chars':1000},
                                     temp, {'context_tokens':8192}, request, engine.record)
            job = chat.Job('100',300,None,'100:u:300','',0,proactive=True)
            with patch.object(chat,'P',dict(chat.P, max_page_chars=1000)), patch.object(engine,'still_wanted',return_value=True), \
                 patch('harness.read_page',AsyncMock(return_value={'url':'https://example.com/article','text':'实际网页'})):
                reading=await engine.autonomous_reading(job,{'query':'生活','summary':'想看看'})
            self.assertEqual(reading['url'],'https://example.com/article')
            self.assertIn('实际网页',reading['text'])
            self.assertIn('一份有来源的笔记',reading['text'])
            self.assertTrue(engine.harness.items()[0]['automatic'])
            request.side_effect=[response({'tool':'finish','text':'自称读到 https://fake.example'})]
            with patch.object(engine,'still_wanted',return_value=True):
                self.assertIsNone(await engine.autonomous_reading(job,{'query':'生活'}))
            request.side_effect=[response({'tool':'finish','text':'完成'})]
            with patch.object(engine,'still_wanted',return_value=False):
                self.assertIsNone(await engine.autonomous_reading(job,{'query':'生活'}))

    async def test_global_pause_cancels_only_automatic_task(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp)/'db.sqlite3')
            engine=chat.Engine(store)
            event=asyncio.Event()
            async def wait(*args,**kwargs):
                event.set()
                await asyncio.Event().wait()
            engine.harness=Harness(store,{'sources':[],'search_enabled':False},temp,{'context_tokens':8192},wait,engine.record)
            task=engine.harness.start('自主探索','100:u:300',automatic=True)
            await event.wait()
            engine.pause(True)
            await engine.harness.active
            self.assertEqual(engine.harness.items()[0]['status'],'cancelled')
            self.assertTrue(store.preference('paused'))
