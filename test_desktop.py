"""桌面桥只能执行显式授权的有限操作；测试不打开真实窗口。"""
import asyncio
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
import httpx
from desktop_bridge import DesktopBridge
from scripts import desktop_service as service
from storage import Store
from test_chat import chat


class DesktopPolicyTests(unittest.TestCase):
    def setUp(self):
        self.bridge=DesktopBridge('.',{'sspai.com'},lambda:True)
        self.task={'id':'a'*32,'goal':'打开浏览器 https://sspai.com/post/1 并使用记事本和计算器','file':'a'*32+'.md','automatic':False}

    def test_only_explicit_manual_scoped_actions(self):
        self.assertEqual(self.bridge.allowed({'tool':'open_browser','url':'https://sspai.com/post/1'},self.task)['action'],'open_browser')
        self.assertEqual(self.bridge.allowed({'tool':'open_notepad'},self.task)['task_id'],'a'*32)
        self.assertEqual(self.bridge.allowed({'tool':'open_calculator'},self.task)['action'],'open_calculator')
        for task,action in ((dict(self.task,automatic=True),{'tool':'open_calculator'}),
            (dict(self.task,goal='读取 https://sspai.com/post/1'),{'tool':'open_browser','url':'https://sspai.com/post/1'}),
            (self.task,{'tool':'open_browser','url':'https://evil.com/'}),
            (dict(self.task,goal='打开 https://sspai.com/?q=abc'),{'tool':'open_browser','url':'https://sspai.com/?q=abc'}),
            (dict(self.task,goal='打开 https://sspai.com/other'),{'tool':'open_browser','url':'https://sspai.com/'}),
            (dict(self.task,goal='整理笔记'),{'tool':'open_notepad'}),
            (dict(self.task,file=''),{'tool':'open_notepad'}),
            (self.task,{'tool':'shell','command':'delete all'})):
            with self.assertRaises(ValueError):self.bridge.allowed(action,task)
        self.bridge.enabled=lambda:False
        with self.assertRaises(ValueError):self.bridge.allowed({'tool':'open_calculator'},self.task)

    def test_valid_url_rejects_local_dns_and_non_whitelist(self):
        answer=[(2,1,6,'',('8.8.8.8',443))]
        with patch.object(service.socket,'getaddrinfo',return_value=answer):
            self.assertTrue(service.valid_url('https://sspai.com/post/1',{'sspai.com'}))
            for url in ('http://sspai.com/','https://evil.com/','https://sspai.com/?x=1','https://sspai.com:444/'):
                self.assertFalse(service.valid_url(url,{'sspai.com'}))
        with patch.object(service.socket,'getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
            self.assertFalse(service.valid_url('https://sspai.com/',{'sspai.com'}))

    def test_automatic_needs_opt_in_idle_real_read_and_note_and_single_window(self):
        self.bridge.automatic_enabled=lambda:True
        self.bridge.automatic_guard=lambda task:True
        task={'id':'a'*32,'goal':'自主阅读','automatic':True,'file':'a'*32+'.md',
              'steps':[{'status':'done','tool':'read_page','output':{'url':'https://sspai.com/post/1'}}]}
        self.assertEqual(self.bridge.allowed({'tool':'open_browser','url':'https://sspai.com/post/1'},task)['action'],'open_browser')
        for action, candidate in [({'tool':'open_browser','url':'https://sspai.com/post/2'},task),
                                  ({'tool':'open_notepad'},dict(task,file='')),
                                  ({'tool':'open_calculator'},task),
                                  ({'tool':'open_notepad'},dict(task,steps=task['steps']+[{'status':'done','tool':'open_browser'}]))]:
            with self.assertRaises(ValueError):self.bridge.allowed(action,candidate)
        self.bridge.automatic_guard=lambda task:False
        with self.assertRaises(ValueError):self.bridge.allowed({'tool':'open_notepad'},task)

    def test_only_existing_random_task_note_opens_notepad(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); folder=root/'data'/'workspace';folder.mkdir(parents=True)
            (folder/('a'*32+'.md')).write_text('test',encoding='utf-8')
            with patch.object(service.sys,'platform','win32'),patch.object(service.subprocess,'Popen') as popen:
                self.assertTrue(service.perform({'action':'open_notepad','task_id':'a'*32},set(),root)['ok'])
                self.assertEqual(popen.call_count,1)
                for task in ('../../a','b'*32):
                    with self.assertRaises(ValueError):service.perform({'action':'open_notepad','task_id':task},set(),root)

    def test_http_requires_token_and_rejects_browser_origin(self):
        token='x'*48
        server=ThreadingHTTPServer(('127.0.0.1',0),service.make_handler(token,{'sspai.com'}))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        url='http://127.0.0.1:'+str(server.server_port)
        with httpx.Client(trust_env=False) as client:
            self.assertEqual(client.get(url+'/health').status_code,401)
            self.assertEqual(client.get(url+'/health',headers={'Authorization':'Bearer '+token,'Origin':'http://evil.test'}).status_code,401)
            self.assertEqual(client.get(url+'/health',headers={'Authorization':'Bearer '+token}).status_code,200)
            self.assertEqual(client.post(url+'/execute',headers={'Authorization':'Bearer '+token},json={'action':'shell'}).status_code,400)


class DesktopReportTests(unittest.IsolatedAsyncioTestCase):
    async def test_automatic_guard_respects_new_messages_and_pause(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp)/'db');store.touch('100:u:300','100',300,None,'saber');store.set_preference('companion_qq',300)
            store.set_preference('harness:auto',True);store.opt_in('100:u:300',True)
            engine=chat.Engine(store);state=store.get('100:u:300')
            task={'session':'100:u:300','expected_last_user':state['last_user']}
            with patch.object(chat,'quiet',return_value=False):
                self.assertTrue(engine.autonomous_desktop_allowed(task))
                self.assertFalse(engine.autonomous_desktop_allowed(dict(task,expected_last_user=0)))
                store.set_preference('paused',True)
                self.assertFalse(engine.autonomous_desktop_allowed(task))

    async def test_only_manual_companion_desktop_results_queue_report(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp)/'db');store.touch('100:u:300','100',300,None,'saber');store.set_preference('companion_qq',300)
            engine=chat.Engine(store)
            task={'session':'100:u:300','status':'done','automatic':False,'result':'完成',
                  'steps':[{'tool':'open_calculator','status':'done','output':{'opened':'计算器'}}]}
            engine.report_desktop_task(task)
            job=engine.queue.get_nowait();self.assertEqual(job.kind,'task_report');self.assertIn('计算器',job.text)
            store.set_preference('companion_qq',301);engine.report_desktop_task(task)
            self.assertTrue(engine.queue.empty())

    async def test_qq_task_is_scoped_to_bound_private_and_creates_one_job(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp)/'db');store.touch('100:u:300','100',300,None,'saber');store.set_preference('companion_qq',300)
            engine=chat.Engine(store);state=engine.effective_state(store.get('100:u:300'))
            job=chat.Job('100',300,None,'100:u:300','/任务 打开计算器',0)
            with patch.object(engine.harness,'start',return_value={'id':'a'*32}) as start:
                self.assertIn('开始处理',engine.command(job,state))
                start.assert_called_once_with('打开计算器',job.key,notify=True)
            job.group_id=200
            with patch.object(engine.harness,'start',Mock()) as start:
                self.assertIn('私聊',engine.command(job,state));start.assert_not_called()
