import copy
import io
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import AsyncMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_chat import chat, CONFIG
from storage import Store
from voice_call import install_call, split_call_speech


def audio():
    result = io.BytesIO()
    with wave.open(result, 'wb') as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(16000)
        out.writeframes(b'\x00\x10' * 16000)
    return result.getvalue()


class CallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'test.sqlite')
        self.store.touch('private:300', '100', 300, None, 'saber')
        self.store.set_preference('companion_qq', 300)
        self.engine = chat.Engine(self.store)
        self.engine.recognition.transcribe_wav = AsyncMock(return_value=('你好', 1))
        self.engine.speech.synthesize = AsyncMock(return_value=audio())
        config = copy.deepcopy(CONFIG)
        config['dashboard']['access_token'] = 'test-only-token'
        self.answer = AsyncMock(return_value=('{"text":"你好呀","emotion":"warm"}', [
            {'role': 'system', 'content': 'system'}, {'role': 'user', 'content': '你好'}]))
        async def mock_answer(*args, **kwargs):
            raw, messages = self.answer.return_value
            if kwargs.get('on_fragment'):
                text, _, _ = chat.message_payload(raw)
                for number, part in enumerate(split_call_speech(text)):
                    await kwargs['on_fragment'](part, number)
            return raw, messages
        self.answer.side_effect = mock_answer
        self.patcher = patch.object(chat, 'answer', self.answer)
        self.patcher.start(); self.addCleanup(self.patcher.stop)
        app = FastAPI(); install_call(app, self.engine, config)
        self.client = TestClient(app)

    def test_call_turn_and_saved_context(self):
        with self.client.websocket_connect('/call/ws', headers={'origin':'http://testserver'}) as ws:
            ws.send_json({'token':'test-only-token'})
            self.assertEqual(ws.receive_json()['type'], 'ready')
            ws.send_json({'type':'turn_id', 'id':42})
            ws.send_bytes(audio())
            first = ws.receive_json()
            self.assertEqual((first['type'], first['id']), ('phase', 42))
            self.assertEqual(ws.receive_json()['type'], 'transcript')
            self.assertEqual(ws.receive_json()['type'], 'phase')
            self.assertEqual(ws.receive_json()['type'], 'phase')
            self.assertEqual(ws.receive_json()['text'], '你好呀')
            self.assertEqual(ws.receive_bytes(), audio())
        self.assertEqual(self.store.get('private:300')['history'][-1]['content'], '你好呀')

    def test_interrupt_cancels_unfinished_turn(self):
        import asyncio
        async def slow_answer(*args, **kwargs):
            await asyncio.sleep(30)
        self.answer.side_effect = slow_answer
        with self.client.websocket_connect('/call/ws', headers={'origin':'http://testserver'}) as ws:
            ws.send_json({'token':'test-only-token'}); ws.receive_json()
            ws.send_bytes(audio())
            self.assertEqual(ws.receive_json()['type'], 'phase')
            self.assertEqual(ws.receive_json()['type'], 'transcript')
            self.assertEqual(ws.receive_json()['type'], 'phase')
            ws.send_json({'type':'interrupt'})
            ws.send_bytes(b'bad')
            self.assertEqual(ws.receive_json()['type'], 'phase')
            self.assertEqual(ws.receive_json()['type'], 'error')
        self.assertEqual(self.store.get('private:300')['history'], [])

    def test_call_specific_token_cannot_replace_panel_token_without_configuration(self):
        token_file = Path(self.temp.name) / 'call-token'
        token_file.write_text('b' * 64, encoding='utf-8')
        config = copy.deepcopy(CONFIG)
        config['dashboard']['access_token'] = 'test-only-token'
        app = FastAPI()
        with patch.dict('os.environ', {'SABER_QQ_CALL_TOKEN_FILE': str(token_file)}):
            install_call(app, self.engine, config)
        with TestClient(app).websocket_connect('/call/ws', headers={'origin':'http://testserver'}) as ws:
            ws.send_json({'token':'b' * 64, 'caller_uin':'300'})
            self.assertEqual(ws.receive_json()['type'], 'ready')
        with TestClient(app).websocket_connect('/call/ws', headers={'origin':'http://testserver'}) as ws:
            ws.send_json({'token':'b' * 64, 'caller_uin':'301'})
            self.assertEqual(ws.receive_json()['type'], 'error')

    def test_recognized_bridge_text_reuses_transcript_without_second_asr(self):
        token_file = Path(self.temp.name) / 'bridge-token'
        token_file.write_text('b' * 64, encoding='utf-8')
        config = copy.deepcopy(CONFIG); config['dashboard']['access_token'] = 'test-only-token'
        app = FastAPI()
        with patch.dict('os.environ', {'SABER_QQ_CALL_TOKEN_FILE': str(token_file)}):
            install_call(app, self.engine, config)
        with TestClient(app).websocket_connect('/call/ws', headers={'origin':'http://testserver'}) as ws:
            ws.send_json({'token':'b' * 64, 'caller_uin':'300'}); self.assertEqual(ws.receive_json()['type'], 'ready')
            ws.send_json({'type':'recognized','id':17,'text':'你好'})
            self.assertEqual(ws.receive_json()['type'], 'phase')
            self.assertEqual(ws.receive_json()['type'], 'transcript')
            self.assertEqual(ws.receive_json()['type'], 'phase')
            self.assertEqual(ws.receive_json()['type'], 'audio_chunk')
            self.assertEqual(ws.receive_bytes(), audio())
            self.assertEqual(ws.receive_json()['id'], 17)
        self.engine.recognition.transcribe_wav.assert_not_awaited()

    def test_long_reply_sent_as_ordered_audio_chunks(self):
        text = '你回来啦，今天是不是有点累？我给你倒杯水，我们慢慢聊一会儿吧。'
        self.answer.return_value = ('{"text":"'+text+'","emotion":"warm"}', [
            {'role':'system','content':'system'}, {'role':'user','content':'你好'}])
        chunks = split_call_speech(text)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertEqual(''.join(chunks), text)
        token_file = Path(self.temp.name) / 'bridge-token'
        token_file.write_text('b' * 64, encoding='utf-8')
        config = copy.deepcopy(CONFIG); config['dashboard']['access_token'] = 'test-only-token'
        app = FastAPI()
        with patch.dict('os.environ', {'SABER_QQ_CALL_TOKEN_FILE': str(token_file)}):
            install_call(app, self.engine, config)
        with TestClient(app).websocket_connect('/call/ws', headers={'origin':'http://testserver'}) as ws:
            ws.send_json({'token':'b' * 64, 'caller_uin':'300'}); ws.receive_json()
            ws.send_json({'type':'recognized','id':21,'text':'你好'})
            for _ in range(3): ws.receive_json()
            for index in range(len(chunks)):
                event=ws.receive_json()
                self.assertEqual((event['type'],event['id'],event['index']), ('audio_chunk',21,index))
                self.assertEqual(ws.receive_bytes(),audio())
            self.assertEqual(ws.receive_json()['type'], 'reply')
        self.assertEqual(self.engine.speech.synthesize.await_count,len(chunks))

    def test_bad_token_and_origin(self):
        with self.client.websocket_connect('/call/ws', headers={'origin':'http://testserver'}) as ws:
            ws.send_json({'token':'wrong'})
            self.assertEqual(ws.receive_json()['type'], 'error')
        from starlette.websockets import WebSocketDisconnect
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('/call/ws', headers={'origin':'https://evil.example'}):
                pass

    def test_only_one_call(self):
        with self.client.websocket_connect('/call/ws', headers={'origin':'http://testserver'}) as first:
            first.send_json({'token':'test-only-token'}); self.assertEqual(first.receive_json()['type'], 'ready')
            with self.client.websocket_connect('/call/ws', headers={'origin':'http://testserver'}) as second:
                second.send_json({'token':'test-only-token'})
                self.assertIn('已有一个', second.receive_json()['message'])

if __name__ == '__main__': unittest.main()
