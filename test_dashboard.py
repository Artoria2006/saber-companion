"""管理面板、日记、图片传输与调度边界的离线回归测试。"""
import base64
import copy
import io
import json
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from test_chat import chat
from dashboard import install_dashboard, schedule
from storage import Store
from stickers import StickerLibrary


def png_bytes():
    output = io.BytesIO()
    Image.new("RGB", (24, 24), "pink").save(output, format="PNG")
    return output.getvalue()


class PanelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "assistant.sqlite3")
        self.engine = chat.Engine(self.store)
        self.config = copy.deepcopy(chat.C)
        self.config["dashboard"]["access_token"] = "panel-test-key-1234567890123456789"
        self.config["stickers"] = dict(chat.ST, builtin_dir="assets", upload_dir="data/stickers")
        assets = self.root / "assets"
        assets.mkdir()
        (assets / "hug.png").write_bytes(png_bytes())
        (assets / "index.json").write_text(json.dumps([{"id":"hug","label":"抱抱","file":"hug.png"}]), encoding="utf-8")
        self.engine.library = StickerLibrary(self.root, self.config["stickers"])
        self.store.touch("100:u:300", "100", 300, None, "saber")
        self.store.touch("100:u:301", "100", 301, None, "saber")
        self.store.touch("100:g:200", "100", 300, 200, "saber")
        app = FastAPI()
        install_dashboard(app, self.engine, self.config, chat.quiet, chat.CHINA)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.headers = {"Authorization": "Bearer " + self.config["dashboard"]["access_token"]}

    def get(self, path):
        return self.client.get("/panel/api" + path, headers=self.headers)

    def post(self, path, payload):
        return self.client.post("/panel/api" + path, headers=self.headers, json=payload)

    def test_requires_auth_and_rejects_cross_origin_writes(self):
        self.assertEqual(self.client.get("/panel/api/status").status_code, 401)
        self.assertEqual(self.client.get("/panel/").status_code, 200)
        self.assertEqual(self.client.get("/panel/").headers["x-frame-options"], "DENY")
        response = self.client.post("/panel/api/control", headers=self.headers | {"Origin":"https://other.example"}, json={"action":"pause","paused":True})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.store.preference("paused", False))

    def test_status_never_returns_config_secrets(self):
        response = self.get("/status")
        self.assertEqual(response.status_code, 200)
        for secret in (self.config["model"]["api_key"], self.config["napcat"]["webui_token"], self.config["dashboard"]["access_token"]):
            self.assertNotIn(secret, response.text)
        self.assertEqual(len(response.json()["sessions"]), 3)
        self.assertIn("next_check_at", response.json())

    def test_preferences_persist_and_can_bind_private_companion(self):
        response = self.post("/control", {"action":"settings","session":"100:u:300","idle_minutes":15,"max_daily_attempts":8,"proactive":True,"stickers_enabled":False})
        self.assertEqual(response.status_code, 200)
        restarted = Store(self.store.path)
        self.assertEqual(restarted.preference("session:100:u:300")["idle_minutes"], 15)
        self.assertEqual(restarted.get("100:u:300")["proactive"], 1)
        self.assertEqual(self.post("/control", {"action":"bind_companion","session":"100:u:300"}).status_code, 200)
        self.assertEqual(restarted.preference("companion_qq"), 300)
        self.assertEqual(self.post("/control", {"action":"bind_companion","session":"100:g:200"}).status_code, 400)

    def test_invalid_preferences_do_not_enable_groups_or_accept_bad_values(self):
        for payload in ({"idle_minutes":True}, {"idle_minutes":1}, {"quiet_start_hour":8,"quiet_end_hour":8}, {"persona":[]}):
            response = self.post("/control", {"action":"settings","session":"100:u:300",**payload})
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.post("/control", {"action":"settings","session":"100:g:200","proactive":True}).status_code, 400)
        self.assertEqual(self.post("/control", {"action":"settings","session":[]}).status_code, 400)
        response = self.post("/control", {"action":"settings","session":"100:u:300","proactive":True,"persona":"missing"})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.store.get("100:u:300")["proactive"])

    def test_pause_is_persistent_and_visible(self):
        self.assertEqual(self.post("/control", {"action":"pause","paused":True}).status_code, 200)
        self.assertTrue(self.get("/status").json()["paused"])
        self.assertTrue(Store(self.store.path).preference("paused"))

    def test_diary_redacts_secrets_and_filters_sessions(self):
        self.engine.record("100:u:300", "decision", "done", "想查一件有趣的事", {"query":"茶的香气","explanation":"想顺着昨天的话题聊一会儿","token":chat.M["api_key"]})
        self.engine.record("100:u:301", "reading", "done", "另一个私聊的内容")
        result = self.get("/activities?session=100:u:300").json()["items"]
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["detail"]["token"], "[已隐藏]")
        self.assertEqual(result[0]["detail"]["query"], "茶的香气")
        self.assertEqual(len(Store(self.store.path).activities("100:u:300")), 1)

    def test_diary_retention(self):
        for i in range(5):
            self.store.activity("a", "decision", "done", str(i), limit=3)
        self.assertEqual([x["summary"] for x in self.store.activities()], ["4","3","2"])

    def test_earliest_contact_moves_to_end_of_quiet_window(self):
        now = datetime(2026, 10, 27, 23, 30, tzinfo=chat.CHINA)
        self.store.opt_in("100:u:300", True)
        with self.store.db() as db:
            db.execute("UPDATE sessions SET last_user=?,last_attempt=0 WHERE key=?", (now.timestamp()-7200,"100:u:300"))
        state = self.store.get("100:u:300")
        result = schedule(self.engine, state, now, chat.quiet)
        expected = datetime(2026, 10, 28, 8, tzinfo=chat.CHINA).timestamp()
        self.assertEqual(result["earliest_at"], expected)

    def test_idle_timing_is_stable_and_matches_scheduler(self):
        self.store.opt_in("100:u:300", True)
        self.engine.update_controls("100:u:300", {"idle_minutes":15})
        now = datetime(2026, 10, 27, 12, tzinfo=chat.CHINA)
        with self.store.db() as db:
            db.execute("UPDATE sessions SET last_user=?,last_attempt=0 WHERE key=?", (now.timestamp(),"100:u:300"))
        state = self.store.get("100:u:300")
        due = self.engine.next_contact_at(state)
        self.assertGreaterEqual(due, now.timestamp()+15*60)
        self.assertLessEqual(due, now.timestamp()+20*60)
        self.assertEqual(chat.Engine(Store(self.store.path)).next_contact_at(state), due)
        self.assertEqual(schedule(self.engine, state, now, chat.quiet)["earliest_at"], due)
        self.assertFalse(chat.eligible(state, datetime.fromtimestamp(due-1, chat.CHINA), self.engine.policy(state)))
        self.assertTrue(chat.eligible(state, datetime.fromtimestamp(due, chat.CHINA), self.engine.policy(state)))

    def test_model_delay_varies_without_crossing_idle_floor(self):
        policy = dict(chat.P, idle_minutes=15)
        with patch.object(chat.random, "uniform", return_value=0.8):
            earlier = chat.next_contact_delay(policy, {"next_delay_minutes":30})
            self.assertEqual(chat.next_contact_delay(policy, {"next_delay_minutes":5}), 15*60)
        with patch.object(chat.random, "uniform", return_value=1.2):
            later = chat.next_contact_delay(policy, {"next_delay_minutes":30})
        self.assertEqual(earlier, 24*60)
        self.assertEqual(later, 36*60)

    def test_planner_receives_session_timing_and_remaining_budget(self):
        self.engine.update_controls("100:u:300", {"idle_minutes":15,"max_daily_attempts":8})
        state = self.engine.effective_state(self.store.get("100:u:300"))
        self.assertEqual(state["proactive_timing"]["idle_minutes"], 15)
        self.assertEqual(state["proactive_timing"]["remaining_attempts"], 8)

    def test_memory_editor_does_not_delete_another_session_memory(self):
        self.post("/memories", {"session":"100:u:300","content":"喜欢红茶"})
        row = self.get("/memories?session=100:u:300").json()["items"][0]
        self.post("/memories", {"session":"100:u:301","action":"delete","id":row["id"]})
        self.assertEqual(len(self.get("/memories?session=100:u:300").json()["items"]), 1)

    def test_sticker_upload_and_protected_download(self):
        response = self.post("/stickers", {"label":"摸摸头","image":base64.b64encode(png_bytes()).decode()})
        self.assertEqual(response.status_code, 200)
        sticker_id = response.json()["id"]
        self.assertTrue(sticker_id.startswith("custom_"))
        self.assertEqual(self.client.get("/panel/api/stickers/"+sticker_id).status_code, 401)
        download = self.get("/stickers/"+sticker_id)
        self.assertEqual(download.content, png_bytes())
        self.assertIsNone(self.engine.library.get("../../config.toml"))

    def test_sticker_upload_rejects_non_images_and_oversized_data(self):
        for encoded in ("not-base64", base64.b64encode(b'not an image').decode(), "A"*1500000):
            response = self.post("/stickers", {"label":"x","image":encoded})
            self.assertIn(response.status_code, (400,413))

    def test_manual_sticker_test_only_targets_existing_private_session(self):
        fake = SimpleNamespace(self_id="100")
        with patch.object(chat, "get_bot", return_value=fake):
            response = self.post("/control", {"action":"sticker_test","session":"100:u:300","sticker":"hug"})
            self.assertEqual(response.status_code, 200)
            job = self.engine.queue.get_nowait()
            self.assertEqual(job.user_id, 300)
            self.assertEqual(job.kind, "sticker")
            response = self.post("/control", {"action":"sticker_test","session":"100:g:200","sticker":"hug"})
            self.assertEqual(response.status_code, 400)


class StickerDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_image_segment_and_cooldown(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/"assets").mkdir()
            (root/"assets"/"hug.png").write_bytes(png_bytes())
            (root/"assets"/"index.json").write_text('[{"id":"hug","label":"hug","file":"hug.png"}]')
            engine = chat.Engine(Store(root/"test.sqlite3"))
            engine.library = StickerLibrary(root, dict(chat.ST,builtin_dir="assets",upload_dir="data/stickers"))
            bot = SimpleNamespace(send_private_msg=AsyncMock(return_value={"message_id":1}))
            job = chat.Job("100",300,None,"100:u:300","",time.time())
            with patch.object(chat,"get_bot",return_value=bot),patch.dict(chat.H,send_interval_seconds=0):
                await engine.send(job,"抱抱。","hug")
                message = bot.send_private_msg.call_args.kwargs["message"]
                images = [s for s in message if s.type=="image"]
                self.assertEqual(len(images),1)
                self.assertTrue(images[0].data["file"].startswith("base64://"))
                await engine.send(job,"在这里。","hug")
                message = bot.send_private_msg.call_args.kwargs["message"]
                self.assertFalse(any(s.type=="image" for s in message))
                await engine.send(job,"表情测试。","hug",force_sticker=True)
                self.assertTrue(any(s.type=="image" for s in bot.send_private_msg.call_args.kwargs["message"]))

    async def test_json_response_does_not_leak_metadata_into_chat(self):
        text, source, sticker = chat.message_payload('{"text":"来，抱抱。","sticker":"hug","use_source":false}')
        self.assertEqual(text,"来，抱抱。")
        self.assertEqual(sticker,"hug")
        self.assertFalse(source)
        self.assertEqual(chat.message_payload('{"text":"hi","sticker":"https://example.com/x.png"}')[2],"")


if __name__ == "__main__":
    unittest.main()
