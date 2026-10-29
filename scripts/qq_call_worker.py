"""QQ AV 桥的音频工作进程；只在已验证来电者后读取和播放音频。"""
import asyncio
from array import array
import sys
import time
import contextlib
import io
import json
import logging
import os
import wave
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import websockets
import webrtcvad

LOG = logging.getLogger('qq_call_worker')
RATE = 16000
FRAME_BYTES = 640  # 单声道 16 kHz、16 位，20 毫秒。


class VoiceDetector:
    """结合人声检测与音量门槛，保留开头并限制单句长度。"""
    def __init__(self, threshold=300, start_frames=5, end_frames=40, max_frames=750, speech_test=None):
        self.threshold, self.start_frames, self.end_frames, self.max_frames = threshold, start_frames, end_frames, max_frames
        self.speech_test = speech_test or webrtcvad.Vad(2).is_speech
        self.pre = []
        self.frames = []
        self.loud = 0
        self.silent = 0
        self.recording = False

    def push(self, frame):
        if len(frame) != FRAME_BYTES:
            raise ValueError('invalid PCM frame')
        samples = array('h', frame)
        if sys.byteorder != 'little': samples.byteswap()
        loud = ((sum(value * value for value in samples) / len(samples)) ** .5 >= self.threshold
                and self.speech_test(frame, RATE))
        started = False
        completed = None
        if not self.recording:
            self.pre.append(frame)
            self.pre = self.pre[-min(15, max(1, self.max_frames - 1)):]
            self.loud = self.loud + 1 if loud else 0
            if self.loud >= self.start_frames:
                self.recording = started = True
                self.frames, self.pre = self.pre, []
                self.silent = 0
        else:
            self.frames.append(frame)
            self.silent = 0 if loud else self.silent + 1
            if self.silent >= self.end_frames or len(self.frames) >= self.max_frames:
                completed = b''.join(self.frames)
                self.pre, self.frames = [], []
                self.loud = self.silent = 0
                self.recording = False
        return started, completed


def pcm_wav(pcm):
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(RATE)
        output.writeframes(pcm)
    return stream.getvalue()


def read_secret(name):
    path = os.environ.get(name, '')
    if not path:
        raise ValueError(f'{name} 未配置')
    value = Path(path).read_text(encoding='utf-8').strip()
    if len(value) < 16:
        raise ValueError(f'{name} 文件内容过短')
    return value


async def bridge_status(client, token):
    response = await client.get('http://127.0.0.1:6110/v1/calls/current', headers={'Authorization': 'Bearer ' + token})
    response.raise_for_status()
    return response.json()['data']


async def recognize_audio(client, pcm, url='http://host.docker.internal:9881/transcribe'):
    response = await client.post(url, content=pcm_wav(pcm), headers={'Content-Type':'audio/wav'}, timeout=30)
    if response.status_code == 422:
        return None
    response.raise_for_status()
    value = response.json()
    text = value.get('text')
    if value.get('uncertain') or not isinstance(text, str) or not 1 <= len(text.strip()) <= 3000:
        return None
    return text.strip()


def components_ready(bridge, native):
    return bool(bridge.get('listenerRegistered') and (bridge.get('avHost') or {}).get('loginConfirmed')
                and native.get('ready') and native.get('pluginFound'))


async def terminate(process):
    if process and process.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), .35)
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError): process.kill()
            await process.wait()


