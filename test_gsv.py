"""本机推理客户端、配置边界与故障回退测试，不加载真实模型。"""
import copy
import json
import io
import wave
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import httpx
from test_chat import chat
from settings import validate_config, ConfigError, DEFAULTS
from speech import Speech
from storage import Store


def config():
    return dict(DEFAULTS["voice"],enabled=True,provider="gpt_sovits",voice="neutral",gpt_sovits_url="http://127.0.0.1:9880",
                references={"neutral":{"audio_path":"D:/saber-voice/references/neutral.wav","text":"こんばんは。","language":"ja"},
                            "warm":{"audio_path":"D:/saber-voice/references/anchor.wav","text":"我在呢。","language":"zh",
                                    "aux_audio_paths":["D:/saber-voice/references/warm.wav"]}})


class LocalVoiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/"voice.sqlite3")
        self.speech=Speech(config(),self.store)

    async def test_local_request_is_bounded_and_contains_only_voice_inputs(self):
        captured=[]
        buffer=io.BytesIO()
        with wave.open(buffer,'wb') as out:
            out.setnchannels(1);out.setsampwidth(2);out.setframerate(8000);out.writeframes(b'\0\x10'*3200)
        wav=buffer.getvalue()
        def handler(request):
            captured.append((str(request.url),json.loads(request.content),dict(request.headers)))
            return httpx.Response(200,content=wav,headers={"content-type":"audio/wav"})
        original=httpx.AsyncClient
        with patch("speech.httpx.AsyncClient",lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs)):
            self.assertEqual(await self.speech.synthesize("辛苦了，抱抱。",auto_emotion=True),wav)
        url,payload,headers=captured[0]
        self.assertEqual(url,"http://127.0.0.1:9880/tts")
        self.assertEqual(payload["ref_audio_path"],config()["references"]["warm"]["audio_path"])
        self.assertEqual(payload["text_lang"],"all_zh")
        self.assertEqual(payload["prompt_lang"],"all_zh")
        self.assertEqual(payload["aux_ref_audio_paths"],config()["references"]["warm"]["aux_audio_paths"])
        self.assertNotIn("authorization",headers)
        self.assertNotIn("history",payload)

    async def test_invalid_audio_and_excessive_payload_are_rejected(self):
        original=httpx.AsyncClient
        for content in (b'{"error":"no model"}',b"x"*3000):
            self.speech.config["max_bytes"]=1024
            transport=httpx.MockTransport(lambda request:httpx.Response(200,content=content))
            with patch("speech.httpx.AsyncClient",lambda **kwargs:original(transport=transport,**kwargs)):
                with self.assertRaises(ValueError):await self.speech.synthesize("你好。")

    def test_switching_provider_does_not_reuse_incompatible_saved_voice(self):
        self.store.set_preference("voice_settings",{"voice":"zh-CN-XiaoyiNeural"})
        self.assertEqual(self.speech.settings()["voice"],"neutral")
        self.speech.update({"voice":"warm"})
        self.assertEqual(self.speech.settings()["voice"],"warm")
        with self.assertRaises(ValueError):self.speech.update({"voice":"nonexistent"})

    def test_preview_keeps_selected_reference_while_chat_can_choose_emotion(self):
        self.assertEqual(self.speech.reference_name("辛苦了，抱抱。"),"neutral")
        self.assertEqual(self.speech.reference_name("辛苦了，抱抱。",True),"warm")
        self.assertEqual(self.speech.reference_name("一起聊聊。",True,"warm"),"warm")
        self.assertEqual(chat.message_emotion('{"text":"我在。","emotion":"warm"}'),"warm")
        self.assertEqual(chat.message_emotion('{"text":"我在。","emotion":"../../file"}'),"")

    async def test_local_failure_can_fall_back_and_is_recorded(self):
        engine=chat.Engine(self.store);engine.speech=self.speech
        self.store.touch("100:u:300","100",300,None,"saber")
        job=chat.Job("100",300,None,"100:u:300","",time.time())
        bot=SimpleNamespace(send_private_msg=AsyncMock(return_value={"message_id":1}))
        with patch.object(chat,"get_bot",return_value=bot),patch.dict(chat.H,send_interval_seconds=0), \
             patch.object(self.speech,"synthesize",AsyncMock(side_effect=httpx.ConnectError("offline"))), \
             patch.object(self.speech,"synthesize_edge",AsyncMock(return_value=b"ID3sample")) as fallback:
            await engine.send(job,"我在。",voice=True)
        fallback.assert_awaited_once()
        self.assertTrue(any(x["detail"].get("fallback") for x in self.store.activities(job.key)))
        self.assertEqual(bot.send_private_msg.call_args.kwargs["message"][0].type,"record")

    async def test_disabled_fallback_preserves_text(self):
        engine=chat.Engine(self.store);engine.speech=self.speech;self.speech.config["fallback_to_edge"]=False
        self.store.touch("100:u:300","100",300,None,"saber")
        job=chat.Job("100",300,None,"100:u:300","",time.time())
        bot=SimpleNamespace(send_private_msg=AsyncMock(return_value={"message_id":1}))
        with patch.object(chat,"get_bot",return_value=bot),patch.dict(chat.H,send_interval_seconds=0), \
             patch.object(self.speech,"synthesize",AsyncMock(side_effect=RuntimeError())), \
             patch.object(self.speech,"synthesize_edge",AsyncMock()) as fallback:
            await engine.send(job,"我在。",voice=True)
        fallback.assert_not_called()
        self.assertEqual(bot.send_private_msg.call_args.kwargs["message"][0].type,"text")


class LocalConfigTests(unittest.TestCase):
    def valid_config(self):
        value=copy.deepcopy(chat.C)
        value["voice"]=config()
        value["model"]["api_key"]="test-model-key-123456789012345"
        value["server"]["access_token"]="test-ws-token-1234567890123456789"
        value["napcat"]["webui_token"]="test-panel-token-1234567890123456789"
        return value

    def test_local_config_rejects_external_hosts_and_missing_reference(self):
        for changes in ({"gpt_sovits_url":"http://example.com:9880"},{"references":{}},{"voice":"missing"},{"fallback_to_edge":"yes"}):
            value=self.valid_config();value["voice"].update(changes)
            with self.assertRaises(ConfigError):validate_config(value)
        self.assertEqual(validate_config(self.valid_config())["voice"]["provider"],"gpt_sovits")

    def test_auxiliary_paths_must_be_a_bounded_list(self):
        for paths in ("file.wav", ["a.wav"]*6, [42], [""]):
            value=self.valid_config()
            value["voice"]["references"]["warm"]["aux_audio_paths"]=paths
            with self.assertRaises(ConfigError):validate_config(value)


if __name__=="__main__":unittest.main()
