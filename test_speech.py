"""语音合成、触发条件、失败降级和管理接口的离线测试。"""
import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from test_chat import chat, private
import test_dashboard as paneltests
from nonebot.adapters.onebot.v11 import Message
from speech import Speech, requested, spoken_text
from storage import Store


class VoiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name)/"voice.sqlite3")
        self.engine = chat.Engine(self.store)
        self.engine.speech.config["enabled"] = True
        self.bot = SimpleNamespace(self_id="100",send_private_msg=AsyncMock(return_value={"message_id":1}))
        self.store.touch("100:u:300","100",300,None,"saber")
        self.job = chat.Job("100",300,None,"100:u:300","",time.time())

    def test_explicit_requests_and_negations(self):
        for text in ("想听你的声音", "我想听她声音", "给我发条语音吧", "用语音回复我", "语音回答"):
            self.assertTrue(requested(text),text)
        for text in ("你好", "语音设置在哪", "不要发语音", "不想听你的声音", "别用语音回复我"):
            self.assertFalse(requested(text),text)

    async def test_warmup_only_once_per_voice_service_process(self):
        speech = self.engine.speech
        config = {'enabled': True, 'provider': 'gpt_sovits', 'gpt_sovits_url': 'http://localhost:9880',
                  'voice': 'warm', 'references': {'warm': {'audio_path': 'reference.wav'}}}
        replies = iter([1, 1, 2])
        class Client:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def get(self, url):
                return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'ok': True, 'pid': next(replies)})
        async def sleep(_):
            if synth.call_count == 2:
                raise asyncio.CancelledError()
        with patch.object(speech, 'settings', return_value=config), \
             patch.object(speech, 'reference_name', return_value='warm'), \
             patch.object(speech, 'synthesize_gsv', new_callable=AsyncMock) as synth, \
             patch('speech.httpx.AsyncClient', return_value=Client()), \
             patch('speech.asyncio.sleep', side_effect=sleep):
            with self.assertRaises(asyncio.CancelledError):
                await speech.warmup_loop()
            self.assertEqual(synth.call_count, 2)

    def test_spoken_text_removes_only_stage_directions(self):
        self.assertEqual(spoken_text('（轻笑）我在呢。（今天周三）'), '我在呢。（今天周三）')
        self.assertEqual(spoken_text('**晚安**，先休息。'), '晚安，先休息。')

    def test_automatic_voice_respects_scope_probability_and_cooldown(self):
        self.assertFalse(self.engine.speech.choose(self.job))
        self.job.proactive=True
        with patch("speech.random.random",return_value=0.1):
            self.assertTrue(self.engine.speech.choose(self.job))
            self.store.set_preference("last_voice:"+self.job.key,time.time())
            self.assertFalse(self.engine.speech.choose(self.job))
            self.assertTrue(self.engine.speech.choose(self.job,force=True))
            self.job.group_id=123
            self.assertFalse(self.engine.speech.choose(self.job,force=True))
        self.job.group_id=None
        self.store.set_preference("session:"+self.job.key,{"voice_enabled":False})
        self.assertFalse(self.engine.speech.choose(self.job,force=True))

    async def test_synthesizes_bounded_audio_without_history(self):
        async def stream():
            yield {"type":"audio","data":b"ID3audio"}
        with patch("speech.edge_tts.Communicate",return_value=SimpleNamespace(stream=stream)) as factory:
            data=await self.engine.speech.synthesize("我在呢。")
        self.assertEqual(data,b"ID3audio")
        self.assertEqual(factory.call_args.args,("我在呢。","zh-CN-XiaoxiaoNeural"))
        self.assertEqual(factory.call_args.kwargs["rate"],"-8%")
        for text in ("x"*181,"https://example.com/","```print(1)```"):
            with self.assertRaises(ValueError):
                await self.engine.speech.synthesize(text)

    async def test_audio_size_empty_response_and_timeout(self):
        async def empty():
            yield {"type":"SentenceBoundary"}
        async def too_large():
            yield {"type":"audio","data":b"x"*20}
        async def slow():
            await asyncio.sleep(1)
            yield {"type":"audio","data":b"x"}
        self.engine.speech.config["max_bytes"]=10
        for generator in (empty,too_large):
            with patch("speech.edge_tts.Communicate",return_value=SimpleNamespace(stream=generator)):
                with self.assertRaises(ValueError):
                    await self.engine.speech.synthesize("测试")
        self.engine.speech.config["timeout_seconds"]=0.01
        with patch("speech.edge_tts.Communicate",return_value=SimpleNamespace(stream=slow)):
            with self.assertRaises(asyncio.TimeoutError):
                await self.engine.speech.synthesize("测试")

    async def test_sends_record_segment_and_records_ack(self):
        with patch.object(chat,"get_bot",return_value=self.bot),patch.dict(chat.H,send_interval_seconds=0), \
             patch.object(self.engine.speech,"synthesize",AsyncMock(return_value=b"ID3audio")):
            await self.engine.send(self.job,"我在呢。",voice=True)
        message=self.bot.send_private_msg.call_args.kwargs["message"]
        self.assertEqual([x.type for x in message],["record"])
        self.assertTrue(message[0].data["file"].startswith("base64://"))
        self.assertTrue(self.store.activities(self.job.key)[0]["detail"]["voice"])
        self.assertGreater(self.store.preference("last_voice:"+self.job.key),0)

    async def test_synthesis_failure_falls_back_to_text_once(self):
        with patch.object(chat,"get_bot",return_value=self.bot),patch.dict(chat.H,send_interval_seconds=0), \
             patch.object(self.engine.speech,"synthesize",AsyncMock(side_effect=RuntimeError())):
            await self.engine.send(self.job,"我在呢。",voice=True)
        self.assertEqual(self.bot.send_private_msg.await_count,1)
        message=self.bot.send_private_msg.call_args.kwargs["message"]
        self.assertEqual([x.type for x in message],["text"])
        self.assertTrue(any(x["kind"]=="speech" and x["status"]=="failed" for x in self.store.activities(self.job.key)))

    async def test_incoming_voice_request_uses_model_reply_not_canned_sample(self):
        event=private(Message("想听你的声音"))
        with patch.object(chat,"get_bot",return_value=self.bot),patch.dict(chat.H,send_interval_seconds=0,session_interval_seconds=0), \
             patch.object(chat,"answer",AsyncMock(return_value=("我在呀。",[{"role":"system","content":"test"},{"role":"user","content":"request"}]))) as model, \
             patch.object(self.engine.speech,"synthesize",AsyncMock(return_value=b"ID3audio")) as synth:
            await self.engine.enqueue(self.bot,event)
            await self.engine.process(self.engine.queue.get_nowait())
        self.assertTrue(model.call_args.kwargs["spoken"])
        synth.assert_awaited_once_with("我在呀。")
        self.assertEqual(self.store.get(self.job.key)["history"][-1]["content"],"我在呀。")

    async def test_proactive_cancelled_during_synthesis_is_not_sent(self):
        self.job.proactive=True
        self.store.opt_in(self.job.key,True)
        self.job.expected_last_user=self.store.get(self.job.key)["last_user"]
        async def synth(text):
            self.store.opt_in(self.job.key,False)
            return b"ID3audio"
        with patch.object(chat,"get_bot",return_value=self.bot),patch.object(chat,"quiet",return_value=False), \
             patch.object(self.engine.speech,"synthesize",synth),patch.dict(chat.H,send_interval_seconds=0):
            self.assertIsNone(await self.engine.send(self.job,"想你啦。",voice=True))
        self.bot.send_private_msg.assert_not_called()


