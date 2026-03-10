import asyncio
import logging
import aiohttp
import io
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage

from database import (
    init_db, get, set_setting,
    add_admin, remove_admin, get_admins, is_admin_db,
    get_active_channels, get_all_channels, add_channel, toggle_channel, delete_channel,
    add_user, get_user, search_user, set_phone,
    add_balance, subtract_balance, set_balance_direct, get_balance,
    block_user, unblock_user, is_blocked,
    get_all_users, get_referral_id, get_referral_count,
    get_referral_list, get_referral_earned, get_level,
    add_project, get_project, get_active_projects, get_all_projects,
    toggle_project, update_project_reward, delete_project,
    add_vote, get_vote, update_vote_status, get_user_votes, get_all_votes_admin,
    add_payment, get_pending_payments, update_payment,
    add_message, get_unread_messages, mark_message_read,
    get_stats, export_users_csv,
)
from site_worker import submit_phone, submit_sms_code, check_vote_result

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────
BOT_TOKEN   = "8679118861:AAES2RZz_HdxuZWhqi9pVSWxIl5yiL1oL2U"
SUPER_ADMIN = 6498632307
# ─────────────────────────────────────

bot      = Bot(token=BOT_TOKEN, parse_mode="Markdown")
storage  = MemoryStorage()
dp       = Dispatcher(bot, storage=storage)
sessions: dict = {}

# ══════════════════════════════════════════════════════════
# STATES
# ══════════════════════════════════════════════════════════
class Vote(StatesGroup):
    project = State()
    phone   = State()
    sms     = State()

class Withdraw(StatesGroup):
    amount = State()
    card   = State()
    number = State()

class Admin(StatesGroup):
    broadcast        = State()
    proj_name        = State()
    proj_url         = State()
    proj_reward      = State()
    proj_check       = State()
    proj_edit_reward = State()
    add_admin_id     = State()
    setting_val      = State()
    block_id         = State()
    unblock_id       = State()
    addbal_uid       = State()
    addbal_amount    = State()
    subbal_uid       = State()
    subbal_amount    = State()
    setbal_uid       = State()
    setbal_amount    = State()
    dm_uid           = State()
    dm_text          = State()
    channel_add      = State()
    user_search      = State()

class User(StatesGroup):
    murojaat = State()

# ══════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════
async def is_admin(uid: int) -> bool:
    return uid == SUPER_ADMIN or await is_admin_db(uid)

async def check_all_subs(uid: int) -> bool:
    """Barcha aktiv kanallarga obuna tekshiradi"""
    channels = await get_active_channels()
    if not channels:
        return True
    for ch in channels:
        try:
            m = await bot.get_chat_member(ch[1], uid)
            if m.status in ("left", "kicked"):
                return False
        except Exception:
            pass
    return True

async def sub_gate(msg: types.Message) -> bool:
    if await check_all_subs(msg.from_user.id):
        return True
    channels = await get_active_channels()
    kb = types.InlineKeyboardMarkup(row_width=1)
    for ch in channels:
        kb.add(types.InlineKeyboardButton(
            f"📢 {ch[2]} — Obuna bo'lish",
            url=f"https://t.me/{ch[1].lstrip('@')}"
        ))
    kb.add(types.InlineKeyboardButton("✅ Obuna bo'ldim — Tekshirish", callback_data="chk_sub"))
    await msg.answer(
        "🔐 *Botdan foydalanish uchun*\nquyidagi kanallarga obuna bo'ling:\n\n"
        + "\n".join(f"📢 *{ch[2]}* ({ch[1]})" for ch in channels)
        + "\n\nObuna bo'lgach ✅ *Tekshirish* tugmasini bosing 👇",
        reply_markup=kb
    )
    return False

def kb_main(adm=False) -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add("🗳 Ovoz berish",      "💎 Hisobim")
    kb.add("🔗 Do'st taklif",    "💳 Pul yechish")
    kb.add("📊 Ovozlarim",       "ℹ️ Bot haqida")
    kb.add("💬 Murojaat")
    if adm:
        kb.add("⚙️ Admin panel")
    return kb

def kb_admin() -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add("📁 Loyiha",          "📦 Ovozlar")
    kb.add("📋 Murojaatlar",     "👥 Foydalanuvchilar")
    kb.add("📊 Statistika",      "📣 Xabar yuborish")
    kb.add("💰 To'lov sozlash",  "⚙️ Sozlamalar")
    kb.add("📡 Kanallar",        "👮 Adminlar")
    kb.add("🚫 Bloklash",        "💬 DM yuborish")
    kb.add("📂 Excel export",    "🔍 Foydalanuvchi qidirish")
    kb.add("💵 Balans tahrirlash","👤 Foydalanuvchi paneli")
    kb.add("🔙 Asosiy menyu")
    return kb

async def ping_admins(text: str, markup=None):
    ids = list({SUPER_ADMIN} | {a[0] for a in await get_admins()})
    for aid in ids:
        try:
            await bot.send_message(aid, text, reply_markup=markup)
        except Exception:
            pass

# ══════════════════════════════════════════════════════════
# OBUNA CALLBACK
# ══════════════════════════════════════════════════════════
@dp.callback_query_handler(lambda c: c.data == "chk_sub")
async def cb_check_sub(cb: types.CallbackQuery):
    if await check_all_subs(cb.from_user.id):
        await cb.message.delete()
        u   = cb.from_user
        adm = await is_admin(u.id)
        txt = await get("welcome_text")
        await bot.send_message(u.id, txt.format(name=u.first_name), reply_markup=kb_main(adm))
    else:
        await cb.answer("Hali obuna bo'lmagansiz! Barcha kanallarga obuna bo'ling.", show_alert=True)

# ══════════════════════════════════════════════════════════
# /START
# ══════════════════════════════════════════════════════════
@dp.message_handler(commands=["start"])
async def cmd_start(msg: types.Message, state: FSMContext):
    await state.finish()
    u      = msg.from_user
    args   = msg.get_args()
    ref_id = int(args) if args and args.isdigit() and int(args) != u.id else None
    await add_user(u.id, u.username, u.full_name, ref_id)

    if await is_blocked(u.id):
        await msg.answer("🚫 Siz botdan bloklangansiz.\nMurojaat uchun adminga yozing.")
        return
    if not await sub_gate(msg):
        return

    adm = await is_admin(u.id)
    txt = await get("welcome_text")
    await msg.answer(txt.format(name=u.first_name), reply_markup=kb_main(adm))

# ══════════════════════════════════════════════════════════
# BOT HAQIDA
# ══════════════════════════════════════════════════════════
@dp.message_handler(lambda m: m.text == "ℹ️ Bot haqida")
async def cmd_about(msg: types.Message):
    if not await sub_gate(msg):
        return
    r    = int(await get("vote_reward"))
    rr   = int(await get("referral_reward"))
    minw = int(await get("min_withdraw"))
    maxw = int(await get("max_withdraw"))
    txt  = await get("about_text")
    await msg.answer(
        f"🤖 *BOT HAQIDA*\n\n{txt}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Ovoz mukofoti: *{r:,} so'm*\n"
        f"👥 Referral bonus: *{rr:,} so'm*\n"
        f"📤 Min yechish: *{minw:,} so'm*\n"
        f"📤 Max yechish: *{maxw:,} so'm*\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📋 *Jarayon:*\n"
        f"1️⃣  Loyihani tanlang\n"
        f"2️⃣  Saytga o'tib ovoz bering\n"
        f"3️⃣  Telefon raqamingizni kiriting\n"
        f"4️⃣  SMS kodni kiriting\n"
        f"5️⃣  1 soatdan keyin pul hisobingizga tushadi 💸"
    )

