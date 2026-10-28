"""本机管理面板：复用 NoneBot 的 FastAPI 服务，不向前端返回真实配置密钥。"""
import hmac
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from speech import SAMPLE, VOICES

ROOT = Path(__file__).resolve().parent


class RevalidatedStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        response=await super().get_response(path,scope)
        # 更新面板后必须重新校验脚本，防止新卡片配上旧缓存脚本而不刷新。
        response.headers['Cache-Control']='no-cache, must-revalidate'
        return response


def schedule(engine, state, now, quiet):
    policy = engine.policy(state)
    used = state["attempts"] if state["attempt_day"] == now.date().isoformat() else 0
    earliest = engine.next_contact_at(state)
    if used >= policy["max_daily_attempts"]:
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        earliest = max(earliest, tomorrow.timestamp())
    candidate = datetime.fromtimestamp(max(earliest, now.timestamp()), now.tzinfo)
    if quiet(candidate, policy):
        start, end = policy["quiet_start_hour"], policy["quiet_end_hour"]
        next_day = start > end and candidate.hour >= start
        candidate = (candidate + timedelta(days=int(next_day))).replace(hour=end, minute=0, second=0, microsecond=0)
    reason = "等待空闲时间满足"
    if state["group_id"] is not None:
        reason = "群聊只回应消息，不主动联系"
    elif not state["proactive"]:
        reason = "尚未开启主动聊天"
    elif engine.store.preference("paused", False):
        reason = "全部主动任务已暂停"
    elif state["bot_id"] not in engine.online_bots:
        reason = "等待 QQ 连接恢复"
    elif used >= policy["max_daily_attempts"]:
        reason = "今日名额已用完，等待明天"
    elif quiet(now, policy):
        reason = "安静时段，不主动打扰"
    elif state["key"] in engine.current:
        reason = engine.current[state["key"]]["summary"]
    elif state["key"] in engine.proactive_pending:
        reason = "主动任务正在排队"
    elif candidate.timestamp() <= now.timestamp() + 1:
        reason = "条件满足，等待下一次检查"
    return {"earliest_at": candidate.timestamp(), "reason": reason, "used": used,
            "limit": policy["max_daily_attempts"], "idle_minutes": policy["idle_minutes"],
            "quiet_start_hour": policy["quiet_start_hour"], "quiet_end_hour": policy["quiet_end_hour"]}


