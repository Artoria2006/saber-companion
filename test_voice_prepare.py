"""音频候选片段边界测试，不下载或读取私人视频。"""
import unittest
from scripts.prepare_voice_audio import candidates


class CandidateTests(unittest.TestCase):
    def test_silence_is_excluded_and_clips_are_bounded(self):
        log="silence_start: 4\nsilence_end: 6\nsilence_start: 18\nsilence_end: 20"
        self.assertEqual(candidates(log,24),[(0.0,4.0),(6.0,9.0),(15.0,3.0),(20.0,4.0)])

    def test_long_audio_is_split_without_too_short_tail(self):
        self.assertEqual(candidates("",20),[(0.0,9.0),(9.0,9.0)])

    def test_all_silence_creates_no_candidate(self):
        self.assertEqual(candidates("silence_start: 0",8),[])

    def test_natural_sentence_pause_remains_inside_reference(self):
        self.assertEqual(candidates("silence_start: 0.88\nsilence_end: 1.59\nsilence_start: 3.84\nsilence_end: 4.44",4.44),[(0.0,3.84)])


if __name__=="__main__":
    unittest.main()