# ══════════════════════════════════════════════════════════
# HISOBIM
# ══════════════════════════════════════════════════════════
@dp.message_handler(lambda m: m.text == "💎 Hisobim")
async def cmd_hisob(msg: types.Message):
    if not await sub_gate(msg):
        return
    user = await get_user(msg.from_user.id)
    if not user:
        await msg.answer("Iltimos /start bosing.")
        return

    # user ustunlari: user_id, username, full_name, phone, balance, total_earned, referral_id, is_blocked, joined_at
    uid        = user[0]
    full_name  = user[2]
    phone      = user[3]
    balance    = int(user[4])
    total_earn = int(user[5]) if user[5] else 0
    minw       = int(await get("min_withdraw"))

    votes      = await get_user_votes(uid)
    total_v    = len(votes)
    approved_v = sum(1 for v in votes if v[3] in ("approved", "auto_approved"))
    pending_v  = sum(1 for v in votes if v[3] == "pending")
    rejected_v = sum(1 for v in votes if v[3] in ("rejected", "auto_rejected"))

    # Daraja
    level_name, next_level, remaining = get_level(approved_v)

    # Inline tugmalar
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton(
            f"💸 Pul yechish (min {minw:,})",
            callback_data="hisob_withdraw"
        ),
        types.InlineKeyboardButton("🔄 Yangilash", callback_data="hisob_refresh")
    )
    kb.add(types.InlineKeyboardButton("👥 Do'stlarni taklif qilish", callback_data="hisob_ref"))

    next_txt = f"\n📊 _{approved_v} ovoz → {next_level}_" if next_level else ""

    await msg.answer(
        f"👤 *Mening hisobim*\n"
        f"{'━' * 22}\n"
        f"🆔 ID: {uid}\n"
        f"👤 Ism: *{full_name}*\n"
        f"📱 Raqam: {phone or 'Kiritilmagan'}\n"
        f"🏅 Daraja: *{level_name}*{next_txt}\n\n"
        f"💰 *Moliya:*\n"
        f"├ 💵 Balans: *{balance:,} so'm*\n"
        f"├ ⏳ Kutilayotgan: *{pending_v * int(await get('vote_reward')):,} so'm*\n"
        f"├ 📈 Jami ishlagan: *{total_earn:,} so'm*\n"
        f"└ 💳 Min. yechish: *{minw:,} so'm*\n\n"
        f"🗳 *Ovozlar:*\n"
        f"├ 📊 Jami: *{total_v}* ta\n"
        f"├ ✅ Tasdiqlangan: *{approved_v}* ta\n"
        f"├ ⏳ Kutilmoqda: *{pending_v}* ta\n"
        f"└ ❌ Rad etilgan: *{rejected_v}* ta",
        reply_markup=kb
    )

@dp.callback_query_handler(lambda c: c.data == "hisob_refresh")
async def cb_hisob_refresh(cb: types.CallbackQuery):
    await cb.answer("🔄 Yangilandi!")
    # Yangi xabar yuborish
    fake = cb.message
    fake.from_user = cb.from_user
    await cmd_hisob(cb.message)

@dp.callback_query_handler(lambda c: c.data == "hisob_withdraw")
async def cb_hisob_withdraw(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer()
    balance = await get_balance(cb.from_user.id)
    minw    = int(await get("min_withdraw"))
    maxw    = int(await get("max_withdraw"))
    if balance < minw:
        await cb.message.answer(
            f"❗ *Balans yetarli emas!*\n\n"
            f"💰 Balansingiz: *{balance:,} so'm*\n"
            f"📤 Minimal yechish: *{minw:,} so'm*\n\n"
            f"Ovoz bering va balans to'plang 🗳"
        )
        return
    await cb.message.answer(
        f"💳 *PUL YECHISH*\n\n"
        f"💰 Balansingiz: *{balance:,} so'm*\n"
        f"📤 Min: *{minw:,} so'm*\n"
        f"📤 Max: *{maxw:,} so'm*\n\n"
        f"Necha so'm yechmoqchisiz?\n_(Raqam kiriting)_"
    )
    await Withdraw.amount.set()

@dp.callback_query_handler(lambda c: c.data == "hisob_ref")
async def cb_hisob_ref(cb: types.CallbackQuery):
    await cb.answer()
    uid       = cb.from_user.id
    rr        = int(await get("referral_reward"))
    info      = await bot.get_me()
    link      = f"https://t.me/{info.username}?start={uid}"
    ref_count = await get_referral_count(uid)
    ref_earn  = await get_referral_earned(uid)

    pending_refs = 0
    ref_list = await get_referral_list(uid)
    pending_refs = sum(1 for r in ref_list if r[3] == 0)
    approved_refs = sum(1 for r in ref_list if r[3] > 0)

    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton(
        "📤 Do'stlarga ulashish",
        url=f"https://t.me/share/url?url={link}&text=Ovoz%20berib%20pul%20ishlang!"
    ))
    kb.add(types.InlineKeyboardButton("👥 Do'stlar ro'yxati", callback_data="ref_list"))

    await cb.message.answer(
        f"👥 *Do'stlarni taklif qilish*\n"
        f"{'━' * 22}\n"
        f"🔗 Sizning havolangiz:\n`{link}`\n\n"
        f"📊 *Statistika:*\n"
        f"├ 💰 Har bir do'st uchun: *{rr:,} so'm*\n"
        f"├ 🎁 Bonus FAQAT: tasdiqlangan O'zbek raqam\n"
        f"├ ✅ Tasdiqlangan do'stlar: *{approved_refs}* ta\n"
        f"├ ⏳ Kutilayotgan: *{pending_refs}* ta\n"
        f"└ 💵 Jami referal daromad: *{ref_earn:,} so'm*\n\n"
        f"💡 _Do'stingiz botga kirib, O'zbek raqamini tasdiqlagandan "
        f"keyin {rr:,} so'm balansingizga avtomatik tushadi!_",
        reply_markup=kb
    )

@dp.callback_query_handler(lambda c: c.data == "ref_list")
async def cb_ref_list(cb: types.CallbackQuery):
    uid      = cb.from_user.id
    ref_list = await get_referral_list(uid)
    if not ref_list:
        await cb.answer("Hozircha do'st yo'q!", show_alert=True)
        return
    text = "👥 *Do'stlarim ro'yxati:*\n\n"
    for i, r in enumerate(ref_list, 1):
        rid, fname, uname, ok = r
        ulink = f"@{uname}" if uname else f"ID:{rid}"
        text += f"{i}. *{fname}* {ulink} — ✅ {ok} ovoz\n"
    await cb.message.answer(text)
    await cb.answer()

# ══════════════════════════════════════════════════════════
# OVOZLARIM
# ══════════════════════════════════════════════════════════
@dp.message_handler(lambda m: m.text == "📊 Ovozlarim")
async def cmd_my_votes(msg: types.Message):
    if not await sub_gate(msg):
        return
    votes = await get_user_votes(msg.from_user.id)
    if not votes:
        await msg.answer(
            "📊 *OVOZLARIM*\n\n"
            "Hozircha ovoz bermadingiz.\n\n"
            "🗳 *Ovoz berish* tugmasini bosib pul ishlashni boshlang!"
        )
        return
    STATUS = {
        "pending":       "⏳ Kutilmoqda",
        "approved":      "✅ Tasdiqlandi",
        "rejected":      "❌ Rad etildi",
        "auto_approved": "✅ Tasdiqlandi",
        "auto_rejected": "❌ Topilmadi",
    }
    lines = ["📊 *OVOZLARIM*\n"]
    for v in votes:
        vid, pname, phone, status, created = v
        date = (created or "")[:10]
        lines.append(
            f"*#{vid}* — _{pname}_\n"
            f"📱 {phone}\n"
            f"{STATUS.get(status, status)} · {date}\n"
        )
    await msg.answer("\n".join(lines))

# ══════════════════════════════════════════════════════════
# DO'ST TAKLIF
# ══════════════════════════════════════════════════════════
@dp.message_handler(lambda m: m.text == "🔗 Do'st taklif")
async def cmd_referral(msg: types.Message):
    if not await sub_gate(msg):
        return
    uid       = msg.from_user.id
    rr        = int(await get("referral_reward"))
    info      = await bot.get_me()
    link      = f"https://t.me/{info.username}?start={uid}"
    ref_count = await get_referral_count(uid)
    ref_earn  = await get_referral_earned(uid)
    ref_list  = await get_referral_list(uid)
    approved_refs = sum(1 for r in ref_list if r[3] > 0)
    pending_refs  = ref_count - approved_refs

    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton(
        "📤 Do'stlarga ulashish",
        url=f"https://t.me/share/url?url={link}&text=Ovoz%20berib%20pul%20ishlang!"
    ))
    kb.add(types.InlineKeyboardButton("👥 Do'stlar ro'yxati", callback_data="ref_list"))

    await msg.answer(
        f"👥 *Do'stlarni taklif qilish*\n"
        f"{'━' * 22}\n"
        f"🔗 Sizning havolangiz:\n`{link}`\n\n"
        f"📊 *Statistika:*\n"
        f"├ 💰 Har bir do'st uchun: *{rr:,} so'm*\n"
        f"├ 🎁 Bonus FAQAT: tasdiqlangan O'zbek raqam\n"
        f"├ ✅ Tasdiqlangan do'stlar: *{approved_refs}* ta\n"
        f"├ ⏳ Kutilayotgan: *{pending_refs}* ta\n"
        f"└ 💵 Jami referal daromad: *{ref_earn:,} so'm*\n\n"
        f"💡 _Do'stingiz botga kirib, O'zbek raqamini tasdiqlagandan "
        f"keyin {rr:,} so'm balansingizga avtomatik tushadi!_",
        reply_markup=kb
    )

