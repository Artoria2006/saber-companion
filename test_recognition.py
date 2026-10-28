"""语音获取、识别边界和消息处理测试，不使用真实 QQ、模型或私人音频。"""
import asyncio
import base64
import copy
import io
import json
import sys
import tempfile
import time
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import httpx
from fastapi.testclient import TestClient
from recognition import Recognition, RecognitionError, validate_wav
from settings import DEFAULTS, validate_config, ConfigError
from test_chat import chat, private, group
from storage import Store
from scripts.run_asr_api import create_app


def wav_data(seconds=1):
    out=io.BytesIO()
    with wave.open(out,'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(b'\x00\x10'*int(seconds*16000))
    return out.getvalue()


class RecognitionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config=dict(DEFAULTS['asr'],enabled=True)
        self.recognition=Recognition(self.config)
        self.bot=SimpleNamespace(get_record=AsyncMock(return_value={'base64':base64.b64encode(wav_data()).decode(),
                                                                  'file':'/private/path.wav','url':'http://untrusted.invalid'}))

    async def test_audio_bytes_only_are_sent_to_local_service(self):
        requests=[]
        def handle(request):
            requests.append(request)
            return httpx.Response(200,json={'text':'今天我很开心。','uncertain':False,'duration_seconds':1})
        original=httpx.AsyncClient
        with patch('recognition.httpx.AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handle),**kw)):
            self.assertEqual(await self.recognition.transcribe(self.bot,'audio-id.amr'),('今天我很开心。',1))
        self.bot.get_record.assert_awaited_once_with(file='audio-id.amr',out_format='wav')
        self.assertEqual(len(requests),1)
        self.assertEqual(requests[0].content,wav_data())
        self.assertEqual(str(requests[0].url),self.config['url']+'/transcribe')
        self.assertNotIn('authorization',requests[0].headers)

    async def test_file_paths_and_urls_cannot_be_used_as_audio_ids(self):
        for value in ('/etc/passwd','../secret','file:///tmp/x','https://evil.invalid/x','C:\\secret','a\n'):
            with self.assertRaises(RecognitionError):await self.recognition.transcribe(self.bot,value)
        self.bot.get_record.assert_not_awaited()

    async def test_bad_audio_and_oversized_base64_stop_before_http(self):
        for value in ('not base64!',base64.b64encode(b'not a wav').decode(),'x'*(12*1024*1024)):
            self.bot.get_record.return_value={'base64':value}
            with self.assertRaises(RecognitionError):await self.recognition.transcribe(self.bot,'id.amr')
        with self.assertRaises(RecognitionError):validate_wav(wav_data(2),8388608,1)
        with self.assertRaises(RecognitionError):validate_wav(wav_data()[:-8],8388608,60)

    async def test_uncertain_and_silent_results_are_not_used_as_chat(self):
        original=httpx.AsyncClient
        for status,payload in [(422,{}),(200,{'text':'猜测内容','uncertain':True}),(200,{'text':''})]:
            with patch('recognition.httpx.AsyncClient',lambda **kw:original(transport=httpx.MockTransport(lambda r:httpx.Response(status,json=payload)),**kw)):
                with self.assertRaises(RecognitionError):await self.recognition.transcribe(self.bot,'id.amr')

    async def test_voice_only_message_enters_queue_and_transcript_does_not_run_commands(self):
        with tempfile.TemporaryDirectory() as temp:
            engine=chat.Engine(Store(Path(temp)/'state.sqlite3'))
            await engine.enqueue(SimpleNamespace(self_id='100'),private('[CQ:record,file=id.amr]'))
            job=engine.queue.get_nowait()
            self.assertEqual(job.voice_file,'id.amr')
            with patch.object(chat,'get_bot',return_value=self.bot),patch.object(engine.recognition,'transcribe',AsyncMock(return_value=('/重置',1))), \
                 patch.object(engine,'command') as command,patch.object(chat,'answer',AsyncMock(return_value=('我听到了。',None))) as answer, \
                 patch.object(engine,'send',AsyncMock()):
                await engine.process(job)
            command.assert_not_called()
            self.assertIn('/重置',answer.call_args.args[1])
            self.assertTrue(any(x['kind']=='asr' and x['status']=='done' for x in engine.store.activities(job.key)))

    async def test_failure_asks_for_clarification_without_calling_model(self):
        with tempfile.TemporaryDirectory() as temp:
            engine=chat.Engine(Store(Path(temp)/'state.sqlite3'))
            await engine.enqueue(SimpleNamespace(self_id='100'),private('[CQ:record,file=id.amr]'))
            job=engine.queue.get_nowait()
            with patch.object(chat,'get_bot',return_value=self.bot),patch.object(engine.recognition,'transcribe',AsyncMock(side_effect=RecognitionError('没听清，请再说一次。'))), \
                 patch.object(chat,'answer',AsyncMock()) as answer,patch.object(engine,'send',AsyncMock()) as send:
                await engine.process(job)
            answer.assert_not_awaited()
            self.assertIn('没听清',send.call_args.args[1])
            self.assertFalse(await chat.addressed(SimpleNamespace(self_id='100'),group('[CQ:record,file=id.amr]')))


class BackendTests(unittest.TestCase):
    def test_service_rejects_silence_low_confidence_and_long_audio(self):
        config=dict(DEFAULTS['asr'])
        fake_audio=SimpleNamespace(decode_audio=lambda *a,**k:object())
        for segments,status in [([],422),([SimpleNamespace(text='幻听',no_speech_prob=.1,avg_logprob=-1.5)],422),
                                ([SimpleNamespace(text='你好。',no_speech_prob=.1,avg_logprob=-.3)],200)]:
            model=SimpleNamespace(transcribe=lambda *a,**k:(iter(segments),None))
            with patch.dict(sys.modules,{'faster_whisper.audio':fake_audio}),TestClient(create_app(model,config)) as h:
                r=h.post('/transcribe',content=wav_data());self.assertEqual(r.status_code,status)
                self.assertEqual(h.post('/transcribe',content=b'bad').status_code,400)
                self.assertEqual(h.get('/health').json()['provider'],'faster_whisper')
        with TestClient(create_app(None,dict(config,max_bytes=100))) as h:
            self.assertEqual(h.post('/transcribe',content=wav_data()).status_code,413)

    def test_asr_config_rejects_external_hosts_and_invalid_limits(self):
        for changes in ({'url':'http://evil.invalid:9881'},{'enabled':'true'},{'max_seconds':0},
                        {'min_avg_logprob':float('nan')},{'max_bytes':99999999}):
            c=copy.deepcopy(chat.C);c['asr']=dict(DEFAULTS['asr'],**changes)
            c['model']['api_key']='test-model-key-123456789012345'
            c['server']['access_token']='test-ws-token-1234567890123456789'
            c['napcat']['webui_token']='test-panel-token-1234567890123456789'
            with self.assertRaises(ConfigError):validate_config(c)


if __name__=='__main__':unittest.main()
