import asyncio
import logging
import aiohttp
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage

from database import *
from site_worker import submit_phone, submit_sms_code, check_vote_result

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

BOT_TOKEN  = "8679118861:AAES2RZz_HdxuZWhqi9pVSWxIl5yiL1oL2U"  # <-- O'z tokeningni qo'y
SUPER_ADMIN = 6498632307              # <-- O'z Telegram ID-ingni qo'y (hech qachon o'chirmaydi)

bot     = Bot(token=BOT_TOKEN, parse_mode="Markdown")
storage = MemoryStorage()
dp      = Dispatcher(bot, storage=storage)

sessions = {}  # user_id: aiohttp.ClientSession

# ══════════════════════════════════════════════════════════
# STATES
# ══════════════════════════════════════════════════════════
class VoteState(StatesGroup):
    choose_project  = State()
    enter_phone     = State()
    enter_sms       = State()

class WithdrawState(StatesGroup):
    enter_amount = State()
    choose_card  = State()
    enter_card   = State()

class AdminState(StatesGroup):
    broadcast         = State()
    add_project_name  = State()
    add_project_url   = State()
    add_project_reward= State()
    add_project_check = State()
    add_admin_id      = State()
    edit_setting_key  = State()
    edit_setting_val  = State()
    block_user_id     = State()
    unblock_user_id   = State()

# ══════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════
async def check_admin(user_id: int) -> bool:
    return user_id == SUPER_ADMIN or await is_admin_db(user_id)

async def check_subscription(user_id: int) -> bool:
    channel = await get("channel")
    if not channel:
        return True
    try:
        member = await bot.get_chat_member(channel, user_id)
        return member.status not in ("left", "kicked")
    except Exception:
        return False

def main_kb(is_admin: bool = False) -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        types.KeyboardButton("🗳 Ovoz berish"),
        types.KeyboardButton("💰 Balansim"),
    )
    kb.add(
        types.KeyboardButton("🔗 Do'st taklif qilish"),
        types.KeyboardButton("💳 Pul yechish"),
    )
    kb.add(
        types.KeyboardButton("📊 Ovozlarim"),
        types.KeyboardButton("ℹ️ Bot haqida"),
    )
    if is_admin:
        kb.add(types.KeyboardButton("⚙️ Admin panel"))
    return kb

def admin_kb() -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        types.KeyboardButton("📊 Statistika"),
        types.KeyboardButton("📁 Loyihalar"),
    )
    kb.add(
        types.KeyboardButton("➕ Loyiha qo'shish"),
        types.KeyboardButton("👥 Foydalanuvchilar"),
    )
    kb.add(
        types.KeyboardButton("💳 To'lovlar"),
        types.KeyboardButton("📢 Xabar yuborish"),
    )
    kb.add(
        types.KeyboardButton("👮 Adminlar"),
        types.KeyboardButton("⚙️ Sozlamalar"),
    )
    kb.add(types.KeyboardButton("🔙 Asosiy menyu"))
    return kb

async def notify_admins(text: str, reply_markup=None):
    admins = await get_admins()
    admin_ids = [SUPER_ADMIN] + [a[0] for a in admins]
    for aid in set(admin_ids):
        try:
            await bot.send_message(aid, text, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Admin {aid} ga xabar yuborishda xato: {e}")

# ══════════════════════════════════════════════════════════
# OBUNA TEKSHIRISH MIDDLEWARE
# ══════════════════════════════════════════════════════════
async def subscription_wall(message: types.Message) -> bool:
    """False qaytarsa — user obuna emas, xabar yuborildi"""
    if await check_subscription(message.from_user.id):
        return True
    channel = await get("channel")
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📢 Kanalga obuna bo'lish", url=f"https://t.me/{channel.replace('@','')}"))
    kb.add(types.InlineKeyboardButton("✅ Obuna bo'ldim", callback_data="check_sub"))
    await message.answer(
        "⚠️ *Botdan foydalanish uchun kanalga obuna bo'ling!*\n\n"
        f"📢 Kanal: {channel}\n\n"
        "Obuna bo'lgandan so'ng *✅ Obuna bo'ldim* tugmasini bosing.",
        reply_markup=kb
    )
    return False

@dp.callback_query_handler(lambda c: c.data == "check_sub")
async def check_sub_callback(callback: types.CallbackQuery):
    if await check_subscription(callback.from_user.id):
        await callback.message.delete()
        user = callback.from_user
        is_adm = await check_admin(user.id)
        welcome = await get("welcome_text")
        await callback.message.answer(
            welcome.format(name=user.first_name),
            reply_markup=main_kb(is_adm)
        )
    else:
        channel = await get("channel")
        await callback.answer(
            f"Hali obuna bo'lmagansiz! {channel} kanaliga obuna bo'ling.",
            show_alert=True
        )

# ══════════════════════════════════════════════════════════
# /START
# ══════════════════════════════════════════════════════════
@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message, state: FSMContext):
    await state.finish()
    user = message.from_user
    args = message.get_args()
    ref_id = int(args) if args and args.isdigit() and int(args) != user.id else None
    await add_user(user.id, user.username, user.full_name, ref_id)

    if await is_blocked(user.id):
        await message.answer("🚫 Siz botdan bloklangansiz. Adminga murojaat qiling.")
        return

    if not await subscription_wall(message):
        return

    is_adm = await check_admin(user.id)
    welcome = await get("welcome_text")
    await message.answer(
        welcome.format(name=user.first_name),
        reply_markup=main_kb(is_adm)
    )