# ══════════════════════════════════════════════════════════
# MUROJAAT
# ══════════════════════════════════════════════════════════
@dp.message_handler(lambda m: m.text == "💬 Murojaat")
async def cmd_murojaat(msg: types.Message):
    if not await sub_gate(msg):
        return
    await msg.answer(
        "💬 *Murojaat yuboring*\n\n"
        "Adminga yuboriladigan xabaringizni kiriting:\n\n"
        "_Bekor qilish uchun /start bosing_"
    )
    await User.murojaat.set()

@dp.message_handler(state=User.murojaat)
async def save_murojaat(msg: types.Message, state: FSMContext):
    uid = msg.from_user.id
    await add_message(uid, msg.text)
    await msg.answer("✅ *Murojaatingiz adminga yuborildi!*\n\nTez orada javob beramiz.", reply_markup=kb_main(await is_admin(uid)))

    # Adminlarga xabar
    user = await get_user(uid)
    fname = user[2] if user else "Noma'lum"
    uname = f"@{user[1]}" if user and user[1] else f"ID:{uid}"
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(f"💬 Javob berish", callback_data=f"reply_{uid}"))
    await ping_admins(
        f"📋 *Yangi murojaat*\n\n"
        f"👤 {fname} ({uname})\n"
        f"🆔 ID: `{uid}`\n\n"
        f"💬 {msg.text}",
        markup=kb
    )
    await state.finish()

@dp.callback_query_handler(lambda c: c.data.startswith("reply_"))
async def cb_reply_user(cb: types.CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id):
        return
    uid = int(cb.data.split("_")[1])
    await state.update_data(dm_uid=uid)
    await cb.message.answer(f"💬 `{uid}` ga javob yuboring:")
    await Admin.dm_text.set()
    await cb.answer()

# ══════════════════════════════════════════════════════════
# OVOZ BERISH
# ══════════════════════════════════════════════════════════
@dp.message_handler(lambda m: m.text == "🗳 Ovoz berish")
async def cmd_vote_start(msg: types.Message, state: FSMContext):
    if not await sub_gate(msg):
        return
    if await is_blocked(msg.from_user.id):
        await msg.answer("🚫 Siz botdan bloklangansiz.")
        return

    projects = await get_active_projects()
    if not projects:
        await msg.answer(
            "⏳ *Hozirda faol loyiha yo'q.*\n\n"
            "🔔 Yangi loyiha qo'shilganda darhol xabar beramiz!\n"
            "Sabr qiling 🙏"
        )
        return

    kb = types.InlineKeyboardMarkup(row_width=1)
    for p in projects:
        pid, name, url, reward, check_url, active, created = p
        kb.add(types.InlineKeyboardButton(
            f"📌 {name}  ·  💰 {int(reward):,} so'm",
            callback_data=f"vp_{pid}"
        ))
    await msg.answer("🗳 *OVOZ BERISH*\n\nLoyihani tanlang 👇", reply_markup=kb)
    await Vote.project.set()

@dp.callback_query_handler(lambda c: c.data.startswith("vp_"), state=Vote.project)
async def cb_vote_project(cb: types.CallbackQuery, state: FSMContext):
    pid = int(cb.data[3:])
    p   = await get_project(pid)
    if not p:
        await cb.answer("Loyiha topilmadi!")
        return
    pid, name, vote_url, reward, check_url, active, created = p
    await state.update_data(pid=pid, proj=p)

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(f"🗳 {name} — Ovoz berish", url=vote_url))
    await cb.message.answer(
        f"📌 *{name}*\n"
        f"💰 Mukofot: *{int(reward):,} so'm*\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"1️⃣  Quyidagi tugmani bosib saytga o'ting\n"
        f"2️⃣  Saytda ovoz bering\n"
        f"3️⃣  Qaytib telefon raqamingizni yozing\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📱 *Telefon raqamingizni kiriting:*\n"
        f"_Namuna: +998901234567_",
        reply_markup=kb
    )
    await Vote.phone.set()
    await cb.answer()

@dp.message_handler(state=Vote.phone)
async def vote_phone(msg: types.Message, state: FSMContext):
    raw = msg.text.strip().replace(" ", "").replace("-", "")
    if not raw.replace("+", "").isdigit() or len(raw.replace("+", "")) < 9:
        await msg.answer(
            "❌ *Noto'g'ri format!*\n\n"
            "Qaytadan kiriting:\n_Namuna: +998901234567_"
        )
        return
    if not raw.startswith("+"):
        d   = raw.lstrip("+")
        raw = "+998" + d[-9:] if not d.startswith("998") else "+" + d

    await state.update_data(phone=raw)
    data  = await state.get_data()
    proj  = data["proj"]
    pid, name, vote_url, reward, check_url, active, created = proj

    wait = await msg.answer("⏳ *Saytga ulanmoqda...*")
    sess = aiohttp.ClientSession()
    sessions[msg.from_user.id] = sess
    ok, html = await submit_phone(sess, vote_url, raw)

    try:
        await bot.delete_message(msg.chat.id, wait.message_id)
    except Exception:
        pass

    if ok:
        await msg.answer(
            f"✅ *SMS kod yuborildi!*\n\n"
            f"📱 Raqam: `{raw}`\n\n"
            f"📩 Telefoningizga kelgan *4-6 raqamli kodni* kiriting:"
        )
    else:
        await sess.close()
        sessions.pop(msg.from_user.id, None)
        await state.update_data(manual=True)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(f"🗳 {name} — Ovoz berish", url=vote_url))
        await msg.answer(
            f"⚠️ *Avtomatik ulanishda xatolik*\n\n"
            f"Qo'lda bajaring:\n"
            f"1️⃣  Quyidagi tugmani bosib saytga o'ting\n"
            f"2️⃣  Telefon raqamingizni saytga kiriting\n"
            f"3️⃣  SMS kelgach kodni shu yerga yuboring\n\n"
            f"📩 *SMS kodini kiriting:*",
            reply_markup=kb
        )
    await Vote.sms.set()

@dp.message_handler(state=Vote.sms)
async def vote_sms(msg: types.Message, state: FSMContext):
    code = msg.text.strip()
    if not code.isdigit() or len(code) < 4:
        await msg.answer("❌ *Noto'g'ri kod!* Qaytadan kiriting:")
        return

    data   = await state.get_data()
    phone  = data["phone"]
    proj   = data["proj"]
    manual = data.get("manual", False)
    pid, name, vote_url, reward, check_url, active, created = proj
    uid = msg.from_user.id

    if not manual:
        sess = sessions.get(uid)
        if sess:
            await submit_sms_code(sess, vote_url, phone, code)
            await sess.close()
            sessions.pop(uid, None)

    vote_id    = await add_vote(uid, phone, pid)
    await set_phone(uid, phone)
    check_time = (datetime.now() + timedelta(hours=1)).strftime("%H:%M")

    await msg.answer(
        f"✅ *Ovozingiz qabul qilindi!*\n\n"
        f"📱 Raqam: `{phone}`\n"
        f"📌 Loyiha: *{name}*\n"
        f"⏰ Tekshirish: *{check_time} da*\n\n"
        f"1 soatdan keyin tasdiqlansa\n"
        f"💰 *{int(reward):,} so'm* hisobingizga o'tadi!",
        reply_markup=kb_main(await is_admin(uid))
    )

    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"va_{vote_id}"),
        types.InlineKeyboardButton("❌ Rad etish",  callback_data=f"vr_{vote_id}")
    )
    await ping_admins(
        f"🗳 *Yangi ovoz #{vote_id}*\n\n"
        f"👤 {msg.from_user.full_name}\n"
        f"🆔 ID: `{uid}`\n"
        f"📱 Raqam: `{phone}`\n"
        f"📌 Loyiha: *{name}*\n"
        f"🔢 Kod: `{code}`",
        markup=kb
    )
    asyncio.create_task(_auto_check(vote_id, uid, phone, check_url, reward, name))
    await state.finish()

async def _auto_check(vote_id, uid, phone, check_url, reward, proj_name):
    await asyncio.sleep(3600)
    v = await get_vote(vote_id)
    if not v or v[4] != "pending":
        return
    found = await check_vote_result(phone, check_url, "")
    if found:
        await update_vote_status(vote_id, "auto_approved")
        await add_balance(uid, int(reward))
        ref_id = await get_referral_id(uid)
        if ref_id:
            rr = int(await get("referral_reward"))
            await add_balance(ref_id, rr)
            try:
                await bot.send_message(ref_id,
                    f"🎉 *Do'stingizning ovozi tasdiqlandi!*\n\n"
                    f"Hisobingizga *{rr:,} so'm* qo'shildi 💰")
            except Exception:
                pass
        try:
            await bot.send_message(uid,
                f"🎉 *Tabriklaymiz!*\n\n"
                f"📌 *{proj_name}*\n"
                f"💰 *{int(reward):,} so'm* hisobingizga qo'shildi!\n\n"
                f"💳 *Pul yechish* tugmasini bosing.")
        except Exception:
            pass
    else:
        await update_vote_status(vote_id, "auto_rejected")
        try:
            await bot.send_message(uid,
                f"❌ *Ovozingiz topilmadi*\n\n"
                f"📌 *{proj_name}*\n"
                f"📱 Raqam: `{phone}`\n\n"
                f"Ovozingizni tekshiring:\n{check_url}")
        except Exception:
            pass

