import aiosqlite
import csv
import io

DB = "ovoz.db"

async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id       INTEGER PRIMARY KEY,
                username      TEXT,
                full_name     TEXT,
                phone         TEXT,
                balance       INTEGER DEFAULT 0,
                total_earned  INTEGER DEFAULT 0,
                referral_id   INTEGER DEFAULT NULL,
                is_blocked    INTEGER DEFAULT 0,
                joined_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id   INTEGER PRIMARY KEY,
                full_name TEXT,
                added_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT,
                vote_url   TEXT,
                reward     INTEGER DEFAULT 5000,
                check_url  TEXT,
                is_active  INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS votes (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER,
                phone      TEXT,
                project_id INTEGER,
                status     TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER,
                amount      INTEGER,
                card_type   TEXT,
                card_number TEXT,
                status      TEXT DEFAULT 'pending',
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                username  TEXT UNIQUE,
                title     TEXT,
                is_active INTEGER DEFAULT 1,
                added_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER,
                text       TEXT,
                is_read    INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        defaults = [
            ("welcome_text",
             "👋 Assalomu alaykum, {name}!\n\n"
             "💰 Ovoz berib pul ishlang!\n\n"
             "1️⃣ Loyiha tanlang\n"
             "2️⃣ Ovoz bering\n"
             "3️⃣ SMS kodni kiriting\n"
             "4️⃣ 1 soatdan keyin pul tushadi 🎉"),
            ("vote_reward",    "5000"),
            ("referral_reward","1000"),
            ("min_withdraw",   "10000"),
            ("max_withdraw",   "500000"),
            ("channel",        "@premium_milliy"),
            ("uzcard_number",  ""),
            ("humo_number",    ""),
            ("click_number",   ""),
            ("payme_number",   ""),
            ("about_text",
             "✅ Har bir tasdiqlangan ovoz uchun pul olasiz\n"
             "👥 Do'stingiz ovoz bersa — sizga bonus!\n"
             "💳 Pul yechish: Uzcard, Humo, Click, Payme\n"
             "📞 Muammo bo'lsa adminga murojaat qiling"),
        ]
        for k, v in defaults:
            await db.execute(
                "INSERT OR IGNORE INTO settings (key,value) VALUES (?,?)", (k, v)
            )
        await db.execute(
            "INSERT OR IGNORE INTO channels (username,title) VALUES (?,?)",
            ("@premium_milliy", "Premium Milliy")
        )
        await db.commit()

        # Migration uchun
        for col in [
            "ALTER TABLE users ADD COLUMN total_earned INTEGER DEFAULT 0",
        ]:
            try:
                await db.execute(col)
            except Exception:
                pass
        await db.commit()

# ── Settings ───────────────────────────────────────────
async def get(key: str) -> str:
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT value FROM settings WHERE key=?", (key,)) as c:
            r = await c.fetchone()
            return r[0] if r else ""

async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, value)
        )
        await db.commit()

# ── Admins ─────────────────────────────────────────────
async def add_admin(user_id: int, full_name: str):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT OR IGNORE INTO admins (user_id,full_name) VALUES (?,?)",
            (user_id, full_name)
        )
        await db.commit()

async def remove_admin(user_id: int):
    async with aiosqlite.connect(DB) as db:
        await db.execute("DELETE FROM admins WHERE user_id=?", (user_id,))
        await db.commit()

async def get_admins():
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT user_id, full_name FROM admins") as c:
            return await c.fetchall()

async def is_admin_db(user_id: int) -> bool:
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,)) as c:
            return bool(await c.fetchone())

# ── Channels ───────────────────────────────────────────
async def get_active_channels():
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT * FROM channels WHERE is_active=1") as c:
            return await c.fetchall()

async def get_all_channels():
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT * FROM channels ORDER BY id DESC") as c:
            return await c.fetchall()

async def add_channel(username: str, title: str):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT OR IGNORE INTO channels (username,title) VALUES (?,?)",
            (username, title)
        )
        await db.commit()

async def toggle_channel(cid: int, is_active: int):
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE channels SET is_active=? WHERE id=?", (is_active, cid))
        await db.commit()

async def delete_channel(cid: int):
    async with aiosqlite.connect(DB) as db:
        await db.execute("DELETE FROM channels WHERE id=?", (cid,))
        await db.commit()

# ── Users ──────────────────────────────────────────────
async def add_user(user_id: int, username: str, full_name: str, referral_id=None):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id,username,full_name,referral_id) VALUES (?,?,?,?)",
            (user_id, username, full_name, referral_id)
        )
        await db.commit()

async def get_user(user_id: int):
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)) as c:
            return await c.fetchone()

