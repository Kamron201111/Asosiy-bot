import aiosqlite

DB = "ovoz.db"

async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                phone TEXT,
                balance INTEGER DEFAULT 0,
                referral_id INTEGER DEFAULT NULL,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS votes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                phone TEXT,
                project_id INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                vote_url TEXT,
                reward INTEGER DEFAULT 5000,
                check_url TEXT,
                is_active INTEGER DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount INTEGER,
                card_type TEXT,
                card_number TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        defaults = [
            ("bot_token", ""),
            ("admin_ids", ""),
            ("welcome_text", "Assalomu alaykum {name}! 👋\nOvoz berib pul ishlang 💰"),
            ("vote_reward", "5000"),
            ("referral_reward", "5000"),
            ("uzcard_numbers", ""),
            ("humo_numbers", ""),
            ("click_numbers", ""),
            ("payme_numbers", ""),
        ]
        for k, v in defaults:
            await db.execute("INSERT OR IGNORE INTO settings (key,value) VALUES (?,?)", (k, v))
        await db.commit()

async def get(key):
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT value FROM settings WHERE key=?", (key,)) as c:
            r = await c.fetchone()
            return r[0] if r else ""

async def set_setting(key, value):
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, value))
        await db.commit()

async def add_user(user_id, username, full_name, referral_id=None):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id,username,full_name,referral_id) VALUES (?,?,?,?)",
            (user_id, username, full_name, referral_id)
        )
        await db.commit()

async def get_user(user_id):
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)) as c:
            return await c.fetchone()

async def set_phone(user_id, phone):
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE users SET phone=? WHERE user_id=?", (phone, user_id))
        await db.commit()

async def add_balance(user_id, amount):
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, user_id))
        await db.commit()

async def get_balance(user_id):
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT balance FROM users WHERE user_id=?", (user_id,)) as c:
            r = await c.fetchone()
            return r[0] if r else 0

async def add_vote(user_id, phone, project_id):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT INTO votes (user_id,phone,project_id) VALUES (?,?,?)",
            (user_id, phone, project_id)
        )
        await db.commit()
        async with db.execute("SELECT last_insert_rowid()") as c:
            return (await c.fetchone())[0]

async def get_vote(vote_id):
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT * FROM votes WHERE id=?", (vote_id,)) as c:
            return await c.fetchone()

async def update_vote_status(vote_id, status):
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE votes SET status=? WHERE id=?", (status, vote_id))
        await db.commit()

async def get_active_projects():
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT * FROM projects WHERE is_active=1") as c:
            return await c.fetchall()

async def get_project(project_id):
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT * FROM projects WHERE id=?", (project_id,)) as c:
            return await c.fetchone()

async def add_project(name, vote_url, reward, check_url):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT INTO projects (name,vote_url,reward,check_url) VALUES (?,?,?,?)",
            (name, vote_url, reward, check_url)
        )
        await db.commit()

async def toggle_project(project_id, is_active):
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE projects SET is_active=? WHERE id=?", (is_active, project_id))
        await db.commit()

async def get_all_projects():
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT * FROM projects") as c:
            return await c.fetchall()

async def get_stats():
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c:
            users = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM votes WHERE status='approved'") as c:
            approved = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM votes WHERE status='pending'") as c:
            pending = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM votes WHERE status='rejected'") as c:
            rejected = (await c.fetchone())[0]
        async with db.execute("SELECT COALESCE(SUM(balance),0) FROM users") as c:
            total_balance = (await c.fetchone())[0]
        return users, approved, pending, rejected, total_balance

async def get_all_users():
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT user_id,username,full_name,phone,balance FROM users") as c:
            return await c.fetchall()

async def add_payment_request(user_id, amount, card_type, card_number):
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
            "SELECT p.*,u.full_name,u.username FROM payments p JOIN users u ON p.user_id=u.user_id WHERE p.status='pending'"
        ) as c:
            return await c.fetchall()

async def update_payment(payment_id, status):
    async with aiosqlite.connect(DB) as db:
        if status == 'approved':
            async with db.execute("SELECT user_id,amount FROM payments WHERE id=?", (payment_id,)) as c:
                row = await c.fetchone()
                if row:
                    await db.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (row[1], row[0]))
        await db.execute("UPDATE payments SET status=? WHERE id=?", (status, payment_id))
        await db.commit()

async def get_referral_id(user_id):
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT referral_id FROM users WHERE user_id=?", (user_id,)) as c:
            r = await c.fetchone()
            return r[0] if r else None