# ── Admin: ovoz tasdiqlash ────────────────────────────────
@dp.callback_query_handler(lambda c: c.data.startswith("va_") or c.data.startswith("vr_"))
async def cb_admin_vote(cb: types.CallbackQuery):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Ruxsat yo'q!")
        return
    approve = cb.data.startswith("va_")
    vid     = int(cb.data.split("_")[1])
    v       = await get_vote(vid)
    if not v:
        await cb.answer("Ovoz topilmadi!")
        return
    vote_id, uid, phone, proj_id, status, created = v
    if status != "pending":
        await cb.answer("Allaqachon ko'rib chiqilgan!")
        return
    p      = await get_project(proj_id)
    reward = int(p[3]) if p else 5000
    pname  = p[1]      if p else "Loyiha"

    if approve:
        await update_vote_status(vid, "approved")
        await add_balance(uid, reward)
        ref_id = await get_referral_id(uid)
        if ref_id:
            rr = int(await get("referral_reward"))
            await add_balance(ref_id, rr)
            try:
                await bot.send_message(ref_id,
                    f"🎉 *Do'stingizning ovozi tasdiqlandi!*\n\n"
                    f"Hisobingizga *{rr:,} so'm* qo'shildi 💰")
            except Exception:
                pass
        try:
            await bot.send_message(uid,
                f"🎉 *Ovozingiz tasdiqlandi!*\n\n"
                f"📌 *{pname}*\n"
                f"💰 *{reward:,} so'm* hisobingizga qo'shildi!\n\n"
                f"💳 *Pul yechish* tugmasini bosing.")
        except Exception:
            pass
        await cb.message.edit_text(cb.message.text + "\n\n✅ *TASDIQLANDI*")
        await cb.answer("✅ Tasdiqlandi!")
    else:
        await update_vote_status(vid, "rejected")
        try:
            await bot.send_message(uid,
                f"❌ *Ovozingiz tasdiqlanmadi*\n\n"
                f"📌 *{pname}*\n"
                f"Muammo bo'lsa adminga murojaat qiling.")
        except Exception:
            pass
        await cb.message.edit_text(cb.message.text + "\n\n❌ *RAD ETILDI*")
        await cb.answer("❌ Rad etildi!")

# ── Admin: to'lov tasdiqlash ──────────────────────────────
@dp.callback_query_handler(lambda c: c.data.startswith("pa_") or c.data.startswith("pr_"))
async def cb_admin_pay(cb: types.CallbackQuery):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Ruxsat yo'q!")
        return
    approve = cb.data.startswith("pa_")
    pid     = int(cb.data.split("_")[1])
    if approve:
        await update_payment(pid, "approved")
        await cb.message.edit_text(cb.message.text + "\n\n✅ *O'TKAZILDI*")
        await cb.answer("✅ Tasdiqlandi!")
    else:
        await update_payment(pid, "rejected")
        await cb.message.edit_text(cb.message.text + "\n\n❌ *RAD ETILDI*")
        await cb.answer("❌ Rad etildi!")

# ══════════════════════════════════════════════════════════
# PUL YECHISH
# ══════════════════════════════════════════════════════════
@dp.message_handler(lambda m: m.text == "💳 Pul yechish")
async def cmd_withdraw(msg: types.Message, state: FSMContext):
    if not await sub_gate(msg):
        return
    balance = await get_balance(msg.from_user.id)
    minw    = int(await get("min_withdraw"))
    maxw    = int(await get("max_withdraw"))
    if balance < minw:
        await msg.answer(
            f"❌ *Balans yetarli emas!*\n\n"
            f"💰 Balansingiz: *{balance:,} so'm*\n"
            f"📊 Minimal yechish: *{minw:,} so'm*\n\n"
            f"Ko'proq ovoz bering va pul ishlang! 💪"
        )
        return
    await msg.answer(
        f"💳 *PUL YECHISH*\n\n"
        f"💰 Balansingiz: *{balance:,} so'm*\n"
        f"📤 Min: *{minw:,} so'm*\n"
        f"📤 Max: *{maxw:,} so'm*\n\n"
        f"Necha so'm yechmoqchisiz?\n_(Raqam kiriting)_"
    )
    await Withdraw.amount.set()

@dp.message_handler(state=Withdraw.amount)
async def withdraw_amount(msg: types.Message, state: FSMContext):
    t = msg.text.strip().replace(" ", "").replace(",", "")
    if not t.isdigit():
        await msg.answer("❗ Faqat raqam kiriting!")
        return
    amount  = int(t)
    balance = await get_balance(msg.from_user.id)
    minw    = int(await get("min_withdraw"))
    maxw    = int(await get("max_withdraw"))
    if amount < minw:
        await msg.answer(f"❗ Minimal yechish: *{minw:,} so'm*")
        return
    if amount > maxw:
        await msg.answer(f"❗ Maksimal yechish: *{maxw:,} so'm*")
        return
    if amount > balance:
        await msg.answer(f"❗ Balans yetarli emas. Sizda: *{balance:,} so'm*")
        return
    await state.update_data(amount=amount)

    uzcard = await get("uzcard_number")
    humo   = await get("humo_number")
    click  = await get("click_number")
    payme  = await get("payme_number")

    def btn(label, icon, num, cd):
        suffix = f" · {num}" if num else ""
        return types.InlineKeyboardButton(f"{icon} {label}{suffix}", callback_data=cd)

    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(btn("Uzcard", "💳", uzcard, "c_uzcard"))
    kb.add(btn("Humo",   "💳", humo,   "c_humo"))
    kb.add(btn("Click",  "💚", click,  "c_click"))
    kb.add(btn("Payme",  "🔴", payme,  "c_payme"))

    await msg.answer(
        f"💳 *To'lov usulini tanlang*\n\nMiqdor: *{amount:,} so'm*",
        reply_markup=kb
    )
    await Withdraw.card.set()

@dp.callback_query_handler(lambda c: c.data.startswith("c_"), state=Withdraw.card)
async def withdraw_card(cb: types.CallbackQuery, state: FSMContext):
    card_type = cb.data[2:]
    await state.update_data(card_type=card_type)
    await cb.message.answer(
        f"💳 *{card_type.upper()}* tanlandi\n\n"
        f"O'z karta yoki telefon raqamingizni kiriting:"
    )
    await Withdraw.number.set()
    await cb.answer()

@dp.message_handler(state=Withdraw.number)
async def withdraw_number(msg: types.Message, state: FSMContext):
    data        = await state.get_data()
    card_type   = data["card_type"]
    amount      = data["amount"]
    card_number = msg.text.strip()
    uid         = msg.from_user.id
    user        = await get_user(uid)
    full_name   = user[2] if user else "Noma'lum"

    pay_id = await add_payment(uid, amount, card_type, card_number)
    await msg.answer(
        f"✅ *So'rov yuborildi!*\n\n"
        f"💳 {card_type.upper()}: `{card_number}`\n"
        f"💰 Miqdor: *{amount:,} so'm*\n\n"
        f"Admin tez orada o'tkazadi 🙏",
        reply_markup=kb_main(await is_admin(uid))
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ O'tkazildi", callback_data=f"pa_{pay_id}"),
        types.InlineKeyboardButton("❌ Rad etish",  callback_data=f"pr_{pay_id}")
    )
    await ping_admins(
        f"💳 *Yangi to'lov #{pay_id}*\n\n"
        f"👤 {full_name}\n"
        f"🆔 ID: `{uid}`\n"
        f"💳 {card_type.upper()}: `{card_number}`\n"
        f"💰 *{amount:,} so'm*",
        markup=kb
    )
    await state.finish()

# ══════════════════════════════════════════════════════════
# ADMIN PANEL
# ══════════════════════════════════════════════════════════
@dp.message_handler(lambda m: m.text == "⚙️ Admin panel")
async def cmd_admin(msg: types.Message):
    if not await is_admin(msg.from_user.id):
        return
    total, appr, pend, rej, bal, ppay, umsg = await get_stats()
    await msg.answer(
        f"⚙️ *ADMIN PANEL*\n\n"
        f"👥 Foydalanuvchilar: *{total}*\n"
        f"✅ Tasdiqlangan ovozlar: *{appr}*\n"
        f"⏳ Kutilayotgan ovozlar: *{pend}*\n"
        f"💳 Kutilayotgan to'lovlar: *{ppay}*\n"
        f"📋 O'qilmagan murojaatlar: *{umsg}*\n\n"
        f"Bo'limni tanlang 👇",
        reply_markup=kb_admin()
    )

