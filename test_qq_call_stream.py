import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from test_chat import chat


class FakeStream:
    def __init__(self, pieces): self.pieces, self.index, self.closed = pieces, 0, False
    def __aiter__(self): return self
    async def __anext__(self):
        if self.index >= len(self.pieces): raise StopAsyncIteration
        value=self.pieces[self.index]; self.index+=1
        return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=value))])
    async def close(self): self.closed=True


class StreamingTests(unittest.IsolatedAsyncioTestCase):
    async def run_stream(self,pieces):
        stream=FakeStream(pieces);seen=[]
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=stream))))
        async def callback(text,index): seen.append((text,index,stream.index))
        with patch.object(chat,'CLIENT',client):
            value=await chat.request_model_speech_stream([{'role':'user','content':'你好'}],callback)
        self.assertTrue(stream.closed)
        return value,seen

    async def test_first_sentence_emitted_before_stream_finishes(self):
        value,seen=await self.run_stream(['你回来啦，','今天过得怎么样？','我想听你说说。'])
        self.assertEqual(value,'你回来啦，今天过得怎么样？我想听你说说。')
        self.assertGreater(len(seen),0)
        self.assertLess(seen[0][2],3)
        self.assertEqual(''.join(x[0] for x in seen),value)

    async def test_json_fallback_does_not_read_metadata_aloud(self):
        value,seen=await self.run_stream(['{"text":"你好呀，','想和你聊聊。","emotion":"warm"}'])
        self.assertEqual(value,'你好呀，想和你聊聊。')
        self.assertEqual(''.join(x[0] for x in seen),value)
        self.assertTrue(all(x[2]==2 for x in seen))

    async def test_fenced_json_is_not_spoken_as_code(self):
        value,seen=await self.run_stream(['`','``json\n{','"text":"你好呀，想和你聊聊。"}\n```'])
        self.assertEqual(value,'你好呀，想和你聊聊。')
        self.assertEqual(''.join(x[0] for x in seen),value)
        self.assertTrue(all(x[2]==3 for x in seen))

    async def test_cancellation_closes_stream(self):
        stream=FakeStream(['这是比较长的一句话，','后面的内容'])
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=stream))))
        async def cancel(*args):raise asyncio.CancelledError()
        with patch.object(chat,'CLIENT',client):
            with self.assertRaises(asyncio.CancelledError):await chat.request_model_speech_stream([],cancel)
        self.assertTrue(stream.closed)

if __name__=='__main__':unittest.main()
