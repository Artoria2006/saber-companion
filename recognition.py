"""通过 OneBot 获取语音字节，再交给本机识别服务；不读取任意路径或网址。"""
import asyncio
import base64
import binascii
import io
import re
import wave
import httpx


class RecognitionError(ValueError):
    """可直接向用户说明的语音识别问题。"""


def validate_wav(data, max_bytes, max_seconds):
    if not isinstance(data, bytes) or not 44 <= len(data) <= max_bytes:
        raise RecognitionError("这条语音文件太大或内容不完整，请分成短句再发。")
    try:
        with wave.open(io.BytesIO(data)) as wav:
            channels, width, rate, frames = wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes()
            if channels not in (1, 2) or width != 2 or not 8000 <= rate <= 48000:
                raise RecognitionError("这条语音的音频格式暂时无法识别，请重新录一条。")
            duration = frames / rate
            if not 0.2 <= duration <= max_seconds:
                raise RecognitionError(f"请把语音控制在 {max_seconds:g} 秒以内，再发给我。")
            if len(wav.readframes(frames)) != frames * channels * width:
                raise RecognitionError("这条语音没有完整下载，请重新发一次。")
            return duration
    except (wave.Error, EOFError) as exc:
        raise RecognitionError("语音转码没有返回有效的 WAV，请管理员检查 [asr] 日志。") from exc


class Recognition:
    def __init__(self, config):
        self.config = config
        self.semaphore = asyncio.Semaphore(1)

    async def transcribe(self, bot, file_id):
        c = self.config
        if not c["enabled"]:
            raise RecognitionError("我暂时还没开启语音识别，可以先打字告诉我。")
        # QQ 上报的是文件标识或文件名；禁止将其解释成路径、URL、Base64 或命令。
        if (not isinstance(file_id, str) or not 1 <= len(file_id) <= 512
                or re.search(r"[\\/:\x00-\x20]", file_id) or ".." in file_id):
            raise RecognitionError("这条语音的文件标识无效，请重新录一条。")

        async def work():
            async with self.semaphore:
                result = await bot.get_record(file=file_id, out_format="wav")
                encoded = result.get("base64") if isinstance(result, dict) else None
                if not isinstance(encoded, str) or len(encoded) > ((c["max_bytes"] + 2) // 3) * 4:
                    raise RecognitionError("未取得完整语音或文件太大，请分成短句重新发送。")
                try:
                    data = base64.b64decode(encoded, validate=True)
                except (ValueError, binascii.Error) as exc:
                    raise RecognitionError("下载的语音内容不完整，请重新发送。") from exc
                validate_wav(data, c["max_bytes"], c["max_seconds"])
                async with httpx.AsyncClient(timeout=c["timeout_seconds"], trust_env=False) as client:
                    async with client.stream("POST", c["url"].rstrip('/') + "/transcribe", content=data,
                                             headers={"Content-Type":"audio/wav"}) as response:
                        if response.status_code == 422:
                            raise RecognitionError("这句我没听清，可以换个说法再说一次，或打字告诉我吗？")
                        response.raise_for_status()
                        raw = bytearray()
                        async for chunk in response.aiter_bytes():
                            raw.extend(chunk)
                            if len(raw) > 32768:
                                raise RecognitionError("识别结果异常，请管理员检查 [asr] 日志。")
                import json
                value = json.loads(raw)
                text = value.get("text")
                if value.get("uncertain") or not isinstance(text, str) or not text.strip() or len(text) > 3000:
                    raise RecognitionError("这句我没听清，可以再说一次，或打字告诉我吗？")
                return text.strip(), value.get("duration_seconds")
        return await asyncio.wait_for(work(), timeout=c["timeout_seconds"])