async def search_user(query: str):
    async with aiosqlite.connect(DB) as db:
        q = f"%{query}%"
        async with db.execute(
            "SELECT user_id,username,full_name,phone,balance,is_blocked FROM users "
            "WHERE full_name LIKE ? OR username LIKE ? "
            "OR CAST(user_id AS TEXT) LIKE ? OR phone LIKE ?",
            (q, q, q, q)
        ) as c:
            return await c.fetchall()

async def set_phone(user_id: int, phone: str):
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE users SET phone=? WHERE user_id=?", (phone, user_id))
        await db.commit()

async def add_balance(user_id: int, amount: int):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "UPDATE users SET balance=balance+?, total_earned=total_earned+? WHERE user_id=?",
            (amount, amount, user_id)
        )
        await db.commit()

async def subtract_balance(user_id: int, amount: int):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "UPDATE users SET balance=balance-? WHERE user_id=?", (amount, user_id)
        )
        await db.commit()

async def set_balance_direct(user_id: int, amount: int):
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE users SET balance=? WHERE user_id=?", (amount, user_id))
        await db.commit()

async def get_balance(user_id: int) -> int:
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT balance FROM users WHERE user_id=?", (user_id,)) as c:
            r = await c.fetchone()
            return r[0] if r else 0

async def block_user(user_id: int):
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE users SET is_blocked=1 WHERE user_id=?", (user_id,))
        await db.commit()

async def unblock_user(user_id: int):
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE users SET is_blocked=0 WHERE user_id=?", (user_id,))
        await db.commit()

async def is_blocked(user_id: int) -> bool:
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT is_blocked FROM users WHERE user_id=?", (user_id,)) as c:
            r = await c.fetchone()
            return bool(r[0]) if r else False

async def get_all_users():
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT user_id,username,full_name,phone,balance,is_blocked FROM users ORDER BY balance DESC"
        ) as c:
            return await c.fetchall()

async def get_referral_id(user_id: int):
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT referral_id FROM users WHERE user_id=?", (user_id,)) as c:
            r = await c.fetchone()
            return r[0] if r else None

async def get_referral_count(user_id: int) -> int:
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE referral_id=?", (user_id,)
        ) as c:
            return (await c.fetchone())[0]

async def get_referral_list(user_id: int):
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT u.user_id, u.full_name, u.username, "
            "COALESCE((SELECT COUNT(*) FROM votes "
            "WHERE user_id=u.user_id AND status IN ('approved','auto_approved')),0) AS ok "
            "FROM users u WHERE u.referral_id=? ORDER BY ok DESC LIMIT 20",
            (user_id,)
        ) as c:
            return await c.fetchall()

async def get_referral_earned(user_id: int) -> int:
    """Referraldan olingan jami bonus"""
    rr = await get("referral_reward")
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM users u "
            "WHERE u.referral_id=? AND EXISTS("
            "SELECT 1 FROM votes v WHERE v.user_id=u.user_id "
            "AND v.status IN ('approved','auto_approved'))",
            (user_id,)
        ) as c:
            count = (await c.fetchone())[0]
    return count * int(rr)

def get_level(vote_count: int) -> tuple:
    levels = [
        (0,   20,  "🌱 Yangi",   "🥉 Bronzaga",  20),
        (20,  50,  "🥉 Bronza",  "🥈 Kumushga",  50),
        (50,  100, "🥈 Kumush",  "🥇 Oltinga",   100),
        (100, 200, "🥇 Oltin",   "💎 Olmosga",   200),
        (200, 500, "💎 Olmos",   "👑 Legendaga", 500),
        (500, 9999,"👑 Legend",  None,            0),
    ]
    for mn, mx, name, nxt, target in levels:
        if mn <= vote_count < mx:
            return name, nxt, (target - vote_count) if nxt else 0
    return "👑 Legend", None, 0

# ── Projects ───────────────────────────────────────────
async def add_project(name: str, vote_url: str, reward: int, check_url: str):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT INTO projects (name,vote_url,reward,check_url) VALUES (?,?,?,?)",
            (name, vote_url, reward, check_url)
        )
        await db.commit()

async def get_project(pid: int):
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT * FROM projects WHERE id=?", (pid,)) as c:
            return await c.fetchone()

async def get_active_projects():
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT * FROM projects WHERE is_active=1") as c:
            return await c.fetchall()

async def get_all_projects():
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT * FROM projects ORDER BY id DESC") as c:
            return await c.fetchall()

async def toggle_project(pid: int, is_active: int):
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE projects SET is_active=? WHERE id=?", (is_active, pid))
        await db.commit()

async def update_project_reward(pid: int, reward: int):
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE projects SET reward=? WHERE id=?", (reward, pid))
        await db.commit()