# ══════════════════════════════════════════════════════════
# BOT HAQIDA
# ══════════════════════════════════════════════════════════
@dp.message_handler(lambda m: m.text == "ℹ️ Bot haqida")
async def about(message: types.Message):
    if not await subscription_wall(message):
        return
    reward     = int(await get("vote_reward"))
    ref_reward = int(await get("referral_reward"))
    min_w      = int(await get("min_withdraw"))
    max_w      = int(await get("max_withdraw"))
    text       = await get("about_text")
    await message.answer(
        f"{text}\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💰 Ovoz mukofoti: *{reward:,} so'm*\n"
        f"👥 Referral bonus: *{ref_reward:,} so'm*\n"
        f"📤 Min yechish: *{min_w:,} so'm*\n"
        f"📤 Max yechish: *{max_w:,} so'm*"
    )

# ══════════════════════════════════════════════════════════
# OVOZ BERISH
# ══════════════════════════════════════════════════════════
@dp.message_handler(lambda m: m.text == "🗳 Ovoz berish")
async def vote_start(message: types.Message, state: FSMContext):
    if not await subscription_wall(message):
        return
    if await is_blocked(message.from_user.id):
        await message.answer("🚫 Siz botdan bloklangansiz.")
        return

    projects = await get_active_projects()
    if not projects:
        await message.answer(
            "⏳ *Hozircha faol loyiha yo'q*\n\n"
            "Tez orada yangi loyihalar qo'shiladi. Kuting!"
        )
        return

    kb = types.InlineKeyboardMarkup(row_width=1)
    for p in projects:
        pid, name, url, reward, check_url, is_active, created = p
        kb.add(types.InlineKeyboardButton(
            f"📌 {name}  |  💰 {int(reward):,} so'm",
            callback_data=f"vote_{pid}"
        ))

    await message.answer(
        "🗳 *Ovoz berish*\n\n"
        "Quyidagi loyihalardan birini tanlang 👇",
        reply_markup=kb
    )
    await VoteState.choose_project.set()

@dp.callback_query_handler(lambda c: c.data.startswith("vote_"), state=VoteState.choose_project)
async def vote_project_chosen(callback: types.CallbackQuery, state: FSMContext):
    pid     = int(callback.data.split("_")[1])
    project = await get_project(pid)
    if not project:
        await callback.answer("Loyiha topilmadi!")
        return

    pid, name, vote_url, reward, check_url, is_active, created = project
    await state.update_data(project_id=pid, project=project)

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(f"🔗 {name} saytiga o'tish", url=vote_url))

    await callback.message.answer(
        f"📌 *{name}*\n"
        f"💰 Mukofot: *{int(reward):,} so'm*\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📋 *Qanday ovoz berish kerak:*\n"
        f"1️⃣ Quyidagi tugmani bosib saytga o'ting\n"
        f"2️⃣ Saytda ovoz bering\n"
        f"3️⃣ Qaytib kelib telefon raqamingizni yozing\n\n"
        f"📱 *Telefon raqamingizni kiriting:*\n"
        f"_Namuna: +998901234567_",
        reply_markup=kb
    )
    await VoteState.enter_phone.set()
    await callback.answer()

@dp.message_handler(state=VoteState.enter_phone)
async def vote_enter_phone(message: types.Message, state: FSMContext):
    phone = message.text.strip().replace(" ", "").replace("-", "")
    if not phone.replace("+", "").isdigit() or len(phone.replace("+", "")) < 9:
        await message.answer(
            "❗ *Noto'g'ri format!*\n\n"
            "Qaytadan kiriting:\n"
            "_Namuna: +998901234567_"
        )
        return

    if not phone.startswith("+"):
        phone = "+" + ("998" + phone[-9:] if not phone.startswith("998") else phone)

    await state.update_data(phone=phone)
    data    = await state.get_data()
    project = data.get("project")
    pid, name, vote_url, reward, check_url, is_active, created = project

    processing_msg = await message.answer("⏳ *Saytga ulanmoqda...*")

    session              = aiohttp.ClientSession()
    sessions[message.from_user.id] = session
    success, html        = await submit_phone(session, vote_url, phone)

    await bot.delete_message(message.chat.id, processing_msg.message_id)

    if success:
        await message.answer(
            f"✅ *SMS kod yuborildi!*\n\n"
            f"📱 Raqam: `{phone}`\n\n"
            f"📩 *Telefoningizga kelgan kodni kiriting:*"
        )
    else:
        await session.close()
        sessions.pop(message.from_user.id, None)
        await state.update_data(manual_mode=True)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(f"🔗 {name} saytiga o'tish", url=vote_url))
        await message.answer(
            f"📌 *{name}*\n\n"
            f"⚠️ Saytga avtomatik ulanishda muammo bo'ldi.\n\n"
            f"📋 *Qo'lda bajaring:*\n"
            f"1️⃣ Quyidagi tugmani bosib saytga o'ting\n"
            f"2️⃣ Telefon raqamingizni saytga kiriting\n"
            f"3️⃣ SMS kelganidan so'ng kodni bu yerga yuboring\n\n"
            f"📩 *SMS kodini kiriting:*",
            reply_markup=kb
        )
    await VoteState.enter_sms.set()

