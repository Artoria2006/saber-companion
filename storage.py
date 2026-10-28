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
        self.mood_baseline = 65
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
                CREATE TABLE IF NOT EXISTS companion_state (
                    owner TEXT PRIMARY KEY, session_key TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '', summary_cursor INTEGER NOT NULL DEFAULT 0,
                    summary_version INTEGER NOT NULL DEFAULT 0, summary_at REAL NOT NULL DEFAULT 0,
                    summary_retry_at REAL NOT NULL DEFAULT 0,
                    mood REAL NOT NULL, mood_at REAL NOT NULL, mood_event TEXT NOT NULL DEFAULT '初始状态'
                );
                CREATE TABLE IF NOT EXISTS dialogue_archive (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL,
                    user_text TEXT NOT NULL, assistant_text TEXT NOT NULL, created REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS dialogue_owner ON dialogue_archive(owner,id);
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
            if not history:
                # 版本递增使清空之前已经开始的摘要请求失效，防止旧内容重新出现。
                db.execute("DELETE FROM dialogue_archive WHERE owner IN (SELECT owner FROM companion_state WHERE session_key=?)",(key,))
                db.execute("UPDATE companion_state SET summary='',summary_cursor=0,summary_version=summary_version+1,summary_at=0,summary_retry_at=0,mood=?,mood_at=?,mood_event='会话重置' WHERE session_key=?",(self.mood_baseline,time.time(),key))

    def ensure_companion(self, owner, session_key, history, baseline):
        with self.db() as db:
            inserted=db.execute("INSERT OR IGNORE INTO companion_state(owner,session_key,mood,mood_at) VALUES(?,?,?,?)",
                                (owner,session_key,baseline,time.time())).rowcount
            if inserted:
                # 升级只导入现存的完整问答对，不伪造已经被旧版裁掉的历史。
                for i in range(0,len(history)-1,2):
                    if history[i].get('role')=='user' and history[i+1].get('role')=='assistant':
                        db.execute("INSERT INTO dialogue_archive(owner,user_text,assistant_text,created) VALUES(?,?,?,?)",
                                   (owner,history[i]['content'],history[i+1]['content'],time.time()))

    def companion(self, owner):
        with self.db() as db:
            row=db.execute("SELECT * FROM companion_state WHERE owner=?",(owner,)).fetchone()
            if row is None:return None
            value=dict(row)
            value['pending_turns']=db.execute("SELECT COUNT(*) FROM dialogue_archive WHERE owner=? AND id>?",(owner,row['summary_cursor'])).fetchone()[0]
            value['archive_turns']=db.execute("SELECT COUNT(*) FROM dialogue_archive WHERE owner=?",(owner,)).fetchone()[0]
            return value

    def append_dialogue(self, owner, user_text, assistant_text):
        with self.db() as db:
            db.execute("INSERT INTO dialogue_archive(owner,user_text,assistant_text,created) VALUES(?,?,?,?)",
                       (owner,user_text,assistant_text,time.time()))

    def pending_dialogue(self, owner, limit=1000):
        with self.db() as db:
            rows=db.execute("SELECT id,user_text,assistant_text FROM dialogue_archive WHERE owner=? AND id>(SELECT summary_cursor FROM companion_state WHERE owner=?) ORDER BY id LIMIT ?",(owner,owner,limit)).fetchall()
            return [dict(row) for row in rows]

    def recent_dialogue(self, owner, limit):
        with self.db() as db:
            rows=db.execute("SELECT user_text,assistant_text FROM dialogue_archive WHERE owner=? AND id>(SELECT summary_cursor FROM companion_state WHERE owner=?) ORDER BY id DESC LIMIT ?",(owner,owner,limit)).fetchall()
            return [dict(row) for row in reversed(rows)]

    def summary_candidates(self, trigger_turns):
        with self.db() as db:
            return [dict(row) for row in db.execute("""SELECT c.* FROM companion_state c JOIN dialogue_archive d ON c.owner=d.owner
                WHERE d.id>c.summary_cursor AND c.summary_retry_at<=? GROUP BY c.owner HAVING COUNT(d.id)>=?
                ORDER BY c.summary_at LIMIT 10""",(time.time(),trigger_turns))]

    def finish_summary(self, owner, version, cursor, summary, retain):
        with self.db() as db:
            changed=db.execute("UPDATE companion_state SET summary=?,summary_cursor=?,summary_version=summary_version+1,summary_at=?,summary_retry_at=0 WHERE owner=? AND summary_version=?",
                               (summary,cursor,time.time(),owner,version)).rowcount
            if not changed:return False
            # 只清理已经成功纳入摘要且超出归档保留量的原文；失败的待整理原文不会删除。
            db.execute("DELETE FROM dialogue_archive WHERE owner=? AND id<=? AND id NOT IN (SELECT id FROM dialogue_archive WHERE owner=? ORDER BY id DESC LIMIT ?)",(owner,cursor,owner,retain))
            return True

    def summary_failed(self, owner, version, retry_seconds):
        with self.db() as db:
            db.execute("UPDATE companion_state SET summary_retry_at=? WHERE owner=? AND summary_version=?",(time.time()+retry_seconds,owner,version))

    def clear_summary(self, owner, keep_turns):
        with self.db() as db:
            db.execute("UPDATE companion_state SET summary='',summary_cursor=0,summary_version=summary_version+1,summary_at=0,summary_retry_at=0 WHERE owner=?",(owner,))
            db.execute("DELETE FROM dialogue_archive WHERE owner=? AND id NOT IN (SELECT id FROM dialogue_archive WHERE owner=? ORDER BY id DESC LIMIT ?)",(owner,owner,keep_turns))

    def update_mood(self, owner, baseline, recovery_per_hour, delta=0, event='平常交流', now=None):
        now=time.time() if now is None else now
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT mood,mood_at,mood_event FROM companion_state WHERE owner=?',(owner,)).fetchone()
            if row is None:return None
            recovery=max(0,now-row['mood_at'])/3600*recovery_per_hour
            score=row['mood']
            score=min(baseline,score+recovery) if score<baseline else max(baseline,score-recovery)
            score=max(0,min(100,score+delta))
            reason=event if delta else row['mood_event']
            db.execute('UPDATE companion_state SET mood=?,mood_at=?,mood_event=? WHERE owner=?',(score,now,reason,owner))
            return score

    def reset_mood(self, owner, baseline):
        with self.db() as db:
            db.execute("UPDATE companion_state SET mood=?,mood_at=?,mood_event='手动恢复平静' WHERE owner=?",(baseline,time.time(),owner))

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
