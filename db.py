"""SQLite-хранилище: пользователи, подписки, лимиты, покупки."""
import sqlite3
import time

from config import ROOT, FREE_DAILY, PRO_DAILY, CREATOR_DAILY

DB_PATH = ROOT / "botdata.db"
LIMITS = {"free": FREE_DAILY, "pro": PRO_DAILY, "creator": CREATOR_DAILY}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT DEFAULT '',
    tier TEXT DEFAULT 'free',
    expires_at INTEGER DEFAULT 0,
    gens INTEGER DEFAULT 0,
    gen_day INTEGER DEFAULT 0,
    joined INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS purchases (
    charge_id TEXT PRIMARY KEY,
    tg_id INTEGER,
    username TEXT DEFAULT '',
    tier TEXT,
    stars INTEGER,
    ts INTEGER,
    refunded INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS presence (
    user_id INTEGER PRIMARY KEY,
    ts INTEGER
);
CREATE TABLE IF NOT EXISTS gallery (
    item_id TEXT PRIMARY KEY,
    name TEXT,
    kind TEXT,
    tier TEXT,
    username TEXT DEFAULT '',
    votes INTEGER DEFAULT 0,
    path TEXT,
    ts INTEGER
);
CREATE TABLE IF NOT EXISTS votes_log (
    user_id INTEGER,
    item_id TEXT,
    PRIMARY KEY (user_id, item_id)
);
"""


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init():
    with _conn() as c:
        c.executescript(SCHEMA)


def ensure_user(uid: int, username: str):
    now = int(time.time())
    with _conn() as c:
        c.execute(
            "INSERT INTO users (id, username, joined) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET username = excluded.username",
            (uid, username or "", now),
        )
        c.execute(
            "INSERT INTO presence (user_id, ts) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET ts = excluded.ts",
            (uid, now),
        )


def online_count(window: int = 900) -> int:
    with _conn() as c:
        row = c.execute("SELECT COUNT(*) AS n FROM presence WHERE ts > ?",
                        (int(time.time()) - window,)).fetchone()
    return row["n"] if row else 0


def get_user(uid: int):
    with _conn() as c:
        return c.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()


def effective_tier(row) -> str:
    if row is not None and row["tier"] in ("pro", "creator") and row["expires_at"] > time.time():
        return row["tier"]
    return "free"


def set_sub(uid: int, username: str, tier: str, days: int):
    now = time.time()
    base = now
    row = get_user(uid)
    if row is not None and row["tier"] == tier and row["expires_at"] > now:
        base = row["expires_at"]  # продлеваем действующую подписку того же тарифа
    with _conn() as c:
        c.execute(
            "INSERT INTO users (id, username, tier, expires_at, joined) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET tier = excluded.tier, expires_at = excluded.expires_at, "
            "username = excluded.username",
            (uid, username or "", tier, int(base + days * 86400), int(now)),
        )


def gens_left(uid: int, tier: str) -> int:
    limit = LIMITS[tier]
    row = get_user(uid)
    today = int(time.time() // 86400)
    if row is None or row["gen_day"] != today:
        return limit
    return max(0, limit - row["gens"])


def record_gen(uid: int):
    today = int(time.time() // 86400)
    row = get_user(uid)
    gens = (row["gens"] + 1) if row is not None and row["gen_day"] == today else 1
    with _conn() as c:
        c.execute(
            "INSERT INTO users (id, gens, gen_day) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET gens = excluded.gens, gen_day = excluded.gen_day",
            (uid, gens, today),
        )


def save_purchase(charge_id: str, uid: int, username: str, tier: str, stars: int):
    with _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO purchases (charge_id, tg_id, username, tier, stars, ts) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (charge_id, uid, username or "", tier, stars, int(time.time())),
        )


def find_purchase(charge_id: str):
    with _conn() as c:
        return c.execute("SELECT * FROM purchases WHERE charge_id = ?", (charge_id,)).fetchone()


def mark_refunded(charge_id: str):
    with _conn() as c:
        c.execute("UPDATE purchases SET refunded = 1 WHERE charge_id = ?", (charge_id,))


def purchases(limit: int = 30):
    with _conn() as c:
        return c.execute(
            "SELECT * FROM purchases ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()


def add_gallery_item(item_id: str, name: str, kind: str, tier: str, username: str, path: str):
    with _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO gallery (item_id, name, kind, tier, username, votes, path, ts) "
            "VALUES (?, ?, ?, ?, ?, 0, ?, ?)",
            (item_id, name, kind, tier, username or "", path, int(time.time())),
        )


def top_gallery(limit: int = 20):
    with _conn() as c:
        return c.execute(
            "SELECT * FROM gallery ORDER BY votes DESC, ts DESC LIMIT ?", (limit,)
        ).fetchall()


def vote_item(uid: int, item_id: str) -> bool:
    """Голосует; True если голос засчитан (один голос на пользователя за работу)."""
    with _conn() as c:
        cur = c.execute(
            "INSERT OR IGNORE INTO votes_log (user_id, item_id) VALUES (?, ?)",
            (uid, item_id),
        )
        if cur.rowcount == 0:
            return False
        c.execute("UPDATE gallery SET votes = votes + 1 WHERE item_id = ?", (item_id,))
    return True


def has_voted(uid: int) -> list:
    with _conn() as c:
        return [r["item_id"] for r in c.execute(
            "SELECT item_id FROM votes_log WHERE user_id = ?", (uid,)).fetchall()]