@dp.message_handler(state=VoteState.enter_sms)
async def vote_enter_sms(message: types.Message, state: FSMContext):
    code = message.text.strip()
    if not code.isdigit() or len(code) < 4:
        await message.answer("❗ *Noto'g'ri kod!* Qaytadan kiriting:")
        return

    data        = await state.get_data()
    phone       = data.get("phone")
    project     = data.get("project")
    manual_mode = data.get("manual_mode", False)
    pid, name, vote_url, reward, check_url, is_active, created = project

    if not manual_mode:
        session = sessions.get(message.from_user.id)
        if session:
            await submit_sms_code(session, vote_url, phone, code)
            await session.close()
            sessions.pop(message.from_user.id, None)

    user_id  = message.from_user.id
    vote_id  = await add_vote(user_id, phone, pid)
    await set_phone(user_id, phone)

    check_time = (datetime.now() + timedelta(hours=1)).strftime("%H:%M")

    await message.answer(
        f"✅ *Ovozingiz qabul qilindi!*\n\n"
        f"📱 Raqam: `{phone}`\n"
        f"📌 Loyiha: *{name}*\n"
        f"⏰ Tekshirish vaqti: *{check_time}*\n\n"
        f"🔍 1 soatdan keyin ovozingiz tekshiriladi.\n"
        f"Tasdiqlansa — *{int(reward):,} so'm* hisobingizga o'tkaziladi 💰",
        reply_markup=main_kb(await check_admin(user_id))
    )

    # Adminlarga xabar
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"vapprove_{vote_id}"),
        types.InlineKeyboardButton("❌ Rad etish",  callback_data=f"vreject_{vote_id}")
    )
    await notify_admins(
        f"🗳 *Yangi ovoz so'rovi #{vote_id}*\n\n"
        f"👤 Foydalanuvchi: {message.from_user.full_name}\n"
        f"🆔 ID: `{user_id}`\n"
        f"📱 Raqam: `{phone}`\n"
        f"📌 Loyiha: *{name}*\n"
        f"🔢 SMS kod: `{code}`",
        reply_markup=kb
    )

    asyncio.create_task(
        auto_check_vote(vote_id, user_id, phone, check_url, reward, name)
    )
    await state.finish()

async def auto_check_vote(vote_id, user_id, phone, check_url, reward, project_name):
    await asyncio.sleep(3600)
    vote = await get_vote(vote_id)
    if not vote or vote[4] != "pending":
        return

    found = await check_vote_result(phone, check_url, "")

    if found:
        await update_vote_status(vote_id, "auto_approved")
        await add_balance(user_id, int(reward))

        ref_id = await get_referral_id(user_id)
        if ref_id:
            ref_reward = int(await get("referral_reward"))
            await add_balance(ref_id, ref_reward)
            try:
                await bot.send_message(
                    ref_id,
                    f"🎉 *Do'stingizning ovozi tasdiqlandi!*\n\n"
                    f"Hisobingizga *{ref_reward:,} so'm* qo'shildi 💰"
                )
            except Exception:
                pass
        try:
            await bot.send_message(
                user_id,
                f"🎉 *Ovozingiz tasdiqlandi!*\n\n"
                f"📌 Loyiha: *{project_name}*\n"
                f"💰 *{int(reward):,} so'm* hisobingizga qo'shildi!\n\n"
                f"Pul yechish uchun 💳 *Pul yechish* tugmasini bosing."
            )
        except Exception:
            pass
    else:
        await update_vote_status(vote_id, "auto_rejected")
        try:
            await bot.send_message(
                user_id,
                f"❌ *Ovozingiz topilmadi*\n\n"
                f"📌 Loyiha: *{project_name}*\n"
                f"📱 Raqam: `{phone}`\n\n"
                f"Ovozingizni o'zingiz tekshirishingiz mumkin:\n"
                f"🔗 {check_url}"
            )
        except Exception:
            pass