def install_dashboard(app, engine, config, quiet, tz):
    panel = config["dashboard"]
    if not panel["enabled"]:
        return
    token = panel["access_token"] or config["napcat"]["webui_token"]
    router = APIRouter(prefix="/panel/api")

    async def authenticated(request: Request):
        supplied = request.headers.get("authorization", "")
        if not supplied.startswith("Bearer ") or not hmac.compare_digest(supplied[7:], token):
            raise HTTPException(401, "管理口令不正确或尚未登录")
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host"):
            raise HTTPException(403, "不接受其他网站发起的管理请求")

    async def body(request):
        raw = await request.body()
        if len(raw) > config["stickers"]["max_bytes"] * 4 // 3 + 2048:
            raise HTTPException(413, "请求内容过大")
        try:
            value = __import__('json').loads(raw)
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(400, "请求必须是 JSON 对象") from None

    def checked(key):
        state = engine.store.get(key)
        if not state:
            raise HTTPException(404, "会话不存在，请先在 QQ 给 Saber 发一条消息")
        return state

    @router.get("/status", dependencies=[Depends(authenticated)])
    async def status():
        now = datetime.now(tz)
        sessions = []
        companion = engine.store.preference("companion_qq", config["chat"].get("companion_qq", 0))
        for state in engine.store.sessions():
            prefs = engine.store.preference("session:" + state["key"], {})
            sessions.append({k: state[k] for k in ("key", "bot_id", "user_id", "group_id", "persona", "proactive", "last_user", "last_attempt")} |
                            {"history_count": len(state["history"]), "schedule": schedule(engine, state, now, quiet),
                             "current": engine.current.get(state["key"]), "is_companion": state["user_id"] == companion and state["group_id"] is None,
                             "stickers_enabled": prefs.get("stickers_enabled", True), "voice_enabled": prefs.get("voice_enabled", True)})
        return {"now": now.timestamp(), "timezone": "Asia/Shanghai", "connected": bool(engine.online_bots),
                "paused": engine.store.preference("paused", False), "queue_size": engine.queue.qsize(),
                "queue_limit": config["chat"]["queue_size"], "next_check_at": engine.next_check_at,
                "sessions": sessions, "personas": list(config["personas"]), "model": config["model"]["model"],
                "search_enabled": config["proactive"]["search_enabled"], "max_image_bytes": config["stickers"]["max_bytes"],
                "voice": {k:v for k,v in engine.speech.settings().items() if k != "references"}, "voices": engine.speech.voices()}

    @router.get("/activities", dependencies=[Depends(authenticated)])
    async def activities(session: str = "", before: int = 0):
        return {"items": engine.store.activities(session or None, before=max(0, before), include_global=True)}

    @router.post("/control", dependencies=[Depends(authenticated)])
    async def control(request: Request):
        values = await body(request)
        key = values.get("session", "")
        action = values.get("action")
        if not isinstance(key, str) or len(key) > 100:
            raise HTTPException(400, "会话标识无效")
        try:
            if action == "pause":
                if type(values.get("paused")) is not bool:
                    raise ValueError("暂停状态无效")
                engine.pause(values["paused"])
            elif action == "settings":
                checked(key)
                engine.update_controls(key, values)
            elif action == "bind_companion":
                state = checked(key)
                if state["group_id"] is not None:
                    raise ValueError("只能将私聊账号设为伴侣")
                engine.store.set_preference("companion_qq", state["user_id"])
                engine.record(key, "control", "done", "已将此私聊账号设为伴侣")
            elif action == "voice_settings":
                engine.speech.update(values)
                engine.record("", "control", "done", "已更新中文语音设置")
            elif action in ("test", "sticker_test", "voice_test"):
                checked(key)
                engine.enqueue_manual(key, {"test":"proactive", "sticker_test":"sticker", "voice_test":"voice"}[action], str(values.get("sticker", "hug")))
            else:
                raise ValueError("未知操作")
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, str(exc) if isinstance(exc, ValueError) else "QQ 尚未连接") from None
        return {"ok": True}

    @router.post("/voice/preview", dependencies=[Depends(authenticated)])
    async def voice_preview():
        if time.time() - engine.speech.preview_at < 10:
            raise HTTPException(429, "请等待十秒再试听")
        engine.speech.preview_at = time.time()
        try:
            audio = await engine.speech.synthesize(SAMPLE)
        except Exception as exc:
            engine.record("", "speech", "failed", "管理面板语音试听失败", {"type":type(exc).__name__})
            raise HTTPException(503, "语音合成暂不可用，请检查 voice.enabled、网络与 [voice] 日志") from None
        kind = "audio/wav" if audio[:4]==b"RIFF" else "audio/mpeg"
        return Response(audio, media_type=kind, headers={"Cache-Control":"no-store", "X-Content-Type-Options":"nosniff"})

    @router.get("/memories", dependencies=[Depends(authenticated)])
    async def memories(session: str):
        state = checked(session)
        owner = f"{session}:member:{state['user_id']}"
        return {"items": engine.store.memories(owner), "history": state["history"][-10:]}

    @router.get('/continuity', dependencies=[Depends(authenticated)])
    async def continuity_status(session: str):
        return engine.continuity.view(checked(session))

    @router.post('/continuity', dependencies=[Depends(authenticated)])
    async def continuity_control(request: Request):
        values=await body(request)
        key=values.get('session')
        if not isinstance(key,str) or len(key)>100:raise HTTPException(400,'会话标识无效')
        state=checked(key)
        if state['group_id'] is not None:raise HTTPException(400,'自动摘要与角色状态目前只用于私聊')
        owner=engine.continuity.ensure(state)
        action=values.get('action')
        if action=='clear_summary' and owner and engine.continuity.summary['enabled']:
            engine.store.clear_summary(owner,engine.continuity.summary['keep_recent_messages']//2)
            engine.record(key,'summary','done','管理面板已清空自动摘要及较早归档')
        elif action=='reset_mood' and owner and engine.continuity.mood['enabled']:
            engine.store.reset_mood(owner,engine.continuity.mood['baseline'])
            engine.record(key,'mood','done','管理面板已恢复角色平静状态')
        else:
            raise HTTPException(400,'操作无效或功能未启用')
        return {'ok':True}

    @router.post("/memories", dependencies=[Depends(authenticated)])
    async def update_memory(request: Request):
        values = await body(request)
        key = values.get("session", "")
        state = checked(key)
        if state["group_id"] is not None:
            raise HTTPException(400, "管理面板的记忆编辑仅支持私聊，群记忆请由本人在 QQ 中管理")
        owner = f"{key}:member:{state['user_id']}"
        try:
            if values.get("action") == "delete":
                if type(values.get("id")) is not int:
                    raise ValueError("记忆编号无效")
                engine.store.forget(owner, values["id"])
            else:
                content = values.get("content", "")
                if not isinstance(content, str) or not 1 <= len(content.strip()) <= config["storage"]["max_memory_chars"]:
                    raise ValueError("记忆为空或超过单条长度上限")
                engine.store.remember(owner, content.strip(), config["storage"]["max_memories"])
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        engine.record(key, "memory", "done", "已更新显式记忆")
        return {"ok": True}

    @router.get("/stickers", dependencies=[Depends(authenticated)])
    async def stickers():
        return {"items": [{k: row[k] for k in ("id", "label", "custom")} for row in engine.library.list()]}

    @router.get("/stickers/{sticker_id}", dependencies=[Depends(authenticated)])
    async def sticker_file(sticker_id: str):
        item = engine.library.get(sticker_id)
        if not item:
            raise HTTPException(404, "表情不存在")
        return FileResponse(item["path"], headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    @router.post("/stickers", dependencies=[Depends(authenticated)])
    async def upload(request: Request):
        values = await body(request)
        if not isinstance(values.get("image"), str) or not isinstance(values.get("label", ""), str):
            raise HTTPException(400, "图片和名称格式不正确")
        try:
            sticker_id = engine.library.upload(values.get("label", ""), values["image"])
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        engine.record("", "sticker", "done", "已添加一张自定义表情", {"sticker": sticker_id})
        return {"ok": True, "id": sticker_id}

    app.include_router(router)
    app.mount("/panel/static", RevalidatedStaticFiles(directory=ROOT / "web"), name="saber-panel-static")

    @app.get("/panel/", include_in_schema=False)
    async def index():
        return FileResponse(ROOT / "web" / "index.html", headers={
            "Cache-Control": "no-store", "X-Frame-Options": "DENY", "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'",
        })
