import io
import httpx
import unittest
import wave
from scripts.qq_call_worker import VoiceDetector, FRAME_BYTES, pcm_wav, components_ready, recognize_audio

class AudioTests(unittest.TestCase):
    def test_voice_end_and_valid_wav(self):
        vad = VoiceDetector(start_frames=3, end_frames=4, speech_test=lambda frame, rate: True)
        quiet = b'\0' * FRAME_BYTES
        loud = b'\xe8\x03' * (FRAME_BYTES // 2)
        for _ in range(2): self.assertEqual(vad.push(quiet), (False, None))
        for _ in range(2): self.assertFalse(vad.push(loud)[0])
        self.assertTrue(vad.push(loud)[0])
        for _ in range(3): self.assertIsNone(vad.push(quiet)[1])
        pcm = vad.push(quiet)[1]
        with wave.open(io.BytesIO(pcm_wav(pcm))) as audio:
            self.assertEqual((audio.getnchannels(), audio.getframerate(), audio.getsampwidth()), (1, 16000, 2))
            self.assertEqual(audio.getnframes() * 2, len(pcm))
        self.assertFalse(vad.recording)

    def test_noise_never_creates_call_and_long_audio_is_bounded(self):
        vad = VoiceDetector(start_frames=2, end_frames=4, max_frames=5, speech_test=lambda frame, rate: True)
        quiet = b'\0' * FRAME_BYTES
        loud = b'\xe8\x03' * (FRAME_BYTES // 2)
        for _ in range(50): self.assertEqual(vad.push(quiet), (False, None))
        result = None
        for _ in range(10):
            _, result = vad.push(loud)
            if result: break
        self.assertIsNotNone(result)
        self.assertLessEqual(len(result), 5 * FRAME_BYTES)

    def test_requires_native_initialization_before_answering(self):
        native = {'ready': True, 'pluginFound': True}
        self.assertFalse(components_ready({'listenerRegistered': True, 'avHost': {'loginConfirmed': False}}, native))
        self.assertFalse(components_ready({'listenerRegistered': True, 'avHost': {'loginConfirmed': True}}, {'ready': False}))
        self.assertTrue(components_ready({'listenerRegistered': True, 'avHost': {'loginConfirmed': True}}, native))

    def test_rejects_partial_frame(self):
        with self.assertRaises(ValueError): VoiceDetector().push(b'\0')

    def test_loud_non_speech_does_not_interrupt(self):
        vad = VoiceDetector(speech_test=lambda frame, rate: False)
        noise = b'\xe8\x03' * (FRAME_BYTES // 2)
        for _ in range(50): self.assertEqual(vad.push(noise), (False, None))

    def test_default_voice_trigger_requires_five_frames(self):
        vad = VoiceDetector(speech_test=lambda frame, rate: True)
        voice = b'\xe8\x03' * (FRAME_BYTES // 2)
        for _ in range(4): self.assertFalse(vad.push(voice)[0])
        self.assertTrue(vad.push(voice)[0])

class RecognitionTests(unittest.IsolatedAsyncioTestCase):
    async def test_noise_and_uncertain_audio_are_not_sent(self):
        responses = iter([httpx.Response(422), httpx.Response(200,json={'text':'无效','uncertain':True}),
                          httpx.Response(200,json={'text':'你好','uncertain':False})])
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: next(responses))) as client:
            pcm = b'\0' * 16000
            self.assertIsNone(await recognize_audio(client, pcm, 'http://asr/transcribe'))
            self.assertIsNone(await recognize_audio(client, pcm, 'http://asr/transcribe'))
            self.assertEqual(await recognize_audio(client, pcm, 'http://asr/transcribe'), '你好')

if __name__ == '__main__': unittest.main()