@dp.message_handler(lambda m: m.text == "🔙 Asosiy menyu")
async def cmd_back(msg: types.Message):
    adm = await is_admin(msg.from_user.id)
    await msg.answer("🏠 *Asosiy menyu*", reply_markup=kb_main(adm))

# ── Statistika ────────────────────────────────────────────
@dp.message_handler(lambda m: m.text == "📊 Statistika")
async def cmd_stats(msg: types.Message):
    if not await is_admin(msg.from_user.id):
        return
    total, appr, pend, rej, bal, ppay, umsg = await get_stats()
    await msg.answer(
        f"📊 *STATISTIKA*\n\n"
        f"👥 Jami foydalanuvchilar: *{total}*\n\n"
        f"🗳 *Ovozlar:*\n"
        f"   ✅ Tasdiqlangan: *{appr}*\n"
        f"   ⏳ Kutilayotgan: *{pend}*\n"
        f"   ❌ Rad etilgan: *{rej}*\n\n"
        f"💰 Jami balans: *{int(bal):,} so'm*\n"
        f"💳 Kutilayotgan to'lovlar: *{ppay}*\n"
        f"📋 O'qilmagan murojaatlar: *{umsg}*"
    )

# ── Loyihalar ─────────────────────────────────────────────
@dp.message_handler(lambda m: m.text == "📁 Loyiha")
async def cmd_projects(msg: types.Message):
    if not await is_admin(msg.from_user.id):
        return
    ps = await get_all_projects()
    add_kb = types.InlineKeyboardMarkup()
    add_kb.add(types.InlineKeyboardButton("➕ Loyiha qo'shish", callback_data="proj_add"))
    if not ps:
        await msg.answer(
            "📁 *LOYIHALAR*\n\nHozircha loyiha yo'q.",
            reply_markup=add_kb
        )
        return
    await msg.answer(
        f"📁 *LOYIHALAR* ({len(ps)} ta)\n\n"
        f"Har bir loyihani alohida boshqarish mumkin:",
        reply_markup=add_kb
    )
    for p in ps:
        pid, name, url, reward, check_url, active, created = p
        st = "✅ Faol" if active else "❌ Nofaol"
        kb = types.InlineKeyboardMarkup(row_width=2)
        if active:
            kb.add(
                types.InlineKeyboardButton("🔴 O'chirish",   callback_data=f"poff_{pid}"),
                types.InlineKeyboardButton("✏️ Mukofot",     callback_data=f"prew_{pid}")
            )
        else:
            kb.add(
                types.InlineKeyboardButton("🟢 Yoqish",      callback_data=f"pon_{pid}"),
                types.InlineKeyboardButton("✏️ Mukofot",     callback_data=f"prew_{pid}")
            )
        kb.add(types.InlineKeyboardButton("🗑 O'chirish", callback_data=f"pdel_{pid}"))
        await msg.answer(
            f"📌 *{name}*\n"
            f"🔗 {url}\n"
            f"💰 Mukofot: *{int(reward):,} so'm*\n"
            f"📍 {st}",
            reply_markup=kb
        )

@dp.callback_query_handler(lambda c: c.data[:4] in ("poff", "pon_", "prew", "pdel"))
async def cb_proj(cb: types.CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id):
        return
    parts = cb.data.split("_")
    act   = parts[0]
    pid   = int(parts[1])
    if act == "poff":
        await toggle_project(pid, 0)
        await cb.answer("🔴 O'chirildi!")
        await cb.message.edit_reply_markup()
    elif act == "pon":
        await toggle_project(pid, 1)
        await cb.answer("🟢 Yoqildi!")
        await cb.message.edit_reply_markup()
    elif act == "prew":
        await state.update_data(rew_pid=pid)
        await cb.message.answer(f"✏️ *Loyiha #{pid}* yangi mukofot (so'mda):")
        await Admin.proj_edit_reward.set()
        await cb.answer()
    elif act == "pdel":
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("✅ Ha, o'chirish", callback_data=f"pdelok_{pid}"),
            types.InlineKeyboardButton("❌ Yo'q",          callback_data="pdelno")
        )
        await cb.message.answer(f"⚠️ Loyiha #{pid} ni o'chirishni tasdiqlaysizmi?", reply_markup=kb)
        await cb.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("pdelok_") or c.data == "pdelno")
async def cb_proj_del_confirm(cb: types.CallbackQuery):
    if not await is_admin(cb.from_user.id):
        return
    if cb.data == "pdelno":
        await cb.message.delete()
        await cb.answer("Bekor qilindi.")
        return
    pid = int(cb.data.split("_")[1])
    await delete_project(pid)
    await cb.message.edit_text(f"🗑 Loyiha #{pid} o'chirildi.")
    await cb.answer("✅ O'chirildi!")

@dp.message_handler(state=Admin.proj_edit_reward)
async def save_proj_reward(msg: types.Message, state: FSMContext):
    if not msg.text.isdigit():
        await msg.answer("❗ Faqat raqam kiriting!")
        return
    data = await state.get_data()
    await update_project_reward(data["rew_pid"], int(msg.text))
    await msg.answer(
        f"✅ Mukofot *{int(msg.text):,} so'm* ga o'zgartirildi!",
        reply_markup=kb_admin()
    )
    await state.finish()

# ── Ovozlar (admin) ───────────────────────────────────────
@dp.message_handler(lambda m: m.text == "📦 Ovozlar")
async def cmd_admin_votes(msg: types.Message):
    if not await is_admin(msg.from_user.id):
        return
    votes = await get_all_votes_admin()
    if not votes:
        await msg.answer("📦 Hozircha ovoz yo'q.")
        return
    STATUS = {
        "pending":       "⏳",
        "approved":      "✅",
        "rejected":      "❌",
        "auto_approved": "✅",
        "auto_rejected": "❌",
    }
    text = "📦 *Oxirgi 50 ta ovoz:*\n\n"
    for v in votes[:20]:
        vid, fname, phone, pname, status, created = v
        text += f"*#{vid}* {STATUS.get(status,'?')} {fname} · {phone[:7]}*** · _{pname}_\n"
    if len(votes) > 20:
        text += f"\n_...va yana {len(votes)-20} ta_"
    await msg.answer(text)

# ── Murojaatlar ───────────────────────────────────────────
@dp.message_handler(lambda m: m.text == "📋 Murojaatlar")
async def cmd_messages(msg: types.Message):
    if not await is_admin(msg.from_user.id):
        return
    msgs = await get_unread_messages()
    if not msgs:
        await msg.answer("📋 *Murojaatlar*\n\n✅ O'qilmagan murojaat yo'q!")
        return
    for m_row in msgs:
        mid, uid, fname, uname, text, created = m_row
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("💬 Javob berish",  callback_data=f"reply_{uid}"),
            types.InlineKeyboardButton("✅ O'qildi",        callback_data=f"mread_{mid}")
        )
        ulink = f"@{uname}" if uname else f"ID:{uid}"
        await msg.answer(
            f"📋 *Murojaat #{mid}*\n\n"
            f"👤 {fname} ({ulink})\n"
            f"🆔 ID: `{uid}`\n\n"
            f"💬 {text}",
            reply_markup=kb
        )

@dp.callback_query_handler(lambda c: c.data.startswith("mread_"))
async def cb_mread(cb: types.CallbackQuery):
    if not await is_admin(cb.from_user.id):
        return
    mid = int(cb.data.split("_")[1])
    await mark_message_read(mid)
    await cb.answer("✅ O'qildi!")
    await cb.message.edit_reply_markup()

# ── Foydalanuvchilar ──────────────────────────────────────
@dp.message_handler(lambda m: m.text == "👥 Foydalanuvchilar")
async def cmd_users(msg: types.Message):
    if not await is_admin(msg.from_user.id):
        return
    users = await get_all_users()
    text  = f"👥 *Foydalanuvchilar ({len(users)} ta)*\n\n"
    for u in users[:20]:
        uid2, uname, fname, phone, balance, is_bl = u
        text += f"{'🚫' if is_bl else '✅'} *{fname}* · 💰{int(balance):,}\n"
    if len(users) > 20:
        text += f"\n_...yana {len(users)-20} ta_"
    await msg.answer(text)

