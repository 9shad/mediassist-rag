import json
import sqlite3
import os
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings


def _get_db_path() -> str:
    db_dir = Path(settings.database_path).parent
    os.makedirs(db_dir, exist_ok=True)
    return str(db_dir / "mediassist_chats.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(_get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT 'New Chat',
            role TEXT NOT NULL,
            username TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('user', 'bot')),
            text TEXT NOT NULL DEFAULT '',
            think_text TEXT DEFAULT '',
            sources TEXT DEFAULT '[]',
            retrieval_type TEXT DEFAULT '',
            usage TEXT DEFAULT '{}',
            embedding TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
        CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(username);
    """)
    _migrate(conn)
    conn.commit()
    conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(conversations)")}
    if "summary" not in existing:
        conn.execute("ALTER TABLE conversations ADD COLUMN summary TEXT NOT NULL DEFAULT ''")
    existing_msg = {row["name"] for row in conn.execute("PRAGMA table_info(messages)")}
    if "embedding" not in existing_msg:
        conn.execute("ALTER TABLE messages ADD COLUMN embedding TEXT DEFAULT ''")


# --- Conversations ---

def create_conversation(id: str, title: str, role: str, username: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    conn.execute(
        "INSERT INTO conversations (id, title, role, username, summary, created_at, updated_at) VALUES (?, ?, ?, ?, '', ?, ?)",
        (id, title, role, username, now, now),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM conversations WHERE id = ?", (id,)).fetchone()
    conn.close()
    return dict(row)


def list_conversations(username: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM conversations WHERE username = ? ORDER BY updated_at DESC",
        (username,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_conversation(id: str, username: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM conversations WHERE id = ? AND username = ?",
        (id, username),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_conversation_by_id(id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM conversations WHERE id = ?", (id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_conversation_title(id: str, title: str, username: str) -> dict | None:
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    conn.execute(
        "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ? AND username = ?",
        (title, now, id, username),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM conversations WHERE id = ?", (id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_summary(conversation_id: str, summary: str) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE conversations SET summary = ?, updated_at = ? WHERE id = ?",
        (summary, datetime.now(timezone.utc).isoformat(), conversation_id),
    )
    conn.commit()
    conn.close()


def delete_conversation(id: str, username: str) -> bool:
    conn = get_connection()
    conn.execute("DELETE FROM messages WHERE conversation_id = ?", (id,))
    conn.execute("DELETE FROM conversations WHERE id = ? AND username = ?", (id, username))
    affected = conn.total_changes
    conn.commit()
    conn.close()
    return affected > 0


def delete_old_conversations(days: int) -> int:
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    conn = get_connection()
    old = conn.execute(
        "SELECT id FROM conversations WHERE updated_at < ?", (cutoff,)
    ).fetchall()
    ids = [r["id"] for r in old]
    if ids:
        placeholders = ",".join("?" for _ in ids)
        conn.execute(f"DELETE FROM messages WHERE conversation_id IN ({placeholders})", ids)
        conn.execute(f"DELETE FROM conversations WHERE id IN ({placeholders})", ids)
    conn.commit()
    conn.close()
    return len(ids)


# --- Messages ---

def add_message(
    id: str,
    conversation_id: str,
    type: str,
    text: str,
    think_text: str = "",
    sources: list | None = None,
    retrieval_type: str = "",
    usage: dict | None = None,
    embedding: str = "",
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    conn.execute(
        "UPDATE conversations SET updated_at = ? WHERE id = ?",
        (now, conversation_id),
    )
    conn.execute(
        "INSERT INTO messages (id, conversation_id, type, text, think_text, sources, retrieval_type, usage, embedding, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (id, conversation_id, type, text, think_text, json.dumps(sources or []), retrieval_type, json.dumps(usage or {}), embedding, now),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM messages WHERE id = ?", (id,)).fetchone()
    conn.close()
    return dict(row)


def get_messages(conversation_id: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
        (conversation_id,),
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["sources"] = json.loads(d["sources"])
        d["usage"] = json.loads(d["usage"])
        result.append(d)
    return result


def delete_message(conversation_id: str, message_id: str) -> bool:
    conn = get_connection()
    conn.execute(
        "DELETE FROM messages WHERE id = ? AND conversation_id = ?",
        (message_id, conversation_id),
    )
    affected = conn.total_changes
    conn.commit()
    conn.close()
    return affected > 0


# Initialize on import
init_db()