# ══════════════════════════════════════════════════════════
# ADMIN — OVOZ TASDIQLASH
# ══════════════════════════════════════════════════════════
@dp.callback_query_handler(lambda c: c.data.startswith("vapprove_") or c.data.startswith("vreject_"))
async def admin_vote_action(callback: types.CallbackQuery):
    if not await check_admin(callback.from_user.id):
        return

    action  = "approve" if callback.data.startswith("vapprove_") else "reject"
    vote_id = int(callback.data.split("_")[1])
    vote    = await get_vote(vote_id)

    if not vote:
        await callback.answer("Ovoz topilmadi!")
        return

    vid, user_id, phone, project_id, status, created = vote
    if status != "pending":
        await callback.answer("Allaqachon ko'rib chiqilgan!")
        return

    project      = await get_project(project_id)
    reward       = int(project[3]) if project else 5000
    project_name = project[1]     if project else "Noma'lum"

    if action == "approve":
        await update_vote_status(vote_id, "approved")
        await add_balance(user_id, reward)

        ref_id = await get_referral_id(user_id)
        if ref_id:
            ref_reward = int(await get("referral_reward"))
            await add_balance(ref_id, ref_reward)
            try:
                await bot.send_message(
                    ref_id,
                    f"🎉 *Do'stingizning ovozi tasdiqlandi!*\n\n"
                    f"Hisobingizga *{ref_reward:,} so'm* qo'shildi 💰"
                )
            except Exception:
                pass
        try:
            await bot.send_message(
                user_id,
                f"🎉 *Ovozingiz tasdiqlandi!*\n\n"
                f"📌 Loyiha: *{project_name}*\n"
                f"💰 *{reward:,} so'm* hisobingizga qo'shildi!\n\n"
                f"Pul yechish uchun 💳 *Pul yechish* tugmasini bosing."
            )
        except Exception:
            pass

        await callback.message.edit_text(
            callback.message.text + "\n\n✅ *TASDIQLANDI*"
        )
        await callback.answer("✅ Tasdiqlandi!")

    else:
        await update_vote_status(vote_id, "rejected")
        try:
            await bot.send_message(
                user_id,
                f"❌ *Ovozingiz tasdiqlanmadi*\n\n"
                f"📌 Loyiha: *{project_name}*\n"
                f"Muammo bo'lsa adminga murojaat qiling."
            )
        except Exception:
            pass

        await callback.message.edit_text(
            callback.message.text + "\n\n❌ *RAD ETILDI*"
        )
        await callback.answer("❌ Rad etildi!")

# ══════════════════════════════════════════════════════════
# BALANS
# ══════════════════════════════════════════════════════════
@dp.message_handler(lambda m: m.text == "💰 Balansim")
async def show_balance(message: types.Message):
    if not await subscription_wall(message):
        return
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("Iltimos /start bosing")
        return
    uid, username, full_name, phone, balance, ref_id, is_blocked_val, joined = user
    await message.answer(
        f"💰 *Balansingiz*\n\n"
        f"👤 Ism: *{full_name}*\n"
        f"🆔 ID: `{uid}`\n"
        f"📱 Telefon: {phone or 'Kiritilmagan'}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💵 Balans: *{int(balance):,} so'm*"
    )

# ══════════════════════════════════════════════════════════
# OVOZLARIM
# ══════════════════════════════════════════════════════════
@dp.message_handler(lambda m: m.text == "📊 Ovozlarim")
async def my_votes(message: types.Message):
    if not await subscription_wall(message):
        return
    votes = await get_user_votes(message.from_user.id)
    if not votes:
        await message.answer(
            "📊 *Ovozlarim*\n\n"
            "Hozircha ovoz bermadingiz.\n"
            "🗳 *Ovoz berish* tugmasini bosing!"
        )
        return

    statuses = {
        "pending":       "⏳ Kutilmoqda",
        "approved":      "✅ Tasdiqlandi",
        "rejected":      "❌ Rad etildi",
        "auto_approved": "✅ Tasdiqlandi",
        "auto_rejected": "❌ Topilmadi",
    }

    text = "📊 *Mening ovozlarim:*\n\n"
    for v in votes:
        vid, pname, phone, status, created = v
        st   = statuses.get(status, status)
        date = created[:10] if created else ""
        text += f"*#{vid}* | {pname}\n📱 {phone} | {st} | {date}\n\n"

    await message.answer(text)

# ══════════════════════════════════════════════════════════
# DO'ST TAKLIF
# ══════════════════════════════════════════════════════════
@dp.message_handler(lambda m: m.text == "🔗 Do'st taklif qilish")
async def referral(message: types.Message):
    if not await subscription_wall(message):
        return
    user_id    = message.from_user.id
    ref_reward = int(await get("referral_reward"))
    bot_info   = await bot.get_me()
    link       = f"https://t.me/{bot_info.username}?start={user_id}"

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(
        "📤 Do'stlarga ulashish",
        url=f"https://t.me/share/url?url={link}&text=Ovoz%20berib%20pul%20ishlang!"
    ))

    await message.answer(
        f"🔗 *Do'st taklif qiling — pul ishlang!*\n\n"
        f"Do'stingiz ovoz berib tasdiqlansa:\n"
        f"💰 Sizga *{ref_reward:,} so'm* qo'shiladi\n"
        f"_(Do'stingizning balansi kamayMaydi)_\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"Sizning havolangiz:\n`{link}`",
        reply_markup=kb
    )

# ══════════════════════════════════════════════════════════
# PUL YECHISH
# ══════════════════════════════════════════════════════════
@dp.message_handler(lambda m: m.text == "💳 Pul yechish")
async def withdraw_start(message: types.Message, state: FSMContext):
    if not await subscription_wall(message):
        return
    balance = await get_balance(message.from_user.id)
    min_w   = int(await get("min_withdraw"))
    max_w   = int(await get("max_withdraw"))

    if balance < min_w:
        await message.answer(
            f"❗ *Balansingiz yetarli emas!*\n\n"
            f"💰 Joriy balans: *{balance:,} so'm*\n"
            f"📤 Minimal yechish: *{min_w:,} so'm*\n\n"
            f"Avval ovoz bering va balans to'plang 🗳"
        )
        return

    await message.answer(
        f"💳 *Pul yechish*\n\n"
        f"💰 Balans: *{balance:,} so'm*\n"
        f"📤 Min: *{min_w:,} so'm*\n"
        f"📤 Max: *{max_w:,} so'm*\n\n"
        f"Necha so'm yechmoqchisiz? _(raqam kiriting)_"
    )
    await WithdrawState.enter_amount.set()