# ── Foydalanuvchi qidirish ────────────────────────────────
@dp.message_handler(lambda m: m.text == "🔍 Foydalanuvchi qidirish")
async def cmd_user_search(msg: types.Message):
    if not await is_admin(msg.from_user.id):
        return
    await msg.answer("🔍 *Foydalanuvchi qidirish*\n\nIsm, username, ID yoki telefon kiriting:")
    await Admin.user_search.set()

@dp.message_handler(state=Admin.user_search)
async def do_user_search(msg: types.Message, state: FSMContext):
    results = await search_user(msg.text.strip())
    if not results:
        await msg.answer("❌ Foydalanuvchi topilmadi!", reply_markup=kb_admin())
        await state.finish()
        return
    text = f"🔍 *Natijalar ({len(results)} ta):*\n\n"
    for u in results[:10]:
        uid2, uname, fname, phone, balance, is_bl = u
        bl = "🚫" if is_bl else "✅"
        ulink = f"@{uname}" if uname else ""
        text += (
            f"{bl} *{fname}* {ulink}\n"
            f"🆔 `{uid2}` · 📱 {phone or '—'} · 💰 {int(balance):,}\n\n"
        )
    kb = types.InlineKeyboardMarkup(row_width=1)
    if len(results) == 1:
        uid2 = results[0][0]
        kb.add(types.InlineKeyboardButton("👤 Batafsil ko'rish", callback_data=f"uview_{uid2}"))
    await msg.answer(text, reply_markup=kb)
    await state.finish()

@dp.callback_query_handler(lambda c: c.data.startswith("uview_"))
async def cb_user_view(cb: types.CallbackQuery):
    if not await is_admin(cb.from_user.id):
        return
    uid  = int(cb.data.split("_")[1])
    user = await get_user(uid)
    if not user:
        await cb.answer("Topilmadi!")
        return
    uid2, uname, fname, phone, balance, total_earn, ref_id, is_bl, joined = user
    votes  = await get_user_votes(uid)
    ok_v   = sum(1 for v in votes if v[3] in ("approved", "auto_approved"))
    ref_c  = await get_referral_count(uid)
    lvl, _, _ = get_level(ok_v)

    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("💬 DM yuborish",       callback_data=f"dm_{uid}"),
        types.InlineKeyboardButton("🚫 Blokla" if not is_bl else "✅ Blokdan chiqar",
                                    callback_data=f"{'ublk' if is_bl else 'blk'}_{uid}")
    )
    kb.add(types.InlineKeyboardButton("💰 Balans tahrirlash", callback_data=f"ebal_{uid}"))

    await cb.message.answer(
        f"👤 *Foydalanuvchi paneli*\n"
        f"{'━' * 22}\n"
        f"🆔 ID: `{uid2}`\n"
        f"👤 Ism: *{fname}*\n"
        f"📱 Tel: {phone or '—'}\n"
        f"🏅 Daraja: *{lvl}*\n"
        f"{'🚫 BLOKLANGAN' if is_bl else '✅ Faol'}\n\n"
        f"💰 Balans: *{int(balance):,} so'm*\n"
        f"📈 Jami ishlagan: *{int(total_earn or 0):,} so'm*\n"
        f"🗳 OK ovozlar: *{ok_v}* ta\n"
        f"👥 Taklif qilganlari: *{ref_c}* ta",
        reply_markup=kb
    )
    await cb.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("blk_") or c.data.startswith("ublk_"))
async def cb_toggle_block(cb: types.CallbackQuery):
    if not await is_admin(cb.from_user.id):
        return
    action = "block" if cb.data.startswith("blk_") else "unblock"
    uid    = int(cb.data.split("_")[1])
    if action == "block":
        await block_user(uid)
        await cb.answer("🚫 Bloklandi!")
        try:
            await bot.send_message(uid, "🚫 Siz botdan bloklangansiz.\nMurojaat uchun adminga yozing.")
        except Exception:
            pass
    else:
        await unblock_user(uid)
        await cb.answer("✅ Blokdan chiqarildi!")
        try:
            await bot.send_message(uid, "✅ Blok olib tashlandi. /start bosing.")
        except Exception:
            pass

@dp.callback_query_handler(lambda c: c.data.startswith("dm_"))
async def cb_dm_user(cb: types.CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id):
        return
    uid = int(cb.data.split("_")[1])
    await state.update_data(dm_uid=uid)
    await cb.message.answer(f"💬 `{uid}` ga xabar yuboring:")
    await Admin.dm_text.set()
    await cb.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("ebal_"))
async def cb_edit_balance(cb: types.CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id):
        return
    uid = int(cb.data.split("_")[1])
    await state.update_data(setbal_uid=uid)
    bal = await get_balance(uid)
    kb = types.InlineKeyboardMarkup(row_width=3)
    kb.add(
        types.InlineKeyboardButton("➕ Qo'shish",  callback_data=f"badd_{uid}"),
        types.InlineKeyboardButton("➖ Ayirish",   callback_data=f"bsub_{uid}"),
        types.InlineKeyboardButton("✏️ Belgilash", callback_data=f"bset_{uid}")
    )
    await cb.message.answer(
        f"💰 *Balans tahrirlash*\n\n"
        f"🆔 ID: `{uid}`\n"
        f"💵 Hozirgi balans: *{int(bal):,} so'm*\n\n"
        f"Amalni tanlang:",
        reply_markup=kb
    )
    await cb.answer()

@dp.callback_query_handler(lambda c: c.data[:4] in ("badd", "bsub", "bset"))
async def cb_bal_action(cb: types.CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id):
        return
    act = cb.data[:4]
    uid = int(cb.data.split("_")[1])
    await state.update_data(bal_uid=uid, bal_act=act)
    labels = {"badd": "qo'shish", "bsub": "ayirish", "bset": "belgilash"}
    await cb.message.answer(f"💰 Miqdorni kiriting ({labels[act]}):")
    if act == "badd":
        await Admin.addbal_amount.set()
    elif act == "bsub":
        await Admin.subbal_amount.set()
    else:
        await Admin.setbal_amount.set()
    await cb.answer()

@dp.message_handler(state=Admin.addbal_amount)
async def addbal_amount(msg: types.Message, state: FSMContext):
    if not msg.text.isdigit():
        await msg.answer("❗ Faqat raqam kiriting!")
        return
    data   = await state.get_data()
    uid    = data.get("bal_uid") or data.get("addbal_uid") or data.get("tuid")
    amount = int(msg.text)
    await add_balance(uid, amount)
    await msg.answer(f"✅ `{uid}` ga *{amount:,} so'm* qo'shildi!", reply_markup=kb_admin())
    try:
        await bot.send_message(uid,
            f"🎁 *Admin tomonidan bonus!*\n\nHisobingizga *{amount:,} so'm* qo'shildi 💰")
    except Exception:
        pass
    await state.finish()

@dp.message_handler(state=Admin.subbal_amount)
async def subbal_amount(msg: types.Message, state: FSMContext):
    if not msg.text.isdigit():
        await msg.answer("❗ Faqat raqam kiriting!")
        return
    data   = await state.get_data()
    uid    = data.get("bal_uid")
    amount = int(msg.text)
    await subtract_balance(uid, amount)
    await msg.answer(f"✅ `{uid}` dan *{amount:,} so'm* ayirildi!", reply_markup=kb_admin())
    await state.finish()

@dp.message_handler(state=Admin.setbal_amount)
async def setbal_amount(msg: types.Message, state: FSMContext):
    if not msg.text.isdigit():
        await msg.answer("❗ Faqat raqam kiriting!")
        return
    data   = await state.get_data()
    uid    = data.get("bal_uid")
    amount = int(msg.text)
    await set_balance_direct(uid, amount)
    await msg.answer(f"✅ `{uid}` balansi *{amount:,} so'm* ga belgilandi!", reply_markup=kb_admin())
    await state.finish()

# ── Bloklash (to'g'ridan-to'g'ri) ────────────────────────
@dp.message_handler(lambda m: m.text == "🚫 Bloklash")
async def cmd_block(msg: types.Message):
    if not await is_admin(msg.from_user.id):
        return
    await msg.answer("🚫 Bloklash uchun foydalanuvchi *ID-ini* kiriting:")
    await Admin.block_id.set()

@dp.message_handler(state=Admin.block_id)
async def do_block(msg: types.Message, state: FSMContext):
    if not msg.text.isdigit():
        await msg.answer("❗ Faqat ID kiriting!")
        return
    uid = int(msg.text)
    await block_user(uid)
    await msg.answer(f"🚫 `{uid}` bloklandi!", reply_markup=kb_admin())
    try:
        await bot.send_message(uid, "🚫 Siz botdan bloklangansiz.\nMurojaat uchun adminga yozing.")
    except Exception:
        pass
    await state.finish()