class VoicePanelTests(unittest.TestCase):
    # 复用面板夹具，不重复执行已有面板用例。
    setUp = paneltests.PanelTests.setUp
    get = paneltests.PanelTests.get
    post = paneltests.PanelTests.post
    def test_voice_settings_and_preview_auth(self):
        result=self.post("/control",{"action":"voice_settings","voice":"zh-CN-XiaoyiNeural","rate_percent":-10})
        self.assertEqual(result.status_code,200)
        self.assertEqual(Speech(self.engine.speech.config,Store(self.store.path)).settings()["rate_percent"],-10)
        for bad in ({"voice":[]},{"rate_percent":True},{"pitch_hz":99},{"proactive_probability":1.1}):
            self.assertEqual(self.post("/control",{"action":"voice_settings",**bad}).status_code,400)
        self.assertEqual(self.client.post("/panel/api/voice/preview").status_code,401)
        with patch.object(self.engine.speech,"synthesize",AsyncMock(return_value=b"ID3sample")):
            response=self.client.post("/panel/api/voice/preview",headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers["content-type"],"audio/mpeg")
        self.assertEqual(response.content,b"ID3sample")
        self.assertEqual(self.client.post("/panel/api/voice/preview",headers=self.headers).status_code,429)

    def test_voice_test_only_targets_existing_private_voice_session(self):
        self.engine.speech.config["enabled"]=True
        with patch.object(chat,"get_bot",return_value=SimpleNamespace()):
            self.assertEqual(self.post("/control",{"action":"voice_test","session":"100:u:300"}).status_code,200)
            self.assertEqual(self.engine.queue.get_nowait().kind,"voice")
            self.assertEqual(self.post("/control",{"action":"voice_test","session":"100:g:200"}).status_code,400)


if __name__ == "__main__":
    unittest.main()