async def delete_project(pid: int):
    async with aiosqlite.connect(DB) as db:
        await db.execute("DELETE FROM projects WHERE id=?", (pid,))
        await db.commit()

# ── Votes ──────────────────────────────────────────────
async def add_vote(user_id: int, phone: str, project_id: int) -> int:
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT INTO votes (user_id,phone,project_id) VALUES (?,?,?)",
            (user_id, phone, project_id)
        )
        await db.commit()
        async with db.execute("SELECT last_insert_rowid()") as c:
            return (await c.fetchone())[0]

async def get_vote(vote_id: int):
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT * FROM votes WHERE id=?", (vote_id,)) as c:
            return await c.fetchone()

async def update_vote_status(vote_id: int, status: str):
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE votes SET status=? WHERE id=?", (status, vote_id))
        await db.commit()

async def get_user_votes(user_id: int):
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT v.id, p.name, v.phone, v.status, v.created_at "
            "FROM votes v JOIN projects p ON v.project_id=p.id "
            "WHERE v.user_id=? ORDER BY v.id DESC LIMIT 10",
            (user_id,)
        ) as c:
            return await c.fetchall()

async def get_all_votes_admin():
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT v.id, u.full_name, v.phone, p.name, v.status, v.created_at "
            "FROM votes v "
            "JOIN users u ON v.user_id=u.user_id "
            "JOIN projects p ON v.project_id=p.id "
            "ORDER BY v.id DESC LIMIT 50"
        ) as c:
            return await c.fetchall()

# ── Payments ───────────────────────────────────────────
async def add_payment(user_id: int, amount: int, card_type: str, card_number: str) -> int:
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT INTO payments (user_id,amount,card_type,card_number) VALUES (?,?,?,?)",
            (user_id, amount, card_type, card_number)
        )
        await db.commit()
        async with db.execute("SELECT last_insert_rowid()") as c:
            return (await c.fetchone())[0]

async def get_pending_payments():
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT p.*, u.full_name, u.username FROM payments p "
            "JOIN users u ON p.user_id=u.user_id "
            "WHERE p.status='pending' ORDER BY p.id DESC"
        ) as c:
            return await c.fetchall()

async def update_payment(pid: int, status: str):
    async with aiosqlite.connect(DB) as db:
        if status == "approved":
            async with db.execute(
                "SELECT user_id, amount FROM payments WHERE id=?", (pid,)
            ) as c:
                row = await c.fetchone()
                if row:
                    await db.execute(
                        "UPDATE users SET balance=balance-? WHERE user_id=?",
                        (row[1], row[0])
                    )
        await db.execute("UPDATE payments SET status=? WHERE id=?", (status, pid))
        await db.commit()

# ── Messages ───────────────────────────────────────────
async def add_message(user_id: int, text: str):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT INTO messages (user_id,text) VALUES (?,?)", (user_id, text)
        )
        await db.commit()

async def get_unread_messages():
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT m.id, m.user_id, u.full_name, u.username, m.text, m.created_at "
            "FROM messages m JOIN users u ON m.user_id=u.user_id "
            "WHERE m.is_read=0 ORDER BY m.id DESC"
        ) as c:
            return await c.fetchall()

async def mark_message_read(mid: int):
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE messages SET is_read=1 WHERE id=?", (mid,))
        await db.commit()

# ── Stats ──────────────────────────────────────────────
async def get_stats():
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c:
            total_users = (await c.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM votes WHERE status IN ('approved','auto_approved')"
        ) as c:
            approved = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM votes WHERE status='pending'") as c:
            pending = (await c.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM votes WHERE status IN ('rejected','auto_rejected')"
        ) as c:
            rejected = (await c.fetchone())[0]
        async with db.execute("SELECT COALESCE(SUM(balance),0) FROM users") as c:
            total_balance = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM payments WHERE status='pending'") as c:
            pending_pay = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM messages WHERE is_read=0") as c:
            unread_msg = (await c.fetchone())[0]
        return total_users, approved, pending, rejected, total_balance, pending_pay, unread_msg

# ── Export ─────────────────────────────────────────────
async def export_users_csv() -> bytes:
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT user_id, username, full_name, phone, balance, total_earned, is_blocked, joined_at "
            "FROM users ORDER BY balance DESC"
        ) as c:
            rows = await c.fetchall()
    out = io.StringIO()
    w   = csv.writer(out)
    w.writerow(["ID", "Username", "Ism", "Telefon", "Balans", "Jami ishlagan", "Bloklangan", "Qoshilgan"])
    for r in rows:
        w.writerow(r)
    return out.getvalue().encode("utf-8-sig")