# ── DM yuborish ───────────────────────────────────────────
@dp.message_handler(lambda m: m.text == "💬 DM yuborish")
async def cmd_dm(msg: types.Message):
    if not await is_admin(msg.from_user.id):
        return
    await msg.answer("💬 *DM yuborish*\n\nFoydalanuvchi *ID-ini* kiriting:")
    await Admin.dm_uid.set()

@dp.message_handler(state=Admin.dm_uid)
async def dm_uid_step(msg: types.Message, state: FSMContext):
    if not msg.text.isdigit():
        await msg.answer("❗ Faqat ID kiriting!")
        return
    await state.update_data(dm_uid=int(msg.text))
    await msg.answer("💬 Yuboriladigan xabarni kiriting:")
    await Admin.dm_text.set()

@dp.message_handler(state=Admin.dm_text)
async def dm_text_step(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    uid  = data["dm_uid"]
    try:
        await bot.send_message(uid, f"📩 *Admin xabari:*\n\n{msg.text}")
        await msg.answer(f"✅ `{uid}` ga xabar yuborildi!", reply_markup=kb_admin())
    except Exception as e:
        await msg.answer(f"❌ Xabar yuborishda xato: {e}", reply_markup=kb_admin())
    await state.finish()

# ── To'lov sozlash ────────────────────────────────────────
@dp.message_handler(lambda m: m.text == "💰 To'lov sozlash")
async def cmd_pay_settings(msg: types.Message):
    if not await is_admin(msg.from_user.id):
        return
    vr   = int(await get("vote_reward"))
    rr   = int(await get("referral_reward"))
    minw = int(await get("min_withdraw"))
    maxw = int(await get("max_withdraw"))
    uz   = await get("uzcard_number")
    hu   = await get("humo_number")
    cl   = await get("click_number")
    pm   = await get("payme_number")

    kb = types.InlineKeyboardMarkup(row_width=1)
    for label, key in [
        ("💰 Ovoz mukofoti",     "vote_reward"),
        ("👥 Referral mukofoti", "referral_reward"),
        ("📤 Min yechish",       "min_withdraw"),
        ("📤 Max yechish",       "max_withdraw"),
        ("💳 Uzcard raqami",     "uzcard_number"),
        ("💳 Humo raqami",       "humo_number"),
        ("💚 Click raqami",      "click_number"),
        ("🔴 Payme raqami",      "payme_number"),
    ]:
        kb.add(types.InlineKeyboardButton(label, callback_data=f"ss_{key}"))

    await msg.answer(
        f"💰 *TO'LOV SOZLAMALARI*\n\n"
        f"💰 Ovoz mukofoti: *{vr:,} so'm*\n"
        f"👥 Referral: *{rr:,} so'm*\n"
        f"📤 Min: *{minw:,}*  ·  Max: *{maxw:,} so'm*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💳 Uzcard: {uz or '—'}\n"
        f"💳 Humo:   {hu or '—'}\n"
        f"💚 Click:  {cl or '—'}\n"
        f"🔴 Payme:  {pm or '—'}\n\n"
        f"O'zgartirish uchun tugmani bosing 👇",
        reply_markup=kb
    )

# ── Sozlamalar ────────────────────────────────────────────
@dp.message_handler(lambda m: m.text == "⚙️ Sozlamalar")
async def cmd_settings(msg: types.Message):
    if not await is_admin(msg.from_user.id):
        return
    kb = types.InlineKeyboardMarkup(row_width=1)
    for label, key in [
        ("👋 Xush kelibsiz matni", "welcome_text"),
        ("ℹ️ Bot haqida matni",    "about_text"),
        ("📢 Majburiy kanal",      "channel"),
    ]:
        kb.add(types.InlineKeyboardButton(label, callback_data=f"ss_{key}"))
    await msg.answer("⚙️ *SOZLAMALAR*\n\nO'zgartirish uchun tugmani bosing 👇", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("ss_"))
async def cb_setting(cb: types.CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id):
        return
    key = cb.data[3:]
    cur = await get(key)
    await state.update_data(skey=key)
    await cb.message.answer(
        f"✏️ *{key}*\n\nHozirgi: `{cur[:100] if cur else 'Boʻsh'}`\n\nYangi qiymatni kiriting:"
    )
    await Admin.setting_val.set()
    await cb.answer()

@dp.message_handler(state=Admin.setting_val)
async def save_setting(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    await set_setting(data["skey"], msg.text.strip())
    await msg.answer(f"✅ *{data['skey']}* yangilandi!", reply_markup=kb_admin())
    await state.finish()

# ── Kanallar ─────────────────────────────────────────────
@dp.message_handler(lambda m: m.text == "📡 Kanallar")
async def cmd_channels(msg: types.Message):
    if not await is_admin(msg.from_user.id):
        return
    chs = await get_all_channels()
    kb  = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("➕ Kanal qo'shish", callback_data="ch_add"))

    if chs:
        text = "📡 *Kanallar ro'yxati:*\n\n"
        for ch in chs:
            cid, uname, title, active, added = ch
            st = "✅" if active else "❌"
            text += f"{st} *{title}* ({uname})\n"
            row_kb = types.InlineKeyboardMarkup(row_width=3)
            if active:
                row_kb.add(
                    types.InlineKeyboardButton("🔴 O'chirish",  callback_data=f"choff_{cid}"),
                    types.InlineKeyboardButton("🗑 O'chirish",  callback_data=f"chdel_{cid}")
                )
            else:
                row_kb.add(
                    types.InlineKeyboardButton("🟢 Yoqish",    callback_data=f"chon_{cid}"),
                    types.InlineKeyboardButton("🗑 O'chirish",  callback_data=f"chdel_{cid}")
                )
            await msg.answer(f"{st} *{title}*\n{uname}", reply_markup=row_kb)
    else:
        text = "📡 Hozircha kanal yo'q."

    await msg.answer(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == "ch_add")
async def cb_ch_add(cb: types.CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id):
        return
    await cb.message.answer(
        "➕ *Yangi kanal qo'shish*\n\n"
        "Kanal username ni kiriting:\n"
        "_Namuna: @mening_kanal_"
    )
    await Admin.channel_add.set()
    await cb.answer()

@dp.message_handler(state=Admin.channel_add)
async def save_channel(msg: types.Message, state: FSMContext):
    uname = msg.text.strip()
    if not uname.startswith("@"):
        uname = "@" + uname
    try:
        chat  = await bot.get_chat(uname)
        title = chat.title or uname
        await add_channel(uname, title)
        await msg.answer(f"✅ Kanal *{title}* ({uname}) qo'shildi!", reply_markup=kb_admin())
    except Exception as e:
        await msg.answer(f"❌ Kanal topilmadi: {e}\n\nBot kanalga admin bo'lishi kerak!", reply_markup=kb_admin())
    await state.finish()

@dp.callback_query_handler(lambda c: c.data[:4] in ("chof", "chon", "chde"))
async def cb_channel_action(cb: types.CallbackQuery):
    if not await is_admin(cb.from_user.id):
        return
    parts = cb.data.split("_")
    act   = parts[0]
    cid   = int(parts[1])
    if act == "choff":
        await toggle_channel(cid, 0)
        await cb.answer("🔴 O'chirildi!")
    elif act == "chon":
        await toggle_channel(cid, 1)
        await cb.answer("🟢 Yoqildi!")
    elif act == "chdel":
        await delete_channel(cid)
        await cb.answer("🗑 O'chirildi!")
    await cb.message.edit_reply_markup()

# ── Adminlar ──────────────────────────────────────────────
@dp.message_handler(lambda m: m.text == "👮 Adminlar")
async def cmd_admins(msg: types.Message):
    if not await is_admin(msg.from_user.id):
        return
    admins = await get_admins()
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("➕ Admin qo'shish", callback_data="adm_add"))
    for a in admins:
        kb.add(types.InlineKeyboardButton(
            f"❌ {a[1]} — o'chirish", callback_data=f"adm_del_{a[0]}"
        ))
    text = f"👮 *ADMINLAR*\n\n👑 Super admin: `{SUPER_ADMIN}`\n\n"
    text += "\n".join(f"👮 *{a[1]}* | `{a[0]}`" for a in admins) if admins else "_Qo'shimcha admin yo'q_"
    await msg.answer(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == "adm_add")
async def cb_adm_add(cb: types.CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id):
        return
    await cb.message.answer("➕ *Yangi admin*\n\nAdmin Telegram ID-ini kiriting:")
    await Admin.add_admin_id.set()
    await cb.answer()

