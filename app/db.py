"""SQLite data layer.

Everything runs on the event-loop thread (async endpoints + bot handlers), so a
single shared connection is fine at community scale.
"""
import sqlite3

from .config import settings

KINDS = ("idea", "bug")
STATUSES = ("open", "planned", "in_progress", "completed", "declined")
PRIORITIES = ("unsorted", "low", "medium", "high", "critical")

_conn: sqlite3.Connection | None = None


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(settings.db_path, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA foreign_keys = ON")
        _conn.execute("PRAGMA journal_mode = WAL")
    return _conn


def init_db() -> None:
    conn = get_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS submissions (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            kind           TEXT NOT NULL CHECK (kind IN ('idea','bug')),
            title          TEXT NOT NULL,
            description    TEXT NOT NULL DEFAULT '',
            status         TEXT NOT NULL DEFAULT 'open',
            priority       TEXT NOT NULL DEFAULT 'unsorted',
            submitter_id   INTEGER NOT NULL,
            submitter_name TEXT NOT NULL,
            created_at     TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS attachments (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
            filename      TEXT NOT NULL,
            original_name TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS votes (
            submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
            user_id       INTEGER NOT NULL,
            PRIMARY KEY (submission_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS kv (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    conn.commit()


def get_kv(key: str) -> str | None:
    row = get_conn().execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def delete_kv(key: str) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM kv WHERE key = ?", (key,))
    conn.commit()


def set_kv(key: str, value: str) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO kv (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


_LIST_SQL = """
SELECT s.*,
       (SELECT COUNT(*) FROM votes v WHERE v.submission_id = s.id)            AS votes,
       EXISTS(SELECT 1 FROM votes v
              WHERE v.submission_id = s.id AND v.user_id = :uid)              AS my_vote,
       (SELECT COUNT(*) FROM attachments a WHERE a.submission_id = s.id)      AS attachment_count
FROM submissions s
"""


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    if "my_vote" in d:
        d["my_vote"] = bool(d["my_vote"])
    return d


def list_submissions(user_id: int) -> list[dict]:
    rows = get_conn().execute(_LIST_SQL + " ORDER BY s.created_at DESC", {"uid": user_id}).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_submission(sid: int, user_id: int) -> dict | None:
    row = get_conn().execute(_LIST_SQL + " WHERE s.id = :sid", {"uid": user_id, "sid": sid}).fetchone()
    if row is None:
        return None
    d = _row_to_dict(row)
    atts = get_conn().execute(
        "SELECT filename, original_name FROM attachments WHERE submission_id = ? ORDER BY id",
        (sid,),
    ).fetchall()
    d["attachments"] = [dict(a) for a in atts]
    return d


def create_submission(kind: str, title: str, description: str, submitter_id: int, submitter_name: str) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO submissions (kind, title, description, submitter_id, submitter_name) VALUES (?,?,?,?,?)",
        (kind, title, description, submitter_id, submitter_name),
    )
    conn.commit()
    return cur.lastrowid


def add_attachment(sid: int, filename: str, original_name: str) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO attachments (submission_id, filename, original_name) VALUES (?,?,?)",
        (sid, filename, original_name),
    )
    conn.commit()


def toggle_vote(sid: int, user_id: int) -> tuple[int, bool]:
    conn = get_conn()
    existing = conn.execute(
        "SELECT 1 FROM votes WHERE submission_id = ? AND user_id = ?", (sid, user_id)
    ).fetchone()
    if existing:
        conn.execute("DELETE FROM votes WHERE submission_id = ? AND user_id = ?", (sid, user_id))
        my_vote = False
    else:
        conn.execute("INSERT INTO votes (submission_id, user_id) VALUES (?,?)", (sid, user_id))
        my_vote = True
    conn.commit()
    votes = conn.execute("SELECT COUNT(*) FROM votes WHERE submission_id = ?", (sid,)).fetchone()[0]
    return votes, my_vote


def delete_submission(sid: int) -> list[str]:
    """Delete a submission (votes and attachment rows cascade).

    Returns the stored attachment filenames so the caller can remove the
    files from disk.
    """
    conn = get_conn()
    files = [
        r["filename"]
        for r in conn.execute("SELECT filename FROM attachments WHERE submission_id = ?", (sid,))
    ]
    conn.execute("DELETE FROM submissions WHERE id = ?", (sid,))
    conn.commit()
    return files


def update_submission(sid: int, status: str | None, priority: str | None) -> None:
    sets, params = [], []
    if status is not None:
        sets.append("status = ?")
        params.append(status)
    if priority is not None:
        sets.append("priority = ?")
        params.append(priority)
    if not sets:
        return
    sets.append("updated_at = datetime('now')")
    params.append(sid)
    conn = get_conn()
    conn.execute(f"UPDATE submissions SET {', '.join(sets)} WHERE id = ?", params)
    conn.commit()