@dp.message_handler(state=WithdrawState.enter_amount)
async def withdraw_amount(message: types.Message, state: FSMContext):
    text = message.text.strip().replace(" ", "").replace(",", "")
    if not text.isdigit():
        await message.answer("❗ Faqat raqam kiriting!")
        return

    amount  = int(text)
    balance = await get_balance(message.from_user.id)
    min_w   = int(await get("min_withdraw"))
    max_w   = int(await get("max_withdraw"))

    if amount < min_w:
        await message.answer(f"❗ Minimal yechish: *{min_w:,} so'm*")
        return
    if amount > max_w:
        await message.answer(f"❗ Maksimal yechish: *{max_w:,} so'm*")
        return
    if amount > balance:
        await message.answer(f"❗ Balansingiz yetarli emas! Balans: *{balance:,} so'm*")
        return

    await state.update_data(amount=amount)

    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("💳 Uzcard", callback_data="card_uzcard"),
        types.InlineKeyboardButton("💳 Humo",   callback_data="card_humo"),
        types.InlineKeyboardButton("💚 Click",  callback_data="card_click"),
        types.InlineKeyboardButton("🔴 Payme",  callback_data="card_payme"),
    )
    await message.answer(
        f"💳 *To'lov tizimini tanlang*\n\n"
        f"Miqdor: *{amount:,} so'm*",
        reply_markup=kb
    )
    await WithdrawState.choose_card.set()

@dp.callback_query_handler(lambda c: c.data.startswith("card_"), state=WithdrawState.choose_card)
async def withdraw_card_chosen(callback: types.CallbackQuery, state: FSMContext):
    card_type   = callback.data.split("_")[1]
    card_number = await get(f"{card_type}_number")

    hint = ""
    if card_number:
        hint = f"\n\n📋 Admin karta raqami:\n`{card_number}`"

    await state.update_data(card_type=card_type)
    await callback.message.answer(
        f"💳 *{card_type.upper()}* tanlandi{hint}\n\n"
        f"Karta yoki telefon raqamingizni kiriting:"
    )
    await WithdrawState.enter_card.set()
    await callback.answer()

@dp.message_handler(state=WithdrawState.enter_card)
async def withdraw_enter_card(message: types.Message, state: FSMContext):
    data        = await state.get_data()
    card_type   = data.get("card_type")
    amount      = data.get("amount")
    card_number = message.text.strip()
    user_id     = message.from_user.id

    payment_id = await add_payment(user_id, amount, card_type, card_number)
    user       = await get_user(user_id)
    full_name  = user[2] if user else "Noma'lum"

    await message.answer(
        f"✅ *To'lov so'rovi yuborildi!*\n\n"
        f"💳 Turi: *{card_type.upper()}*\n"
        f"🔢 Raqam: `{card_number}`\n"
        f"💰 Miqdor: *{amount:,} so'm*\n\n"
        f"Admin tez orada o'tkazadi 🙏",
        reply_markup=main_kb(await check_admin(user_id))
    )

    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ O'tkazildi",  callback_data=f"papprove_{payment_id}"),
        types.InlineKeyboardButton("❌ Rad etish",   callback_data=f"preject_{payment_id}")
    )
    await notify_admins(
        f"💳 *Yangi to'lov so'rovi #{payment_id}*\n\n"
        f"👤 {full_name}\n"
        f"🆔 ID: `{user_id}`\n"
        f"💳 {card_type.upper()}: `{card_number}`\n"
        f"💰 Miqdor: *{amount:,} so'm*",
        reply_markup=kb
    )
    await state.finish()

@dp.callback_query_handler(lambda c: c.data.startswith("papprove_") or c.data.startswith("preject_"))
async def admin_payment_action(callback: types.CallbackQuery):
    if not await check_admin(callback.from_user.id):
        return

    action     = "approve" if callback.data.startswith("papprove_") else "reject"
    payment_id = int(callback.data.split("_")[1])

    if action == "approve":
        await update_payment(payment_id, "approved")
        await callback.message.edit_text(callback.message.text + "\n\n✅ *O'TKAZILDI*")
        await callback.answer("✅ Tasdiqlandi!")
    else:
        await update_payment(payment_id, "rejected")
        await callback.message.edit_text(callback.message.text + "\n\n❌ *RAD ETILDI*")
        await callback.answer("❌ Rad etildi!")

# ══════════════════════════════════════════════════════════
# ADMIN PANEL
# ══════════════════════════════════════════════════════════
@dp.message_handler(lambda m: m.text == "⚙️ Admin panel")
async def admin_panel(message: types.Message):
    if not await check_admin(message.from_user.id):
        return
    await message.answer("👮 *Admin panel*\n\nBo'limni tanlang 👇", reply_markup=admin_kb())

@dp.message_handler(lambda m: m.text == "🔙 Asosiy menyu")
async def back_main(message: types.Message):
    is_adm = await check_admin(message.from_user.id)
    await message.answer("🏠 Asosiy menyu", reply_markup=main_kb(is_adm))

