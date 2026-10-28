"""中文语音合成：只发送待朗读正文，限制时长、大小与并发，不保存私人音频。"""
import asyncio
import random
import re
import time
import io
import wave
from array import array
import edge_tts
import httpx

VOICES = {"zh-CN-XiaoxiaoNeural": "晓晓 · 中文女声", "zh-CN-XiaoyiNeural": "晓伊 · 中文女声"}
EMOTIONS = {"neutral":"平静", "warm":"温柔", "cheerful":"开心", "serious":"认真", "sleepy":"晚安"}
SAMPLE = "我在呢。今天辛苦了，先歇一会儿吧。想说话的时候，我会陪着你。"


def requested(text):
    # 明确请求才触发；谈论设置、关闭语音或否定句不算请求。
    if re.search(r"(?:不想|不要|别|不用|不必|关闭|取消|禁止).{0,8}(?:语音|声音|说话)", text):
        return False
    return bool(re.search(r"想听.{0,8}(?:你|她|Saber|saber).{0,3}(?:的)?声音|(?:用|发|来|说|回).{0,4}(?:条|段)?语音|语音(?:回复|回答|说|聊)", text))


def speakable(text):
    # 链接、代码和长篇说明保留文字，避免语音丢失原始信息。
    return bool(text.strip()) and not re.search(r"https?://|```", text)


def spoken_text(text):
    # 只去掉纯表演标记和排版符号，保留有实际信息的括号内容。
    text = re.sub(r'[（(](?:轻笑|笑|微笑|低声|轻声|温柔地|停顿|叹气)[）)]', '', text)
    return re.sub(r'[*#_`<>]', '', text).strip()