async def play(wav_data, pulse_env):
    ffmpeg = await asyncio.create_subprocess_exec(
        'ffmpeg', '-nostdin', '-loglevel', 'error', '-i', 'pipe:0', '-f', 's16le', '-ac', '1', '-ar', '24000', 'pipe:1',
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    output = None
    async def feed():
        ffmpeg.stdin.write(wav_data)
        await ffmpeg.stdin.drain()
        ffmpeg.stdin.close()
    try:
        output = await asyncio.create_subprocess_exec('pacat', '--playback', '--raw', '--format=s16le', '--rate=24000',
            '--channels=1', '--latency-msec=120', '--process-time-msec=30', '--device=maibot_qq_mic', stdin=asyncio.subprocess.PIPE, env=pulse_env,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        feeder = asyncio.create_task(feed())
        try:
            while chunk := await ffmpeg.stdout.read(8192):
                output.stdin.write(chunk)
                await output.stdin.drain()
            await feeder
            output.stdin.close()
            await output.wait()
            await ffmpeg.wait()
            if ffmpeg.returncode or output.returncode:
                raise RuntimeError('音频播放进程失败')
        finally:
            if not feeder.done(): feeder.cancel()
            await asyncio.gather(feeder, return_exceptions=True)
    finally:
        # 先关闭播放管道并同时结束两个进程，避免转码器阻塞时声音继续播放。
        if ffmpeg.stdin:
            ffmpeg.stdin.close()
        if output and output.stdin:
            output.stdin.close()
        drain = asyncio.create_task(ffmpeg.stdout.read()) if ffmpeg.stdout else None
        await asyncio.gather(terminate(output), terminate(ffmpeg), return_exceptions=True)
        if drain:
            await asyncio.gather(drain, return_exceptions=True)
        for writer in (ffmpeg.stdin, output.stdin if output else None):
            if writer:
                with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                    await writer.wait_closed()


async def connected_call(allowed_uin, bridge_token, panel_token, pulse_env, bot_url):
    # 不接受其他主机的 AV 控制服务；调用者身份以受鉴权的桥状态为准。
    parsed = urlsplit(bot_url)
    if parsed.scheme != 'ws' or not parsed.hostname or parsed.path != '/call/ws':
        raise ValueError('SABER_QQ_CALL_BOT_WS 必须是内网 ws://地址/call/ws')
    origin = 'http://' + parsed.netloc
    capture = None
    playback = None
    async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
      async with websockets.connect(bot_url, origin=origin, max_size=6_000_000) as ws:
        await ws.send(json.dumps({'token': panel_token, 'caller_uin': allowed_uin}))
        if json.loads(await asyncio.wait_for(ws.recv(), 10)).get('type') != 'ready':
            raise RuntimeError('Saber 通话服务拒绝连接')
        capture = await asyncio.create_subprocess_exec('parec', '--raw', '--format=s16le', '--rate=16000', '--channels=1',
            '--device=maibot_qq_speaker.monitor', stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, env=pulse_env)
        detector = VoiceDetector()
        active_turn = 0
        suppressed_turn = None
        audio_queue = asyncio.Queue(maxsize=12)
        capture_generation = 0
        validation_tasks = set()
        validation_lock = asyncio.Semaphore(1)
        async def validate_and_send(pcm, generation):
            nonlocal active_turn
            try:
                async with validation_lock:
                    if generation != capture_generation:
                        return
                    started_at = time.monotonic()
                    text = await recognize_audio(client, pcm, os.environ.get('SABER_QQ_CALL_ASR_URL',
                                                   'http://host.docker.internal:9881/transcribe'))
                    if generation != capture_generation or not text:
                        return
                    LOG.info('语音识别完成：%.2f 秒', time.monotonic()-started_at)
                    active_turn += 1
                    await ws.send(json.dumps({'type':'interrupt'}))
                    await ws.send(json.dumps({'type':'recognized','id':active_turn,'text':text.strip()}, ensure_ascii=False))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOG.warning('语音识别未完成：%s', type(exc).__name__)
        async def read_audio():
            nonlocal playback, capture_generation, suppressed_turn
            while True:
                frame = await capture.stdout.readexactly(FRAME_BYTES)
                started, pcm = detector.push(frame)
                if started:
                    capture_generation += 1
                    # 用户在句间开口也要立即屏蔽旧回复，避免下一段继续播放。
                    interrupt = active_turn and suppressed_turn != active_turn
                    if interrupt:
                        suppressed_turn = active_turn
                    if playback and not playback.done():
                        started_at = time.monotonic()
                        playback.cancel()
                        await asyncio.gather(playback, return_exceptions=True)
                        LOG.info('播放停止耗时：%.3f 秒', time.monotonic()-started_at)
                    if interrupt:
                        await ws.send(json.dumps({'type':'interrupt'}))
                        LOG.info('检测到插话，已请求停止上一轮')
                if pcm:
                    task = asyncio.create_task(validate_and_send(pcm, capture_generation))
                    validation_tasks.add(task)
                    task.add_done_callback(validation_tasks.discard)
        async def play_queue():
            nonlocal playback
            while True:
                turn_id, wav = await audio_queue.get()
                try:
                    if turn_id == active_turn and turn_id != suppressed_turn:
                        playback = asyncio.create_task(play(wav, pulse_env))
                        await asyncio.gather(playback, return_exceptions=True)
                        playback = None
                finally:
                    audio_queue.task_done()
        async def listen_reply():
            pending = None
            async for message in ws:
                if isinstance(message, bytes):
                    if pending is not None:
                        if pending == active_turn and pending != suppressed_turn:
                            await audio_queue.put((pending, message))
                        pending = None
                else:
                    event = json.loads(message)
                    if event.get('type') == 'audio_chunk': pending = event.get('id')
                    elif event.get('type') == 'error': LOG.warning('通话处理失败')
        async def monitor():
            while True:
                status = await bridge_status(client, bridge_token)
                if status.get('phase') != 'connected' or str(status.get('callerUin') or '') != allowed_uin:
                    return
                await asyncio.sleep(.5)
        tasks = [asyncio.create_task(read_audio()), asyncio.create_task(listen_reply()), asyncio.create_task(play_queue()), asyncio.create_task(monitor())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            for task in tasks: task.cancel()
            for task in validation_tasks: task.cancel()
            if playback: playback.cancel()
            await asyncio.gather(*tasks, *validation_tasks, *([playback] if playback else []), return_exceptions=True)
            await terminate(capture)


async def main():
    allowed = os.environ.get('SABER_QQ_CALL_ALLOWED_UIN', '')
    if not allowed.isascii() or not allowed.isdigit() or not 5 <= len(allowed) <= 15 or allowed[0] == '0':
        raise ValueError('必须明确设置 SABER_QQ_CALL_ALLOWED_UIN')
    bridge_token = read_secret('SABER_QQ_CALL_BRIDGE_TOKEN_FILE')
    panel_token = read_secret('SABER_QQ_CALL_PANEL_TOKEN_FILE')
    pulse_env = dict(os.environ)
    if not pulse_env.get('PULSE_SERVER', '').startswith('unix:'):
        raise ValueError('必须使用隔离的 PulseAudio Unix socket')
    bot_url = os.environ.get('SABER_QQ_CALL_BOT_WS', 'ws://bot:8080/call/ws')
    ready_file = Path(os.environ.get('SABER_QQ_CALL_READY_FILE', '/tmp/call/runtime/worker-ready'))
    async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
        last_invite = None
        last_error_kind = None
        last_error_at = 0.0
        while True:
            try:
                status = await bridge_status(client, bridge_token)
                headers = {'Authorization': 'Bearer ' + bridge_token}
                bridge = await client.get('http://127.0.0.1:6110/v1/status', headers=headers)
                bridge.raise_for_status()
                native = await client.get('http://127.0.0.1:6111/v1/status', headers=headers)
                native.raise_for_status()
                b = bridge.json()['data']; n = native.json()['data']
                if not components_ready(b, n):
                    raise RuntimeError('通话模块尚未确认初始化')
                for url in ('http://bot:8080/call/', 'http://host.docker.internal:9881/health', 'http://host.docker.internal:9880/health'):
                    response = await client.get(url)
                    response.raise_for_status()
                ready_file.touch()
                last_error_kind = None
                invite = status.get('inviteAt')
                if (status.get('phase') == 'connected' and str(status.get('callerUin') or '') == allowed
                        and invite and invite != last_invite):
                    last_invite = invite
                    LOG.info('授权的通话已接通')
                    await connected_call(allowed, bridge_token, panel_token, pulse_env, bot_url)
                    LOG.info('通话已结束')
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                with contextlib.suppress(FileNotFoundError): ready_file.unlink()
                kind = type(exc).__name__
                now = time.monotonic()
                if kind != last_error_kind or now - last_error_at >= 60:
                    LOG.warning('桥接不可用：%s', kind)
                    last_error_kind, last_error_at = kind, now
            await asyncio.sleep(1)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='[qq-call] %(message)s')
    asyncio.run(main())
