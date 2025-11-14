# app/web/storage.py
import sqlite3
import os
from typing import Dict, Any
from datetime import datetime

DB_PATH = os.getenv("VOICE_DB_PATH", "voice_calls.db")

def _conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

# initialize DB if needed
def init_db():
    conn = _conn()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS call_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        call_id TEXT,
        timestamp TEXT,
        speaker TEXT,
        text TEXT,
        raw_json TEXT,
        created_at TEXT
    )
    """)
    conn.commit()
    conn.close()

# call once at startup
init_db()

async def save_call_event(row: Dict[str, Any]):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("""
      INSERT INTO call_events (call_id, timestamp, speaker, text, raw_json, created_at)
      VALUES (?, ?, ?, ?, ?, ?)
    """, (
        row.get("call_id"),
        row.get("timestamp"),
        row.get("speaker"),
        row.get("text"),
        json_safe(row.get("raw")),
        datetime.utcnow().isoformat()
    ))
    conn.commit()
    conn.close()

def list_events_for_call(call_id: str):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM call_events WHERE call_id = ? ORDER BY id", (call_id,))
    return [dict(r) for r in cur.fetchall()]

def json_safe(v):
    import json
    try:
        return json.dumps(v)
    except Exception:
        return str(v)
