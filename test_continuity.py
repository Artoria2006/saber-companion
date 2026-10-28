"""验证摘要不丢原文、不跨会话、清空后不复活，以及角色状态的保守变化。"""
import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from continuity import Continuity, mood_event, mood_label
from settings import DEFAULTS, ConfigError, validate_config
from storage import Store
from dashboard import install_dashboard
from test_chat import chat


def response(summary='用户讨论了工作安排，尚未确定日期；角色答应继续听用户说。'):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({'summary':summary},ensure_ascii=False)))])


class ContinuityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'old.sqlite3')
        self.store.touch('100:u:300','100',300,None,'saber')
        history=[m for i in range(10) for m in ({'role':'user','content':f'用户在讨论计划第{i}步'},
                                               {'role':'assistant','content':f'角色确认尚未完成第{i}步'})]
        self.store.save_history('100:u:300',history,'saber',20)
        self.c=Continuity(self.store,dict(DEFAULTS['summary'],enabled=True),dict(DEFAULTS['mood'],enabled=True),20)
        self.state=self.store.get('100:u:300');self.owner=self.c.ensure(self.state)
        self.events=[]

    def snapshot(self):
        return self.store.summary_candidates(10)[0]

    def log(self,*args):self.events.append(args)

    async def test_success_moves_cursor_and_keeps_recent_exact_words(self):
        self.c.summary['archive_turns']=2
        request=AsyncMock(return_value=response())
        self.assertTrue(await self.c.summarize(self.snapshot(),request,chat.tokens,self.log))
        saved=self.store.companion(self.owner)
        self.assertEqual(saved['pending_turns'],4)
        self.assertEqual(saved['archive_turns'],4)
        context=self.c.context(self.state)
        self.assertEqual(len(context['history']),8)
        self.assertIn('第6步',context['history'][0]['content'])
        self.assertIn('用户讨论',context['rolling_summary'])
        self.assertEqual(request.call_args.kwargs['max_tokens'],800)
        self.assertFalse(self.store.summary_candidates(10))
        self.assertEqual(self.store.memories(self.owner),[])

    async def test_failure_retains_previous_summary_and_all_unsummarized_turns(self):
        version=self.snapshot()['summary_version']
        for result in (response('x'*1201),SimpleNamespace(choices=[])):
            self.assertFalse(await self.c.summarize(self.store.companion(self.owner),AsyncMock(return_value=result),chat.tokens,self.log))
            saved=self.store.companion(self.owner)
            self.assertEqual(saved['summary_version'],version)
            self.assertEqual(saved['pending_turns'],10)
            self.assertEqual(saved['archive_turns'],10)
            self.assertGreater(saved['summary_retry_at'],time.time())
        self.assertFalse(self.store.summary_candidates(10))

    async def test_clear_during_request_prevents_old_summary_resurrection(self):
        async def request(*args,**kwargs):
            self.store.clear_summary(self.owner,4)
            return response('过时的摘要')
        self.assertFalse(await self.c.summarize(self.snapshot(),request,chat.tokens,self.log))
        saved=self.store.companion(self.owner)
        self.assertEqual(saved['summary'],'')
        self.assertEqual(saved['pending_turns'],4)
        self.assertEqual(self.events[-1][2],'cancelled')

    async def test_new_message_during_summary_is_not_removed(self):
        async def request(*args,**kwargs):
            self.store.append_dialogue(self.owner,'新的纠正：不是周五','我按你的纠正理解。')
            return response()
        self.assertTrue(await self.c.summarize(self.snapshot(),request,chat.tokens,self.log))
        pending=self.store.pending_dialogue(self.owner)
        self.assertEqual(len(pending),5)
        self.assertIn('新的纠正',pending[-1]['user_text'])

    async def test_input_budget_failure_does_not_discard_long_source(self):
        request=AsyncMock(return_value=response())
        self.assertFalse(await self.c.summarize(self.snapshot(),request,lambda messages:999999,self.log))
        request.assert_not_awaited()
        self.assertEqual(len(self.store.pending_dialogue(self.owner)),10)

    async def test_summary_and_mood_are_added_as_bounded_context(self):
        await self.c.summarize(self.snapshot(),AsyncMock(return_value=response()),chat.tokens,self.log)
        state=self.c.context(self.state,'你是废物')
        with patch.dict(chat.M,context_tokens=32768),patch.object(chat,'request_model',AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='我听着。'))]))) as model:
            await chat.answer(state,'我想继续聊计划。')
        system=model.call_args.args[0][0]['content']
        self.assertIn('自动滚动摘要',system)
        self.assertIn('不等于用户确认',system)
        self.assertIn('当前角色相处状态',system)

    def test_criticism_negation_quotation_and_personal_distress_do_not_lower_mood(self):
        for text in ['你的声音不好听','我今天很难过','我工作累死了','他说“你是废物”','“你是废物”是他骂的话','你是废物这句话是他骂我的','你不是废物','你让我失望了']:
            self.assertEqual(mood_event(text,self.c.mood)[0],0,text)
        self.assertLess(mood_event('Saber，你是废物',self.c.mood)[0],0)
        self.assertLess(mood_event('你是个废物',self.c.mood)[0],0)
        self.assertGreater(mood_event('对不起，刚才不该骂你。',self.c.mood)[0],0)

    def test_mood_is_persistent_clamped_and_recovers_by_elapsed_time(self):
        score=self.c.context(self.state,'你是废物')['mood']
        self.assertEqual(score,53)
        saved=self.store.companion(self.owner)
        later=saved['mood_at']+3600
        self.assertAlmostEqual(self.store.update_mood(self.owner,65,6,now=later),59)
        self.assertAlmostEqual(self.store.update_mood(self.owner,65,6,now=later),59)
        for _ in range(10):self.store.update_mood(self.owner,65,0,-20,'直接冒犯',now=later)
        self.assertEqual(Store(self.store.path).companion(self.owner)['mood'],0)
        self.assertEqual(mood_label(0),'有些受伤')
        self.assertEqual(self.store.update_mood(self.owner,65,0,10,'收到道歉',now=later),10)
        for _ in range(10):self.store.update_mood(self.owner,65,0,20,'收到亲近表达',now=later)
        self.assertEqual(self.store.companion(self.owner)['mood'],100)

    def test_other_sessions_and_groups_do_not_inherit_private_state(self):
        self.c.context(self.state,'你是废物')
        self.store.touch('100:u:301','100',301,None,'saber')
        other=self.c.context(self.store.get('100:u:301'))
        self.assertEqual(other['mood'],65)
        self.assertFalse(other['rolling_summary'])
        self.store.touch('100:g:200','100',300,200,'saber')
        group=self.c.context(self.store.get('100:g:200'),'你是废物')
        self.assertNotIn('mood',group)
        self.assertNotIn('rolling_summary',group)

    def test_reset_invalidates_pending_summary_and_keeps_explicit_memory(self):
        self.c.mood['baseline']=80;self.store.mood_baseline=80
        snapshot=self.snapshot()
        self.store.remember(self.owner,'喜欢喝茶',20)
        self.store.save_history(self.state['key'],[],'saber',20)
        self.assertFalse(self.store.finish_summary(self.owner,snapshot['summary_version'],1,'旧内容',200))
        saved=self.store.companion(self.owner)
        self.assertEqual(saved['pending_turns'],0)
        self.assertEqual(saved['mood'],80)
        self.assertEqual(self.store.memories(self.owner)[0]['content'],'喜欢喝茶')


class ContinuityPanelTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'test.sqlite3');self.engine=chat.Engine(self.store)
        self.engine.continuity=Continuity(self.store,dict(DEFAULTS['summary'],enabled=True),dict(DEFAULTS['mood'],enabled=True),20)
        self.store.touch('100:u:300','100',300,None,'saber');self.store.touch('100:g:200','100',300,200,'saber')
        config=copy.deepcopy(chat.C);config['dashboard']['access_token']='test-continuity-token-123456789012345'
        app=FastAPI();install_dashboard(app,self.engine,config,chat.quiet,chat.CHINA)
        self.client=TestClient(app);self.addCleanup(self.client.close)
        self.headers={'Authorization':'Bearer '+config['dashboard']['access_token']}

    def test_controls_require_auth_and_do_not_accept_group_write(self):
        self.assertEqual(self.client.get('/panel/api/continuity',params={'session':'100:u:300'}).status_code,401)
        r=self.client.get('/panel/api/continuity',params={'session':'100:u:300'},headers=self.headers)
        self.assertEqual(r.status_code,200);self.assertTrue(r.json()['summary_enabled'])
        self.assertEqual(self.client.post('/panel/api/continuity',json={'session':'100:g:200','action':'reset_mood'},headers=self.headers).status_code,400)
        for action in ['reset_mood','clear_summary']:
            self.assertEqual(self.client.post('/panel/api/continuity',json={'session':'100:u:300','action':action},headers=self.headers).status_code,200)

    def test_new_config_limits_are_validated(self):
        for section,changes in [('summary',{'keep_recent_messages':20}),('summary',{'trigger_messages':21}),
                                ('summary',{'enabled':'true'}),('mood',{'recovery_per_hour':float('nan')}),('mood',{'negative_delta':True})]:
            value=copy.deepcopy(chat.C);value[section].update(changes)
            value['model']['api_key']='test-api-key-1234567890123456789'
            value['server']['access_token']='test-ws-key-1234567890123456789'
            value['napcat']['webui_token']='test-panel-key-1234567890123456789'
            with self.assertRaises(ConfigError):validate_config(value)

    def test_panel_script_is_revalidated_after_upgrades(self):
        response=self.client.get('/panel/static/app.js')
        self.assertEqual(response.status_code,200)
        self.assertIn('no-cache',response.headers['cache-control'])


if __name__=='__main__':unittest.main()