# ── STATISTIKA ────────────────────────────────────────────
@dp.message_handler(lambda m: m.text == "📊 Statistika")
async def admin_stats(message: types.Message):
    if not await check_admin(message.from_user.id):
        return
    total_users, approved, pending, rejected, total_balance, pending_payments = await get_stats()
    await message.answer(
        f"📊 *Bot statistikasi*\n\n"
        f"👥 Jami foydalanuvchilar: *{total_users}*\n\n"
        f"🗳 *Ovozlar:*\n"
        f"  ✅ Tasdiqlangan: *{approved}*\n"
        f"  ⏳ Kutilayotgan: *{pending}*\n"
        f"  ❌ Rad etilgan: *{rejected}*\n\n"
        f"💰 Jami to'lanmagan balans: *{int(total_balance):,} so'm*\n"
        f"💳 Kutilayotgan to'lovlar: *{pending_payments}*"
    )

# ── LOYIHALAR ─────────────────────────────────────────────
@dp.message_handler(lambda m: m.text == "📁 Loyihalar")
async def admin_projects(message: types.Message):
    if not await check_admin(message.from_user.id):
        return
    projects = await get_all_projects()
    if not projects:
        await message.answer("📁 Hozircha loyiha yo'q.")
        return

    for p in projects:
        pid, name, url, reward, check_url, is_active, created = p
        status = "✅ Faol" if is_active else "❌ Nofaol"
        kb = types.InlineKeyboardMarkup(row_width=2)
        if is_active:
            kb.add(
                types.InlineKeyboardButton("🔴 O'chirish",      callback_data=f"proj_off_{pid}"),
                types.InlineKeyboardButton("✏️ Mukofot o'zgartir", callback_data=f"proj_rew_{pid}")
            )
        else:
            kb.add(
                types.InlineKeyboardButton("🟢 Yoqish",         callback_data=f"proj_on_{pid}"),
                types.InlineKeyboardButton("✏️ Mukofot o'zgartir", callback_data=f"proj_rew_{pid}")
            )
        await message.answer(
            f"📌 *{name}*\n"
            f"🔗 {url}\n"
            f"💰 Mukofot: *{int(reward):,} so'm*\n"
            f"🔍 Tekshirish: {check_url}\n"
            f"📍 Status: {status}",
            reply_markup=kb
        )

