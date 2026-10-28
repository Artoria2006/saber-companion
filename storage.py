"""SQLite 持久化：聊天、显式记忆与主动聊天授权。"""

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, path, max_sessions=1000):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_sessions = max_sessions
        with self.db() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions (
                    key TEXT PRIMARY KEY, bot_id TEXT NOT NULL, user_id INTEGER NOT NULL,
                    group_id INTEGER, persona TEXT NOT NULL, history TEXT NOT NULL DEFAULT '[]',
                    last_user REAL NOT NULL, last_processed REAL NOT NULL DEFAULT 0,
                    proactive INTEGER NOT NULL DEFAULT 0, last_attempt REAL NOT NULL DEFAULT 0,
                    attempt_day TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL,
                    content TEXT NOT NULL, created REAL NOT NULL,
                    UNIQUE(owner, content)
                );
                CREATE TABLE IF NOT EXISTS pages (
                    owner TEXT NOT NULL, url TEXT NOT NULL, digest TEXT NOT NULL,
                    PRIMARY KEY(owner, url)
                );
                CREATE TABLE IF NOT EXISTS activities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, session_key TEXT NOT NULL,
                    created REAL NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,
                    summary TEXT NOT NULL, detail TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS activity_session ON activities(session_key,id);
                CREATE TABLE IF NOT EXISTS preferences (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
            """)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def get(self, key):
        with self.db() as db:
            row = db.execute("SELECT * FROM sessions WHERE key=?", (key,)).fetchone()
        if row is None:
            return None
        state = dict(row)
        state["history"] = json.loads(state["history"])
        return state

    def touch(self, key, bot_id, user_id, group_id, persona):
        now = time.time()
        with self.db() as db:
            existing = db.execute("SELECT 1 FROM sessions WHERE key=?", (key,)).fetchone()
            if not existing:
                count = db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
                if count >= self.max_sessions:
                    raise ValueError("会话数量已达上限；不会自动删除已有长期记忆")
                db.execute(
                    "INSERT INTO sessions(key,bot_id,user_id,group_id,persona,last_user) VALUES(?,?,?,?,?,?)",
                    (key, str(bot_id), user_id, group_id, persona, now),
                )
            else:
                db.execute("UPDATE sessions SET last_user=? WHERE key=?", (now, key))
        return now

    def save_history(self, key, history, persona, limit):
        with self.db() as db:
            db.execute("UPDATE sessions SET history=?,persona=? WHERE key=?",
                       (json.dumps(history[-limit:], ensure_ascii=False), persona, key))

    def processed(self, key):
        with self.db() as db:
            db.execute("UPDATE sessions SET last_processed=? WHERE key=?", (time.time(), key))

    def memories(self, owner):
        with self.db() as db:
            return [dict(r) for r in db.execute(
                "SELECT id,content FROM memories WHERE owner=? ORDER BY id", (owner,))]

    def remember(self, owner, content, limit):
        with self.db() as db:
            if db.execute("SELECT 1 FROM memories WHERE owner=? AND content=?", (owner, content)).fetchone():
                return
            if db.execute("SELECT COUNT(*) FROM memories WHERE owner=?", (owner,)).fetchone()[0] >= limit:
                raise ValueError("记忆数量已达上限，请先使用 /忘记 编号")
            db.execute("INSERT INTO memories(owner,content,created) VALUES(?,?,?)",
                       (owner, content, time.time()))

    def forget(self, owner, memory_id=None):
        with self.db() as db:
            if memory_id is None:
                return db.execute("DELETE FROM memories WHERE owner=?", (owner,)).rowcount
            return db.execute("DELETE FROM memories WHERE owner=? AND id=?", (owner, memory_id)).rowcount

    def opt_in(self, key, enabled):
        with self.db() as db:
            db.execute("UPDATE sessions SET proactive=?,last_attempt=? WHERE key=?",
                       (int(enabled), time.time(), key))

    def candidates(self):
        with self.db() as db:
            return [dict(r) for r in db.execute(
                "SELECT * FROM sessions WHERE proactive=1 AND group_id IS NULL ORDER BY last_attempt")]

    def reserve_attempt(self, key, day, expected_last_user, daily_limit, count=True):
        # 在模型请求之前持久化名额；即使请求失败或决定不打扰，也计入调用上限。
        # 手动测试 count=False 时只更新时间戳，不占用每日名额。
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM sessions WHERE key=?", (key,)).fetchone()
            if not row or not row["proactive"] or row["last_user"] != expected_last_user:
                return False
            attempts = row["attempts"] if row["attempt_day"] == day else 0
            if count and attempts >= daily_limit:
                return False
            if count:
                db.execute("UPDATE sessions SET attempts=?,attempt_day=?,last_attempt=? WHERE key=?",
                           (attempts + 1, day, time.time(), key))
            else:
                db.execute("UPDATE sessions SET last_attempt=? WHERE key=?", (time.time(), key))
        return True

    def page_changed(self, owner, url, digest):
        with self.db() as db:
            previous = db.execute("SELECT digest FROM pages WHERE owner=? AND url=?", (owner, url)).fetchone()
            db.execute("INSERT INTO pages(owner,url,digest) VALUES(?,?,?) ON CONFLICT(owner,url) DO UPDATE SET digest=excluded.digest",
                       (owner, url, digest))
        return previous is None or previous["digest"] != digest

    def sessions(self):
        with self.db() as db:
            rows = db.execute("SELECT key FROM sessions ORDER BY last_user DESC LIMIT 1000").fetchall()
        return [self.get(row["key"]) for row in rows]

    def preference(self, key, default=None):
        with self.db() as db:
            row = db.execute("SELECT value FROM preferences WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set_preference(self, key, value):
        with self.db() as db:
            db.execute("INSERT INTO preferences(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (key, json.dumps(value, ensure_ascii=False)))

    def activity(self, session_key, kind, status, summary, detail=None, limit=1000):
        with self.db() as db:
            cursor = db.execute("INSERT INTO activities(session_key,created,kind,status,summary,detail) VALUES(?,?,?,?,?,?)",
                                (session_key, time.time(), kind, status, summary, json.dumps(detail or {}, ensure_ascii=False)))
            db.execute("DELETE FROM activities WHERE id NOT IN (SELECT id FROM activities ORDER BY id DESC LIMIT ?)", (limit,))
            return cursor.lastrowid

    def activities(self, session_key=None, before=0, limit=60, include_global=False):
        clauses, args = [], []
        if session_key:
            clauses.append("(session_key=? OR session_key='')" if include_global else "session_key=?")
            args.append(session_key)
        if before:
            clauses.append("id<?")
            args.append(before)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.db() as db:
            rows = db.execute("SELECT * FROM activities" + where + " ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall()
        return [dict(row, detail=json.loads(row["detail"])) for row in rows]