class Speech:
    def __init__(self, config, store):
        self.config, self.store = dict(config), store
        self.semaphore = asyncio.Semaphore(2)
        self.preview_at = 0

    def settings(self):
        value = self.config | self.store.preference("voice_settings", {})
        value.setdefault("provider", "edge")
        available = self.voices()
        if value["voice"] not in available:
            value["voice"] = self.config["voice"] if self.config["voice"] in available else next(iter(available), "zh-CN-XiaoxiaoNeural")
        return value

    def voices(self):
        if self.config.get("provider") == "gpt_sovits":
            return {key:"Saber · "+EMOTIONS.get(key,key) for key in self.config.get("references",{})}
        return VOICES

    def update(self, values):
        updates = {}
        if "voice" in values:
            if not isinstance(values["voice"], str) or values["voice"] not in self.voices():
                raise ValueError("请选择支持的中文女声")
            updates["voice"] = values["voice"]
        for name, minimum, maximum in (("rate_percent", -50, 25), ("pitch_hz", -20, 20)):
            if name in values:
                if type(values[name]) is not int or not minimum <= values[name] <= maximum:
                    raise ValueError(f"{name} 必须在 {minimum} 到 {maximum} 之间")
                updates[name] = values[name]
        if "proactive_probability" in values:
            value = values["proactive_probability"]
            if type(value) not in (int, float) or not 0 <= value <= 1:
                raise ValueError("主动语音概率必须在 0 到 1 之间")
            updates["proactive_probability"] = value
        self.store.set_preference("voice_settings", self.store.preference("voice_settings", {}) | updates)

    def choose(self, job, force=False):
        config = self.settings()
        prefs = self.store.preference("session:" + job.key, {})
        if not config["enabled"] or job.group_id is not None or not prefs.get("voice_enabled", True):
            return False
        if force:
            return True
        return (job.proactive and time.time() - self.store.preference("last_voice:" + job.key, 0) >= config["min_interval_seconds"]
                and random.random() < config["proactive_probability"])

    async def synthesize(self, text, auto_emotion=False, emotion=""):
        if self.settings().get("provider") == "gpt_sovits":
            return await self.synthesize_gsv(text,auto_emotion,emotion)
        return await self.synthesize_edge(text)

    def reference_name(self,text,auto_emotion=False,emotion=""):
        config=self.settings()
        name=config["voice"]
        if auto_emotion and not config.get("lock_reference",False):
            style=self.emotion_name(text,emotion)
            if style in config["references"]:
                return style
        return name

    def emotion_name(self,text,emotion=""):
        if emotion in EMOTIONS:
            return emotion
        for key, words in (("sleepy",("晚安","睡吧")),("warm",("抱抱","辛苦","陪着你","别难过")),("cheerful",("太好了","好开心"))):
            if any(word in text for word in words):
                return key
        name=self.settings()["voice"]
        return name if name in EMOTIONS else "neutral"

    async def synthesize_gsv(self, text, auto_emotion=False, emotion="", preview_variant="baseline"):
        config = self.settings()
        if not config["enabled"] or not speakable(text) or len(text) > config["max_chars"]:
            raise ValueError("语音未开启或正文不适合朗读")
        text = spoken_text(text)
        if not text:
            raise ValueError("朗读正文为空")
        if preview_variant not in ('baseline','soft'):
            raise ValueError('试听版本不存在')
        # 使用明确配置的不同语气参考；没有对应素材时保持选定声线。
        name = self.reference_name(text,auto_emotion,emotion)
        ref = config["references"][name]
        # 锁定同一组参考时仅轻微改变节奏，不因语气标签更换音色。
        rate=config["rate_percent"]
        if auto_emotion:
            rate+=config.get("emotion_rates",{}).get(self.emotion_name(text,emotion),0)
        if preview_variant == 'soft':
            rate -= 3
        rate=max(-50,min(25,rate))
        payload = {"text":text,"text_lang":"all_zh","ref_audio_path":ref["audio_path"],"prompt_text":ref["text"],
                   "prompt_lang":("all_"+ref["language"] if ref["language"] in ("ja","zh") else "en"),"media_type":"wav","streaming_mode":False,"text_split_method":"cut5",
                   "batch_size":1,"parallel_infer":True,"speed_factor":1 + rate/100,
                   "fragment_interval":0.28 if preview_variant=='soft' else config.get("fragment_interval_seconds",0.3),
                   "aux_ref_audio_paths":ref.get("aux_audio_paths",[])}
        async def collect():
            async with self.semaphore, httpx.AsyncClient(timeout=config["timeout_seconds"],trust_env=False) as client:
                async with client.stream("POST",config["gpt_sovits_url"].rstrip('/')+"/tts",json=payload) as response:
                    response.raise_for_status()
                    data=bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data)>config["max_bytes"]:
                            raise ValueError("本地合成音频超过大小上限")
                    if len(data)<44 or data[:4]!=b"RIFF" or data[8:12]!=b"WAVE":
                        raise ValueError("本地服务没有返回有效 WAV 音频")
                    try:
                        with wave.open(io.BytesIO(data)) as wav:
                            if wav.getsampwidth()!=2 or wav.getnchannels() not in (1,2) or not 0.2<=wav.getnframes()/wav.getframerate()<=90:
                                raise ValueError("本地音频格式或时长不适合发送")
                            samples=array('h',wav.readframes(wav.getnframes()))
                            if not samples or max(abs(x) for x in samples)<64:
                                raise ValueError("本地合成结果接近静音")
                    except (wave.Error,EOFError) as exc:
                        raise ValueError("本地音频结构损坏") from exc
                    return bytes(data)
        return await asyncio.wait_for(collect(),timeout=config["timeout_seconds"])

    async def synthesize_edge(self, text):
        config = self.settings()
        if not config["enabled"]:
            raise ValueError("语音功能未启用，请将 voice.enabled 设为 true 后重启")
        if not speakable(text) or len(text) > config["max_chars"]:
            raise ValueError("回复过长或含链接、代码，本次保留文字")
        # 删除常见排版标记，让语气自然；不允许输入自定义 SSML。
        text = re.sub(r"[*#_`<>]", "", text).strip()

        async def collect():
            async with self.semaphore:
                chunks, size = [], 0
                voice = config["voice"] if config["voice"] in VOICES else "zh-CN-XiaoxiaoNeural"
                stream = edge_tts.Communicate(text, voice, rate=f"{config['rate_percent']:+d}%",
                                              pitch=f"{config['pitch_hz']:+d}Hz")
                async for chunk in stream.stream():
                    if chunk["type"] == "audio":
                        size += len(chunk["data"])
                        if size > config["max_bytes"]:
                            raise ValueError("合成音频超过大小上限")
                        chunks.append(chunk["data"])
                if not chunks:
                    raise ValueError("语音服务没有返回音频")
                return b"".join(chunks)
        return await asyncio.wait_for(collect(), timeout=config["timeout_seconds"])