@dp.callback_query_handler(lambda c: c.data.startswith("proj_"))
async def proj_action(callback: types.CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        return
    parts  = callback.data.split("_")
    action = parts[1]
    pid    = int(parts[2])

    if action == "off":
        await toggle_project(pid, 0)
        await callback.answer("🔴 O'chirildi!")
        await callback.message.edit_reply_markup()
    elif action == "on":
        await toggle_project(pid, 1)
        await callback.answer("🟢 Yoqildi!")
        await callback.message.edit_reply_markup()
    elif action == "rew":
        await state.update_data(edit_project_id=pid)
        await callback.message.answer(
            f"✏️ *Loyiha #{pid} uchun yangi mukofotni kiriting (so'mda):*"
        )
        await state.set_state("edit_project_reward")
        await callback.answer()

@dp.message_handler(state="edit_project_reward")
async def save_project_reward(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❗ Faqat raqam kiriting!")
        return
    data = await state.get_data()
    pid  = data.get("edit_project_id")
    await update_project_reward(pid, int(message.text))
    await message.answer(
        f"✅ Loyiha #{pid} mukofoti *{int(message.text):,} so'm* ga o'zgartirildi!",
        reply_markup=admin_kb()
    )
    await state.finish()

# ── LOYIHA QO'SHISH ───────────────────────────────────────
@dp.message_handler(lambda m: m.text == "➕ Loyiha qo'shish")
async def admin_add_project(message: types.Message):
    if not await check_admin(message.from_user.id):
        return
    await message.answer(
        "➕ *Yangi loyiha qo'shish*\n\n"
        "Loyiha nomini kiriting:"
    )
    await AdminState.add_project_name.set()

@dp.message_handler(state=AdminState.add_project_name)
async def ap_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("🔗 Ovoz berish URL-ini kiriting:")
    await AdminState.add_project_url.set()

@dp.message_handler(state=AdminState.add_project_url)
async def ap_url(message: types.Message, state: FSMContext):
    await state.update_data(url=message.text)
    await message.answer("💰 Mukofot miqdorini kiriting (so'mda):")
    await AdminState.add_project_reward.set()

@dp.message_handler(state=AdminState.add_project_reward)
async def ap_reward(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❗ Faqat raqam kiriting!")
        return
    await state.update_data(reward=message.text)
    await message.answer(
        "🔍 Ovozlarni tekshirish URL-ini kiriting:\n"
        "_(Bu URL da nomer oxirgi 4 raqami tekshiriladi)_"
    )
    await AdminState.add_project_check.set()

@dp.message_handler(state=AdminState.add_project_check)
async def ap_check(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await add_project(data["name"], data["url"], int(data["reward"]), message.text)
    await message.answer(
        f"✅ *Loyiha muvaffaqiyatli qo'shildi!*\n\n"
        f"📌 Nom: *{data['name']}*\n"
        f"💰 Mukofot: *{int(data['reward']):,} so'm*",
        reply_markup=admin_kb()
    )
    await state.finish()

# ── FOYDALANUVCHILAR ──────────────────────────────────────
@dp.message_handler(lambda m: m.text == "👥 Foydalanuvchilar")
async def admin_users(message: types.Message):
    if not await check_admin(message.from_user.id):
        return
    users = await get_all_users()
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🚫 Bloklash",    callback_data="act_block"),
        types.InlineKeyboardButton("✅ Blokdan chiqarish", callback_data="act_unblock")
    )
    text = f"👥 *Foydalanuvchilar ({len(users)} ta):*\n\n"
    for u in users[:20]:
        uid, uname, fname, phone, balance, is_bl = u
        bl   = "🚫" if is_bl else "✅"
        text += f"{bl} *{fname}* | 💰{int(balance):,}\n"
    if len(users) > 20:
        text += f"\n_...va yana {len(users)-20} ta_"
    await message.answer(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data in ["act_block", "act_unblock"])
async def user_action_start(callback: types.CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        return
    action = callback.data
    await state.update_data(user_action=action)
    if action == "act_block":
        await callback.message.answer("🚫 *Bloklash uchun foydalanuvchi ID-ini kiriting:*")
        await AdminState.block_user_id.set()
    else:
        await callback.message.answer("✅ *Blokdan chiqarish uchun foydalanuvchi ID-ini kiriting:*")
        await AdminState.unblock_user_id.set()
    await callback.answer()

@dp.message_handler(state=AdminState.block_user_id)
async def do_block(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❗ Faqat ID raqam kiriting!")
        return
    uid = int(message.text)
    await block_user(uid)
    await message.answer(f"🚫 Foydalanuvchi `{uid}` bloklandi!", reply_markup=admin_kb())
    try:
        await bot.send_message(uid, "🚫 Siz botdan bloklangansiz. Adminga murojaat qiling.")
    except Exception:
        pass
    await state.finish()

@dp.message_handler(state=AdminState.unblock_user_id)
async def do_unblock(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❗ Faqat ID raqam kiriting!")
        return
    uid = int(message.text)
    await unblock_user(uid)
    await message.answer(f"✅ Foydalanuvchi `{uid}` blokdan chiqarildi!", reply_markup=admin_kb())
    try:
        await bot.send_message(uid, "✅ Siz botdan blok olib tashlandi. /start bosing.")
    except Exception:
        pass
    await state.finish()

# ── TO'LOVLAR ─────────────────────────────────────────────
@dp.message_handler(lambda m: m.text == "💳 To'lovlar")
async def admin_payments(message: types.Message):
    if not await check_admin(message.from_user.id):
        return
    payments = await get_pending_payments()
    if not payments:
        await message.answer("✅ *Kutilayotgan to'lov yo'q!*")
        return
    for p in payments:
        pid, uid, amount, card_type, card_number, status, created, fname, uname = p
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("✅ O'tkazildi",  callback_data=f"papprove_{pid}"),
            types.InlineKeyboardButton("❌ Rad etish",   callback_data=f"preject_{pid}")
        )
        await message.answer(
            f"💳 *To'lov so'rovi #{pid}*\n\n"
            f"👤 {fname}\n"
            f"🆔 ID: `{uid}`\n"
            f"💳 {card_type.upper()}: `{card_number}`\n"
            f"💰 Miqdor: *{int(amount):,} so'm*",
            reply_markup=kb
        )

# ── BROADCAST ─────────────────────────────────────────────
@dp.message_handler(lambda m: m.text == "📢 Xabar yuborish")
async def broadcast_start(message: types.Message):
    if not await check_admin(message.from_user.id):
        return
    await message.answer(
        "📢 *Barcha foydalanuvchilarga xabar yuborish*\n\n"
        "Xabarni kiriting:"
    )
    await AdminState.broadcast.set()

@dp.message_handler(state=AdminState.broadcast)
async def broadcast_send(message: types.Message, state: FSMContext):
    users    = await get_all_users()
    sent     = 0
    failed   = 0
    progress = await message.answer(f"📢 Yuborilmoqda... 0/{len(users)}")

    for u in users:
        try:
            await bot.send_message(u[0], message.text)
            sent += 1
        except Exception:
            failed += 1
        if (sent + failed) % 20 == 0:
            try:
                await bot.edit_message_text(
                    f"📢 Yuborilmoqda... {sent+failed}/{len(users)}",
                    message.chat.id, progress.message_id
                )
            except Exception:
                pass
        await asyncio.sleep(0.05)

    await bot.edit_message_text(
        f"📢 *Yuborish yakunlandi!*\n\n✅ Muvaffaqiyatli: {sent}\n❌ Xato: {failed}",
        message.chat.id, progress.message_id
    )
    await state.finish()

# ── ADMINLAR ──────────────────────────────────────────────
@dp.message_handler(lambda m: m.text == "👮 Adminlar")
async def admin_list(message: types.Message):
    if not await check_admin(message.from_user.id):
        return
    admins = await get_admins()
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("➕ Admin qo'shish", callback_data="add_admin"))
    for a in admins:
        kb.add(types.InlineKeyboardButton(
            f"❌ {a[1]} ni o'chirish", callback_data=f"del_admin_{a[0]}"
        ))

    text = f"👮 *Adminlar ro'yxati*\n\n"
    text += f"👑 Super admin: `{SUPER_ADMIN}`\n\n"
    if admins:
        for a in admins:
            text += f"👮 {a[1]} | `{a[0]}`\n"
    else:
        text += "_Qo'shimcha admin yo'q_"

    await message.answer(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == "add_admin")
async def add_admin_start(callback: types.CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        return
    await callback.message.answer(
        "➕ *Yangi admin qo'shish*\n\n"
        "Admin Telegram ID-ini kiriting:"
    )
    await AdminState.add_admin_id.set()
    await callback.answer()

@dp.message_handler(state=AdminState.add_admin_id)
async def save_admin(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❗ Faqat ID raqam kiriting!")
        return
    uid = int(message.text)
    try:
        chat = await bot.get_chat(uid)
        name = chat.full_name
    except Exception:
        name = f"ID:{uid}"

    await add_admin(uid, name)
    await message.answer(
        f"✅ *{name}* admin sifatida qo'shildi!",
        reply_markup=admin_kb()
    )
    try:
        await bot.send_message(uid, "🎉 Siz bot adminiga qo'shildingiz!")
    except Exception:
        pass
    await state.finish()

@dp.callback_query_handler(lambda c: c.data.startswith("del_admin_"))
async def delete_admin(callback: types.CallbackQuery):
    if callback.from_user.id != SUPER_ADMIN:
        await callback.answer("Faqat super admin o'chirishi mumkin!")
        return
    uid = int(callback.data.split("_")[2])
    await remove_admin(uid)
    await callback.answer("✅ Admin o'chirildi!")
    await callback.message.edit_reply_markup()

# ── SOZLAMALAR ────────────────────────────────────────────
@dp.message_handler(lambda m: m.text == "⚙️ Sozlamalar")
async def admin_settings(message: types.Message):
    if not await check_admin(message.from_user.id):
        return
    vote_r  = int(await get("vote_reward"))
    ref_r   = int(await get("referral_reward"))
    min_w   = int(await get("min_withdraw"))
    max_w   = int(await get("max_withdraw"))
    channel = await get("channel")
    uzcard  = await get("uzcard_number")
    humo    = await get("humo_number")
    click   = await get("click_number")
    payme   = await get("payme_number")

    kb = types.InlineKeyboardMarkup(row_width=1)
    settings_list = [
        ("💰 Ovoz mukofoti",         "vote_reward"),
        ("👥 Referral mukofoti",      "referral_reward"),
        ("📤 Min yechish miqdori",    "min_withdraw"),
        ("📤 Max yechish miqdori",    "max_withdraw"),
        ("📢 Majburiy kanal",         "channel"),
        ("💳 Uzcard raqami",          "uzcard_number"),
        ("💳 Humo raqami",            "humo_number"),
        ("💚 Click raqami",           "click_number"),
        ("🔴 Payme raqami",           "payme_number"),
        ("👋 Xush kelibsiz matni",    "welcome_text"),
        ("ℹ️ Bot haqida matni",       "about_text"),
    ]
    for label, key in settings_list:
        kb.add(types.InlineKeyboardButton(label, callback_data=f"sset_{key}"))

    await message.answer(
        f"⚙️ *Sozlamalar*\n\n"
        f"💰 Ovoz mukofoti: *{vote_r:,} so'm*\n"
        f"👥 Referral mukofoti: *{ref_r:,} so'm*\n"
        f"📤 Min yechish: *{min_w:,} so'm*\n"
        f"📤 Max yechish: *{max_w:,} so'm*\n"
        f"📢 Kanal: {channel}\n"
        f"💳 Uzcard: {uzcard or '—'}\n"
        f"💳 Humo: {humo or '—'}\n"
        f"💚 Click: {click or '—'}\n"
        f"🔴 Payme: {payme or '—'}",
        reply_markup=kb
    )

@dp.callback_query_handler(lambda c: c.data.startswith("sset_"))
async def setting_edit(callback: types.CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        return
    key     = callback.data[5:]
    current = await get(key)
    await state.update_data(setting_key=key)
    await callback.message.answer(
        f"✏️ *{key}* ni o'zgartirish\n\n"
        f"Hozirgi qiymat: `{current}`\n\n"
        f"Yangi qiymatni kiriting:"
    )
    await AdminState.edit_setting_val.set()
    await callback.answer()

@dp.message_handler(state=AdminState.edit_setting_val)
async def save_setting(message: types.Message, state: FSMContext):
    data = await state.get_data()
    key  = data.get("setting_key")
    await set_setting(key, message.text.strip())
    await message.answer(f"✅ *{key}* muvaffaqiyatli yangilandi!", reply_markup=admin_kb())
    await state.finish()

# ══════════════════════════════════════════════════════════
# HEALTH CHECK SERVER (Koyeb uchun)
# ══════════════════════════════════════════════════════════
async def health_server():
    from aiohttp import web
    async def handle(request):
        return web.Response(text="OK")
    app    = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site   = web.TCPSite(runner, "0.0.0.0", 8000)
    await site.start()
    logger.info("Health check server port 8000 da ishga tushdi ✅")

# ══════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════
if __name__ == "__main__":
    async def on_startup(dp):
        await init_db()
        await health_server()
        logger.info("Bot ishga tushdi ✅")

    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
