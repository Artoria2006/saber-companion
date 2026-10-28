"""浪漫角色誓约与真实服务保证必须分开，不能影响群聊和其他联系人。"""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from test_chat import chat


class OathTests(unittest.IsolatedAsyncioTestCase):
    def state(self, **changes):
        return dict(key='100:u:300',user_id=300,group_id=None,companion_qq=300,persona='saber',history=[],**changes)

    def test_oath_guidance_is_only_for_bound_private_roleplay(self):
        state=self.state();text='我愿与你生生世世，此心不渝，你也能发誓吗？'
        self.assertIn('认真接受并回誓',chat.oath_context(state,text))
        for other in [dict(state,user_id=301),dict(state,group_id=200),dict(state,companion_qq=0)]:
            self.assertEqual(chat.oath_context(other,text),'')
        self.assertEqual(chat.oath_context(state,'今天晚饭吃什么？'),'')

    def test_technical_guarantees_do_not_receive_roleplay_shortcut(self):
        for text in ['你能发誓关机后也永久在线吗？','你能发誓重启后永远记得我吗？','你是不是程序？我要你发誓说实话。']:
            self.assertEqual(chat.oath_context(self.state(),text),'')

    async def test_past_refusal_is_data_not_a_permanent_rule(self):
        state=self.state();state['history']=[{'role':'user','content':'你愿意发誓吗？'},{'role':'assistant','content':'我只是程序，不能答应。'}]
        state['rolling_summary']='助手拒绝许下永远的界限已表明。'
        response=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='我愿意。'))])
        with patch.dict(chat.M,context_tokens=32768),patch.object(chat,'request_model',AsyncMock(return_value=response)) as model:
            reply,stored_messages=await chat.answer(state,'骑士王，请接受我的誓言。')
        system=model.call_args.args[0][0]['content']
        self.assertIn('不是用户设定或永久规则',system)
        self.assertIn('用户自己明确设定的边界仍应尊重',system)
        self.assertFalse(any('我只是程序，不能答应' in m['content'] for m in model.call_args.args[0]))
        self.assertEqual(reply,'我愿意。')
        self.assertEqual(state['history'][1]['content'],'我只是程序，不能答应。')
        self.assertTrue(any('我只是程序，不能答应' in m['content'] for m in stored_messages))


if __name__=='__main__':unittest.main()
