"""仅供已授权伴侣使用的网页语音通话。"""
import asyncio
import hmac
import logging
import os
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from recognition import RecognitionError, validate_wav

ROOT = Path(__file__).resolve().parent
log = logging.getLogger("saber.call")


def split_call_speech(text, limit=24):
    """优先在标点处分段，避免改变文字和声线。"""
    chunks = []
    rest = text.strip()
    while len(rest) > limit:
        candidates = [m.end() for m in re.finditer(r'[，。！？；、,.!?;]', rest[:limit]) if m.end() >= 5]
        cut = candidates[-1] if candidates else limit
        chunks.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    if rest:
        chunks.append(rest)
    return chunks


def install_call(app, engine, config):
    from chat import answer, message_payload, message_emotion
    token = config['dashboard']['access_token'] or config['napcat']['webui_token']
    token_path = os.environ.get('SABER_QQ_CALL_TOKEN_FILE')
    bridge_token = Path(token_path).read_text(encoding='utf-8').strip() if token_path else ''
    if token_path and len(bridge_token) < 32:
        raise ValueError('QQ 通话专用口令必须至少 32 字符')
    active = set()

    @app.get('/call/')
    async def page():
        return FileResponse(ROOT / 'web' / 'call.html', headers={'Cache-Control': 'no-store'})

    @app.get('/call/app.js')
    async def script():
        return FileResponse(ROOT / 'web' / 'call.js', media_type='application/javascript', headers={'Cache-Control': 'no-store'})

    @app.websocket('/call/ws')
    async def call(ws: WebSocket):
        origin = ws.headers.get('origin', '')
        if not origin or urlsplit(origin).netloc != ws.headers.get('host'):
            await ws.close(code=1008)
            return
        await ws.accept()
        task = None
        key = None
        try:
            try:
                auth = await asyncio.wait_for(ws.receive_json(), 10)
            except (asyncio.TimeoutError, ValueError):
                await ws.close(code=1008)
                return
            supplied = auth.get('token', '') if isinstance(auth, dict) else ''
            panel_auth = isinstance(supplied, str) and supplied.isascii() and hmac.compare_digest(supplied, token)
            bridge_auth = isinstance(supplied, str) and supplied.isascii() and bool(bridge_token and hmac.compare_digest(supplied, bridge_token))
            if not panel_auth and not bridge_auth:
                await ws.send_json({'type': 'error', 'message': '口令不正确，请检查管理口令。'})
                await ws.close(code=1008)
                return
            companion = engine.store.preference('companion_qq', config['chat'].get('companion_qq', 0))
            if bridge_auth and not panel_auth and str(auth.get('caller_uin', '')) != str(companion):
                await ws.send_json({'type': 'error', 'message': '来电者与当前绑定的伴侣账号不一致。'})
                await ws.close(code=1008)
                return
            matches = [s for s in engine.store.sessions() if s['group_id'] is None and companion and s['user_id'] == companion]
            if not matches:
                await ws.send_json({'type': 'error', 'message': '请先在管理面板将你的 QQ 私聊设为伴侣账号。'})
                await ws.close(code=1008)
                return
            state = max(matches, key=lambda s: s['last_user'])
            key = state['key']
            if key in active:
                await ws.send_json({'type': 'error', 'message': '已有一个通话正在进行，请先挂断。'})
                await ws.close(code=1008)
                key = None
                return
            active.add(key)
            await ws.send_json({'type': 'ready'})

            next_turn_id = None

            async def turn(data, turn_id):
                entry = None
                try:
                    await ws.send_json({'id': turn_id, 'type': 'phase', 'message': '正在听你说话…'})
                    if isinstance(data, str):
                        text = data
                    else:
                        validate_wav(data, min(config['asr']['max_bytes'], 1500000), min(config['asr']['max_seconds'], 20))
                        text, _ = await engine.recognition.transcribe_wav(data)
                    await ws.send_json({'id': turn_id, 'type': 'transcript', 'text': text})
                    entry = engine.locks.setdefault(key, [asyncio.Lock(), 0])
                    entry[1] += 1
                    async with entry[0]:
                        state = engine.store.get(key)
                        if not state:
                            raise ValueError('会话不存在')
                        engine.store.touch(key, state['bot_id'], state['user_id'], None, state['persona'])
                        state = engine.continuity.context(engine.effective_state(state), text)
                        state['telephone_call'] = True
                        recent_state = dict(state)
                        recent_state['history'] = state['history'][-8:]
                        owner = f"{key}:member:{state['user_id']}"
                        await ws.send_json({'id': turn_id, 'type': 'phase', 'message': 'Saber 正在想怎么回答…'})
                        if bridge_auth and not panel_auth:
                            async def speak_fragment(part, number):
                                started = time.monotonic()
                                audio = await engine.speech.synthesize(part, auto_emotion=True)
                                log.warning('[call] tts_chunk index=%s seconds=%.2f', number, time.monotonic()-started)
                                await ws.send_json({'id': turn_id, 'type': 'audio_chunk', 'index': number})
                                await ws.send_bytes(audio)
                            raw, messages = await answer(recent_state, '[QQ语音转写，可能有误]\n' + text,
                                                         engine.store.memories(owner), spoken=True, on_fragment=speak_fragment)
                            reply, _, _ = message_payload(raw)
                            reply = reply[:min(config['chat']['max_reply_chars'], config['voice']['max_chars'], 80)]
                            await ws.send_json({'id': turn_id, 'type': 'reply', 'text': reply})
                        else:
                            raw, messages = await answer(state, '[网页语音转写，可能有误]\n' + text, engine.store.memories(owner), spoken=True)
                            reply, _, _ = message_payload(raw)
                            reply = reply[:min(config['chat']['max_reply_chars'], config['voice']['max_chars'], 80)]
                            await ws.send_json({'id': turn_id, 'type': 'phase', 'message': '正在准备声音…'})
                            audio = await engine.speech.synthesize(reply, auto_emotion=True, emotion=message_emotion(raw))
                            await ws.send_json({'id': turn_id, 'type': 'reply', 'text': reply})
                            await ws.send_bytes(audio)
                        engine.continuity.append(state, messages[-1]['content'], reply)
                        engine.store.save_history(key, state['history'] + [messages[-1], {'role': 'assistant', 'content': reply}], state['persona'], config['chat']['history_messages'])
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.warning('[call] turn_failed type=%s', type(exc).__name__)
                    message = str(exc) if isinstance(exc, RecognitionError) else '这次没能接通，请稍后再试；管理员可查看 [call] 日志。'
                    try:
                        await ws.send_json({'id': turn_id, 'type': 'error', 'message': message})
                    except Exception:
                        pass
                finally:
                    if entry is not None:
                        entry[1] -= 1
                        if entry[1] == 0:
                            engine.locks.pop(key, None)

            while True:
                packet = await ws.receive()
                if packet['type'] == 'websocket.disconnect':
                    break
                if packet.get('bytes') is not None:
                    if task and not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                    task = asyncio.create_task(turn(packet['bytes'], next_turn_id))
                    next_turn_id = None
                elif packet.get('text'):
                    import json
                    try:
                        event = json.loads(packet['text'])
                    except ValueError:
                        continue
                    if isinstance(event, dict) and event.get('type') == 'recognized' and bridge_auth:
                        value, turn_id = event.get('text'), event.get('id')
                        if isinstance(value, str) and 1 <= len(value.strip()) <= 3000 and isinstance(turn_id, int) and 0 <= turn_id < 2**53:
                            if task and not task.done():
                                task.cancel()
                                await asyncio.gather(task, return_exceptions=True)
                            task = asyncio.create_task(turn(value.strip(), turn_id))
                    if isinstance(event, dict) and event.get('type') == 'turn_id':
                        value = event.get('id')
                        next_turn_id = value if isinstance(value, int) and 0 <= value < 2**53 else None
                    if isinstance(event, dict) and event.get('type') == 'interrupt' and task and not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                        task = None
        except WebSocketDisconnect:
            pass
        finally:
            if task and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            if key is not None:
                active.discard(key)