@dp.message_handler(state=Admin.add_admin_id)
async def save_admin_handler(msg: types.Message, state: FSMContext):
    if not msg.text.isdigit():
        await msg.answer("❗ Faqat ID kiriting!")
        return
    uid = int(msg.text)
    try:
        c    = await bot.get_chat(uid)
        name = c.full_name
    except Exception:
        name = f"ID:{uid}"
    await add_admin(uid, name)
    await msg.answer(f"✅ *{name}* admin qo'shildi!", reply_markup=kb_admin())
    try:
        await bot.send_message(uid, "🎉 Siz bot admini sifatida qo'shildingiz!")
    except Exception:
        pass
    await state.finish()

@dp.callback_query_handler(lambda c: c.data.startswith("adm_del_"))
async def cb_adm_del(cb: types.CallbackQuery):
    if cb.from_user.id != SUPER_ADMIN:
        await cb.answer("Faqat super admin o'chirishi mumkin!")
        return
    uid = int(cb.data.split("_")[2])
    await remove_admin(uid)
    await cb.answer("✅ Admin o'chirildi!")
    await cb.message.edit_reply_markup()

# ── Broadcast ─────────────────────────────────────────────
@dp.message_handler(lambda m: m.text == "📣 Xabar yuborish")
async def cmd_broadcast(msg: types.Message):
    if not await is_admin(msg.from_user.id):
        return
    await msg.answer("📣 *Barcha foydalanuvchilarga xabar*\n\nXabarni kiriting:")
    await Admin.broadcast.set()

@dp.message_handler(state=Admin.broadcast)
async def do_broadcast(msg: types.Message, state: FSMContext):
    users    = await get_all_users()
    sent = failed = 0
    prog = await msg.answer(f"📣 Yuborilmoqda... 0/{len(users)}")
    for u in users:
        try:
            await bot.send_message(u[0], msg.text)
            sent += 1
        except Exception:
            failed += 1
        if (sent + failed) % 20 == 0:
            try:
                await bot.edit_message_text(
                    f"📣 Yuborilmoqda... {sent+failed}/{len(users)}",
                    msg.chat.id, prog.message_id
                )
            except Exception:
                pass
        await asyncio.sleep(0.05)
    await bot.edit_message_text(
        f"📣 *Yakunlandi!*\n✅ Yuborildi: {sent}\n❌ Xato: {failed}",
        msg.chat.id, prog.message_id
    )
    await state.finish()

@dp.callback_query_handler(lambda c: c.data == "proj_add")
async def cb_proj_add(cb: types.CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id):
        return
    await cb.message.answer("➕ *Yangi loyiha*\n\nLoyiha nomini kiriting:")
    await Admin.proj_name.set()
    await cb.answer()

@dp.message_handler(lambda m: m.text in ("📁 Loyiha qo'shish", "➕ Loyiha qo'shish"))
async def cmd_add_proj(msg: types.Message):
    if not await is_admin(msg.from_user.id):
        return
    await msg.answer("➕ *Yangi loyiha*\n\nLoyiha nomini kiriting:")
    await Admin.proj_name.set()

@dp.message_handler(state=Admin.proj_name)
async def ap_name(msg: types.Message, state: FSMContext):
    await state.update_data(pname=msg.text.strip())
    await msg.answer("🔗 Ovoz berish URL-ini kiriting:")
    await Admin.proj_url.set()

@dp.message_handler(state=Admin.proj_url)
async def ap_url(msg: types.Message, state: FSMContext):
    await state.update_data(purl=msg.text.strip())
    await msg.answer("💰 Mukofot miqdorini kiriting (so'mda):")
    await Admin.proj_reward.set()

@dp.message_handler(state=Admin.proj_reward)
async def ap_reward(msg: types.Message, state: FSMContext):
    if not msg.text.isdigit():
        await msg.answer("❗ Faqat raqam kiriting!")
        return
    await state.update_data(preward=msg.text.strip())
    await msg.answer("🔍 Natijalar tekshirish URL-ini kiriting:")
    await Admin.proj_check.set()

@dp.message_handler(state=Admin.proj_check)
async def ap_check(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    await add_project(data["pname"], data["purl"], int(data["preward"]), msg.text.strip())
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(
        f"🗳 {data['pname']} — Ovoz berish", url=data["purl"]
    ))
    await msg.answer(
        f"✅ *Loyiha qo'shildi!*\n\n"
        f"📌 *{data['pname']}*\n"
        f"💰 Mukofot: *{int(data['preward']):,} so'm*\n\n"
        f"Ovoz berish havolasi 👇",
        reply_markup=kb
    )
    await msg.answer("Admin panel 👇", reply_markup=kb_admin())
    await state.finish()

# ── Excel export ──────────────────────────────────────────
@dp.message_handler(lambda m: m.text == "📂 Excel export")
async def cmd_export(msg: types.Message):
    if not await is_admin(msg.from_user.id):
        return
    wait = await msg.answer("⏳ *Fayl tayyorlanmoqda...*")
    try:
        csv_data = await export_users_csv()
        fname    = f"users_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        await bot.send_document(
            msg.chat.id,
            types.InputFile(io.BytesIO(csv_data), filename=fname),
            caption=f"📂 *Foydalanuvchilar eksporti*\n📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
        await bot.delete_message(msg.chat.id, wait.message_id)
    except Exception as e:
        await bot.edit_message_text(f"❌ Xato: {e}", msg.chat.id, wait.message_id)

# ── Balans tahrirlash (to'g'ridan-to'g'ri) ───────────────
@dp.message_handler(lambda m: m.text == "💵 Balans tahrirlash")
async def cmd_bal_edit(msg: types.Message):
    if not await is_admin(msg.from_user.id):
        return
    await msg.answer(
        "💵 *Balans tahrirlash*\n\n"
        "Foydalanuvchi *ID-ini* kiriting:"
    )
    await Admin.addbal_uid.set()

@dp.message_handler(state=Admin.addbal_uid)
async def addbal_uid_step(msg: types.Message, state: FSMContext):
    if not msg.text.isdigit():
        await msg.answer("❗ Faqat ID kiriting!")
        return
    uid = int(msg.text)
    bal = await get_balance(uid)
    await state.update_data(tuid=uid, bal_uid=uid)
    kb = types.InlineKeyboardMarkup(row_width=3)
    kb.add(
        types.InlineKeyboardButton("➕ Qo'shish",  callback_data=f"badd_{uid}"),
        types.InlineKeyboardButton("➖ Ayirish",   callback_data=f"bsub_{uid}"),
        types.InlineKeyboardButton("✏️ Belgilash", callback_data=f"bset_{uid}")
    )
    await msg.answer(
        f"💵 ID: `{uid}`\n"
        f"💰 Hozirgi balans: *{int(bal):,} so'm*\n\n"
        f"Amalni tanlang:",
        reply_markup=kb
    )
    await state.finish()

# ── Foydalanuvchi paneli ──────────────────────────────────
@dp.message_handler(lambda m: m.text == "👤 Foydalanuvchi paneli")
async def cmd_user_panel(msg: types.Message):
    if not await is_admin(msg.from_user.id):
        return
    await msg.answer(
        "👤 *Foydalanuvchi paneli*\n\n"
        "Foydalanuvchi *ID-ini* kiriting:"
    )
    await Admin.user_search.set()

# ── Kutilayotgan to'lovlar ────────────────────────────────
@dp.message_handler(lambda m: m.text in ("💳 To'lovlar", "💳 To'lov sozlash"))
async def cmd_payments(msg: types.Message):
    if not await is_admin(msg.from_user.id):
        return
    # Agar "To'lov sozlash" bo'lsa sozlamalarga yo'naltir
    if msg.text == "💰 To'lov sozlash":
        await cmd_pay_settings(msg)
        return
    pays = await get_pending_payments()
    if not pays:
        await msg.answer("💳 *TO'LOVLAR*\n\n✅ Kutilayotgan to'lov yo'q!")
        return
    for p in pays:
        pid, uid, amount, card_type, card_number, status, created, fname, uname = p
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("✅ O'tkazildi", callback_data=f"pa_{pid}"),
            types.InlineKeyboardButton("❌ Rad etish",  callback_data=f"pr_{pid}")
        )
        await msg.answer(
            f"💳 *To'lov #{pid}*\n\n"
            f"👤 {fname}\n"
            f"🆔 ID: `{uid}`\n"
            f"💳 {card_type.upper()}: `{card_number}`\n"
            f"💰 *{int(amount):,} so'm*",
            reply_markup=kb
        )

# ══════════════════════════════════════════════════════════
# HEALTH CHECK (Koyeb)
# ══════════════════════════════════════════════════════════
async def health_server():
    from aiohttp import web
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="OK"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8000).start()
    logger.info("Health check: port 8000 ✅")

# ══════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════
if __name__ == "__main__":
    async def on_startup(_dp):
        await init_db()
        await health_server()
        logger.info("Bot ishga tushdi ✅")

    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
