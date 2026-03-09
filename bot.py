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

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN = "8679118861:AAES2RZz_HdxuZWhqi9pVSWxIl5yiL1oL2U"   # <-- O'z tokeningni qo'y
ADMIN_IDS = [6498632307]              # <-- O'z Telegram ID-ingni qo'y

bot = Bot(token=BOT_TOKEN, parse_mode="Markdown")
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Aktiv sessiyalar (user_id: aiohttp.ClientSession)
sessions = {}

# ══════════════════════════════════════════════
# STATES
# ══════════════════════════════════════════════
class VoteState(StatesGroup):
    choose_project = State()
    enter_phone = State()
    enter_sms = State()

class WithdrawState(StatesGroup):
    choose_card = State()
    enter_card = State()

class AdminState(StatesGroup):
    broadcast = State()
    add_project_name = State()
    add_project_url = State()
    add_project_reward = State()
    add_project_check = State()
    edit_setting_key = State()
    edit_setting_val = State()
    set_cards = State()

# ══════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════
def is_admin(user_id):
    return user_id in ADMIN_IDS

def main_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        types.KeyboardButton("🗳 Ovoz berish"),
        types.KeyboardButton("💰 Balans"),
        types.KeyboardButton("🔗 Do'st taklif qilish"),
        types.KeyboardButton("💳 Pul yechish"),
        types.KeyboardButton("📊 Mening ovozlarim"),
        types.KeyboardButton("ℹ️ Bot haqida"),
    )
    return kb

def admin_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        types.KeyboardButton("📊 Statistika"),
        types.KeyboardButton("📁 Loyihalar"),
        types.KeyboardButton("➕ Loyiha qo'shish"),
        types.KeyboardButton("👥 Foydalanuvchilar"),
        types.KeyboardButton("💳 To'lovlar"),
        types.KeyboardButton("📢 Xabar yuborish"),
        types.KeyboardButton("⚙️ Sozlamalar"),
        types.KeyboardButton("🔙 Asosiy menyu"),
    )
    return kb

async def notify_admins(text, reply_markup=None):
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Admin {admin_id} ga xabar yuborishda xato: {e}")

# ══════════════════════════════════════════════
# START
# ══════════════════════════════════════════════
@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message, state: FSMContext):
    await state.finish()
    user = message.from_user
    args = message.get_args()
    ref_id = int(args) if args and args.isdigit() and int(args) != user.id else None
    await add_user(user.id, user.username, user.full_name, ref_id)

    welcome = await get("welcome_text")
    await message.answer(
        welcome.format(name=user.first_name),
        reply_markup=admin_kb() if is_admin(user.id) else main_kb()
    )

# ══════════════════════════════════════════════
# BOT HAQIDA
# ══════════════════════════════════════════════
@dp.message_handler(lambda m: m.text == "ℹ️ Bot haqida")
async def about(message: types.Message):
    reward = await get("vote_reward")
    ref_reward = await get("referral_reward")
    await message.answer(
        f"🤖 *Bu bot haqida*\n\n"
        f"✅ Har bir tasdiqlangan ovoz uchun: *{int(reward):,} so'm*\n"
        f"👥 Har bir do'st ovozi uchun: *{int(ref_reward):,} so'm*\n\n"
        f"📌 Qanday ishlaydi:\n"
        f"1️⃣ Ovoz berish tugmasini bosing\n"
        f"2️⃣ Telefon raqamingizni kiriting\n"
        f"3️⃣ SMS kodni kiriting\n"
        f"4️⃣ 1 soatdan keyin ovozingiz tekshiriladi\n"
        f"5️⃣ Tasdiqlansa — pulni hisobingizga o'tkazamiz 💰"
    )

# ══════════════════════════════════════════════
# OVOZ BERISH
# ══════════════════════════════════════════════
@dp.message_handler(lambda m: m.text == "🗳 Ovoz berish")
async def vote_start(message: types.Message, state: FSMContext):
    projects = await get_active_projects()
    if not projects:
        await message.answer("⚠️ Hozircha faol loyiha yo'q. Kuting!")
        return

    kb = types.InlineKeyboardMarkup(row_width=1)
    for p in projects:
        pid, name, url, reward, check_url, is_active = p
        kb.add(types.InlineKeyboardButton(f"📌 {name} — {int(reward):,} so'm", callback_data=f"vote_{pid}"))

    await message.answer("🗳 *Qaysi loyiha uchun ovoz bermoqchisiz?*", reply_markup=kb)
    await VoteState.choose_project.set()

@dp.callback_query_handler(lambda c: c.data.startswith("vote_"), state=VoteState.choose_project)
async def vote_project_chosen(callback: types.CallbackQuery, state: FSMContext):
    project_id = int(callback.data.split("_")[1])
    project = await get_project(project_id)
    if not project:
        await callback.answer("Loyiha topilmadi!")
        return

    await state.update_data(project_id=project_id, project=project)

    # Saytga kirish uchun link
    pid, name, vote_url, reward, check_url, _ = project
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(f"🔗 {name} saytiga o'tish", url=vote_url))

    await callback.message.answer(
        f"📌 *{name}*\n\n"
        f"1️⃣ Quyidagi tugmani bosib saytga o'ting\n"
        f"2️⃣ Saytda ovoz bering\n"
        f"3️⃣ Qaytib kelib *telefon raqamingizni* kiriting\n\n"
        f"📱 *Telefon raqamingizni kiriting:*\n"
        f"_(Format: +998901234567)_",
        reply_markup=kb
    )
    await VoteState.enter_phone.set()
    await callback.answer()

@dp.message_handler(state=VoteState.enter_phone)
async def vote_enter_phone(message: types.Message, state: FSMContext):
    phone = message.text.strip()

    # Raqamni tekshirish
    clean = phone.replace("+", "").replace(" ", "").replace("-", "")
    if not clean.isdigit() or len(clean) < 9:
        await message.answer("❗ Noto'g'ri format! Qayta kiriting:\n_(Misol: +998901234567)_")
        return

    if not clean.startswith("998"):
        clean = "998" + clean[-9:]
    phone = "+" + clean

    await state.update_data(phone=phone, session_start=datetime.now().isoformat())

    data = await state.get_data()
    project = data.get("project")
    pid, name, vote_url, reward, check_url, _ = project

    await message.answer(f"⏳ Saytga ulanmoqda...")

    # Sayt sessiyasini boshlash
    session = aiohttp.ClientSession()
    sessions[message.from_user.id] = session

    success, html = await submit_phone(session, vote_url, phone)

    if success:
        await message.answer(
            f"✅ *{phone}* raqamiga SMS kod yuborildi!\n\n"
            f"📩 Kodni kiriting:"
        )
        await VoteState.enter_sms.set()
    else:
        await session.close()
        sessions.pop(message.from_user.id, None)

        # Agar sayt avtomatlashtirishda muammo bo'lsa — manual rejim
        await message.answer(
            f"📌 *{name}* saytida qo'lda ovoz bering:\n\n"
            f"1️⃣ Saytga o'ting va ovoz bering\n"
            f"2️⃣ SMS kelganida kodni bu yerga yuboring\n\n"
            f"📩 SMS kodingizni kiriting:"
        )
        await state.update_data(manual_mode=True)
        await VoteState.enter_sms.set()

@dp.message_handler(state=VoteState.enter_sms)
async def vote_enter_sms(message: types.Message, state: FSMContext):
    code = message.text.strip()
    if not code.isdigit():
        await message.answer("❗ Faqat raqamlardan iborat kod kiriting!")
        return

    data = await state.get_data()
    phone = data.get("phone")
    project = data.get("project")
    manual_mode = data.get("manual_mode", False)
    pid, name, vote_url, reward, check_url, _ = project

    if not manual_mode:
        session = sessions.get(message.from_user.id)
        if session:
            success, result = await submit_sms_code(session, vote_url, phone, code)
            await session.close()
            sessions.pop(message.from_user.id, None)
        else:
            success = True

    user_id = message.from_user.id
    vote_id = await add_vote(user_id, phone, pid)
    await set_phone(user_id, phone)

    vote_time = datetime.now().isoformat()
    check_time = (datetime.now() + timedelta(hours=1)).strftime("%H:%M")

    await message.answer(
        f"✅ *Ovozingiz qabul qilindi!*\n\n"
        f"📱 Raqam: `{phone}`\n"
        f"📌 Loyiha: *{name}*\n"
        f"⏰ Tekshirish vaqti: *{check_time}*\n\n"
        f"🔍 1 soatdan keyin ovozingiz tekshiriladi.\n"
        f"Tasdiqlansa — *{int(reward):,} so'm* hisobingizga o'tkaziladi 💰",
        reply_markup=main_kb()
    )

    # Adminlarga xabar
    last4 = phone.replace("+", "")[-4:]
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"vapprove_{vote_id}"),
        types.InlineKeyboardButton("❌ Rad etish", callback_data=f"vreject_{vote_id}")
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

    # 1 soatdan keyin avtomatik tekshirish
    asyncio.create_task(
        auto_check_vote(vote_id, user_id, phone, check_url, reward, name, vote_time)
    )

    await state.finish()

async def auto_check_vote(vote_id, user_id, phone, check_url, reward, project_name, vote_time):
    """1 soatdan keyin ovozni avtomatik tekshiradi"""
    await asyncio.sleep(3600)  # 1 soat

    vote = await get_vote(vote_id)
    if not vote or vote[4] != "pending":
        return  # Allaqachon ko'rib chiqilgan

    found = await check_vote_result(phone, check_url, vote_time)

    if found:
        await update_vote_status(vote_id, "auto_approved")
        await add_balance(user_id, int(reward))

        # Referral bonus
        ref_id = await get_referral_id(user_id)
        if ref_id:
            ref_reward = int(await get("referral_reward"))
            await add_balance(ref_id, ref_reward)
            try:
                await bot.send_message(
                    ref_id,
                    f"🎉 Do'stingiz ovoz berdi!\n"
                    f"Hisobingizga *{ref_reward:,} so'm* qo'shildi 💰"
                )
            except:
                pass

        try:
            await bot.send_message(
                user_id,
                f"✅ *Ovozingiz tasdiqlandi!*\n\n"
                f"📌 Loyiha: *{project_name}*\n"
                f"💰 Hisobingizga *{int(reward):,} so'm* qo'shildi!\n\n"
                f"Pul yechish uchun 💳 Pul yechish bo'limiga o'ting."
            )
        except:
            pass
    else:
        await update_vote_status(vote_id, "auto_rejected")
        try:
            await bot.send_message(
                user_id,
                f"❌ *Ovozingiz topilmadi*\n\n"
                f"📌 Loyiha: *{project_name}*\n"
                f"📱 Raqam: `{phone}`\n\n"
                f"Ovozingizni tekshirishingiz mumkin:\n"
                f"🔗 {check_url}"
            )
        except:
            pass

# ══════════════════════════════════════════════
# ADMIN — OVOZ TASDIQLASH
# ══════════════════════════════════════════════
@dp.callback_query_handler(lambda c: c.data.startswith("vapprove_") or c.data.startswith("vreject_"))
async def admin_vote_action(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    action = "approve" if callback.data.startswith("vapprove_") else "reject"
    vote_id = int(callback.data.split("_")[1])
    vote = await get_vote(vote_id)

    if not vote:
        await callback.answer("Ovoz topilmadi!")
        return

    vid, user_id, phone, project_id, status, created = vote
    if status != "pending":
        await callback.answer("Allaqachon ko'rib chiqilgan!")
        return

    project = await get_project(project_id)
    reward = int(project[3]) if project else 5000
    project_name = project[1] if project else "—"

    if action == "approve":
        await update_vote_status(vote_id, "approved")
        await add_balance(user_id, reward)

        # Referral bonus
        ref_id = await get_referral_id(user_id)
        if ref_id:
            ref_reward = int(await get("referral_reward"))
            await add_balance(ref_id, ref_reward)
            try:
                await bot.send_message(
                    ref_id,
                    f"🎉 Do'stingizning ovozi tasdiqlandi!\n"
                    f"Hisobingizga *{ref_reward:,} so'm* qo'shildi 💰"
                )
            except:
                pass

        try:
            await bot.send_message(
                user_id,
                f"✅ *Ovozingiz tasdiqlandi!*\n\n"
                f"📌 Loyiha: *{project_name}*\n"
                f"💰 Hisobingizga *{reward:,} so'm* qo'shildi!\n\n"
                f"Pul yechish uchun 💳 Pul yechish bo'limiga o'ting."
            )
        except:
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
        except:
            pass

        await callback.message.edit_text(
            callback.message.text + "\n\n❌ *RAD ETILDI*"
        )
        await callback.answer("❌ Rad etildi!")

# ══════════════════════════════════════════════
# BALANS
# ══════════════════════════════════════════════
@dp.message_handler(lambda m: m.text == "💰 Balans")
async def show_balance(message: types.Message):
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("Iltimos /start bosing")
        return
    uid, username, full_name, phone, balance, ref_id, joined = user
    await message.answer(
        f"💰 *Balansingiz*\n\n"
        f"👤 {full_name}\n"
        f"📱 Tel: {phone or 'Kiritilmagan'}\n"
        f"💵 Balans: *{int(balance):,} so'm*"
    )

# ══════════════════════════════════════════════
# MENING OVOZLARIM
# ══════════════════════════════════════════════
@dp.message_handler(lambda m: m.text == "📊 Mening ovozlarim")
async def my_votes(message: types.Message):
    async with __import__('aiosqlite').connect("ovoz.db") as db:
        async with db.execute(
            "SELECT v.id, p.name, v.phone, v.status, v.created_at FROM votes v "
            "JOIN projects p ON v.project_id=p.id WHERE v.user_id=? ORDER BY v.id DESC LIMIT 10",
            (message.from_user.id,)
        ) as c:
            votes = await c.fetchall()

    if not votes:
        await message.answer("Hozircha ovoz bermadingiz.")
        return

    statuses = {
        "pending": "⏳ Kutilmoqda",
        "approved": "✅ Tasdiqlandi",
        "rejected": "❌ Rad etildi",
        "auto_approved": "✅ Avtomatik tasdiqlandi",
        "auto_rejected": "❌ Avtomatik rad etildi",
    }

    text = "📊 *Mening ovozlarim:*\n\n"
    for v in votes:
        vid, pname, phone, status, created = v
        st = statuses.get(status, status)
        text += f"#{vid} | {pname}\n📱 {phone} | {st}\n\n"

    await message.answer(text)

# ══════════════════════════════════════════════
# DO'ST TAKLIF
# ══════════════════════════════════════════════
@dp.message_handler(lambda m: m.text == "🔗 Do'st taklif qilish")
async def referral(message: types.Message):
    user_id = message.from_user.id
    ref_reward = await get("referral_reward")
    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={user_id}"

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(
        "📤 Do'stlarga ulashish",
        url=f"https://t.me/share/url?url={link}&text=Ovoz%20berib%20pul%20ishlang!"
    ))

    await message.answer(
        f"🔗 *Do'st taklif qiling — pul ishlang!*\n\n"
        f"Do'stingiz ovoz berib tasdiqlansa:\n"
        f"💰 Sizga *{int(ref_reward):,} so'm* qo'shiladi\n"
        f"_(Do'stingizning balansi kamayMaydi)_\n\n"
        f"Sizning havolangiz:\n`{link}`",
        reply_markup=kb
    )

# ══════════════════════════════════════════════
# PUL YECHISH
# ══════════════════════════════════════════════
@dp.message_handler(lambda m: m.text == "💳 Pul yechish")
async def withdraw_start(message: types.Message, state: FSMContext):
    balance = await get_balance(message.from_user.id)
    if balance <= 0:
        await message.answer("❗ Balansingiz 0. Avval ovoz bering!")
        return

    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("💳 Uzcard", callback_data="card_uzcard"),
        types.InlineKeyboardButton("💳 Humo", callback_data="card_humo"),
        types.InlineKeyboardButton("💚 Click", callback_data="card_click"),
        types.InlineKeyboardButton("🔴 Payme", callback_data="card_payme"),
    )

    await message.answer(
        f"💰 Balans: *{int(balance):,} so'm*\n\n"
        f"Qaysi karta/to'lov tizimiga o'tkazish kerak?",
        reply_markup=kb
    )
    await WithdrawState.choose_card.set()

@dp.callback_query_handler(lambda c: c.data.startswith("card_"), state=WithdrawState.choose_card)
async def withdraw_card_chosen(callback: types.CallbackQuery, state: FSMContext):
    card_type = callback.data.split("_")[1]
    await state.update_data(card_type=card_type)

    # Admin tomonidan kiritilgan karta raqamlarini ko'rsatish
    card_numbers = await get(f"{card_type}_numbers")
    hint = f"\n\n*Admin karta raqami:*\n`{card_numbers}`" if card_numbers else ""

    await callback.message.answer(
        f"💳 *{card_type.upper()}* tanlandi{hint}\n\n"
        f"Karta/telefon raqamingizni kiriting:"
    )
    await WithdrawState.enter_card.set()
    await callback.answer()

@dp.message_handler(state=WithdrawState.enter_card)
async def withdraw_enter_card(message: types.Message, state: FSMContext):
    data = await state.get_data()
    card_type = data.get("card_type")
    card_number = message.text.strip()
    user_id = message.from_user.id
    balance = await get_balance(user_id)

    payment_id = await add_payment_request(user_id, balance, card_type, card_number)

    await message.answer(
        f"✅ *To'lov so'rovi yuborildi!*\n\n"
        f"💳 Karta turi: *{card_type.upper()}*\n"
        f"🔢 Karta: `{card_number}`\n"
        f"💰 Miqdor: *{int(balance):,} so'm*\n\n"
        f"Admin tez orada o'tkazadi 🙏",
        reply_markup=main_kb()
    )

    user = await get_user(user_id)
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("✅ O'tkazildi", callback_data=f"papprove_{payment_id}"),
        types.InlineKeyboardButton("❌ Rad etish", callback_data=f"preject_{payment_id}")
    )
    await notify_admins(
        f"💳 *Yangi to'lov so'rovi #{payment_id}*\n\n"
        f"👤 {user[2] if user else 'Noaniq'}\n"
        f"🆔 ID: `{user_id}`\n"
        f"💳 {card_type.upper()}: `{card_number}`\n"
        f"💰 Miqdor: *{int(balance):,} som*",
        reply_markup=kb
    )
    await state.finish()

@dp.callback_query_handler(lambda c: c.data.startswith("papprove_") or c.data.startswith("preject_"))
async def admin_payment_action(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    action = "approve" if callback.data.startswith("papprove_") else "reject"
    payment_id = int(callback.data.split("_")[1])

    if action == "approve":
        await update_payment(payment_id, "approved")
        await callback.message.edit_text(callback.message.text + "\n\n✅ *O'TKAZILDI*")
        await callback.answer("✅ Tasdiqlandi!")
    else:
        await update_payment(payment_id, "rejected")
        await callback.message.edit_text(callback.message.text + "\n\n❌ *RAD ETILDI*")
        await callback.answer("❌ Rad etildi!")

# ══════════════════════════════════════════════
# ADMIN PANEL
# ══════════════════════════════════════════════
@dp.message_handler(lambda m: m.text == "📊 Statistika")
async def admin_stats(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    users, approved, pending, rejected, total_balance = await get_stats()
    await message.answer(
        f"📊 *Bot statistikasi*\n\n"
        f"👥 Jami foydalanuvchilar: *{users}*\n"
        f"✅ Tasdiqlangan ovozlar: *{approved}*\n"
        f"⏳ Kutilayotgan ovozlar: *{pending}*\n"
        f"❌ Rad etilgan ovozlar: *{rejected}*\n"
        f"💰 Jami to'lanmagan balans: *{int(total_balance):,} so'm*"
    )

@dp.message_handler(lambda m: m.text == "📁 Loyihalar")
async def admin_projects(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    projects = await get_all_projects()
    if not projects:
        await message.answer("Loyihalar yo'q.")
        return
    for p in projects:
        pid, name, url, reward, check_url, is_active = p
        status = "✅ Faol" if is_active else "❌ Nofaol"
        kb = types.InlineKeyboardMarkup()
        if is_active:
            kb.add(types.InlineKeyboardButton("🔴 O'chirish", callback_data=f"proj_off_{pid}"))
        else:
            kb.add(types.InlineKeyboardButton("🟢 Yoqish", callback_data=f"proj_on_{pid}"))
        await message.answer(
            f"📌 *{name}*\n"
            f"🔗 {url}\n"
            f"💰 {int(reward):,} so'm\n"
            f"🔍 Tekshirish: {check_url}\n"
            f"Status: {status}",
            reply_markup=kb
        )

@dp.callback_query_handler(lambda c: c.data.startswith("proj_"))
async def toggle_proj(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    parts = callback.data.split("_")
    action, pid = parts[1], int(parts[2])
    await toggle_project(pid, 1 if action == "on" else 0)
    await callback.message.edit_reply_markup()
    await callback.answer("✅ O'zgartirildi!")
    await admin_projects(callback.message)

@dp.message_handler(lambda m: m.text == "➕ Loyiha qo'shish")
async def admin_add_project(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("📌 Loyiha nomini kiriting:")
    await AdminState.add_project_name.set()

@dp.message_handler(state=AdminState.add_project_name)
async def ap_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("🔗 Ovoz berish URL-ini kiriting:")
    await AdminState.add_project_url.set()

@dp.message_handler(state=AdminState.add_project_url)
async def ap_url(message: types.Message, state: FSMContext):
    await state.update_data(url=message.text)
    await message.answer("💰 Mukofot miqdori (so'mda):")
    await AdminState.add_project_reward.set()

@dp.message_handler(state=AdminState.add_project_reward)
async def ap_reward(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❗ Faqat raqam kiriting!")
        return
    await state.update_data(reward=message.text)
    await message.answer("🔍 Ovozlarni tekshirish URL-ini kiriting:")
    await AdminState.add_project_check.set()

@dp.message_handler(state=AdminState.add_project_check)
async def ap_check(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await add_project(data["name"], data["url"], int(data["reward"]), message.text)
    await message.answer(
        f"✅ Loyiha qo'shildi!\n📌 *{data['name']}*",
        reply_markup=admin_kb()
    )
    await state.finish()

@dp.message_handler(lambda m: m.text == "👥 Foydalanuvchilar")
async def admin_users(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    users = await get_all_users()
    text = f"👥 *Foydalanuvchilar ({len(users)} ta):*\n\n"
    for u in users[:25]:
        uid, uname, fname, phone, balance = u
        text += f"👤 {fname} | 📱{phone or '—'} | 💰{int(balance):,}\n"
    if len(users) > 25:
        text += f"\n...va yana {len(users)-25} ta"
    await message.answer(text)

@dp.message_handler(lambda m: m.text == "💳 To'lovlar")
async def admin_payments(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    payments = await get_pending_payments()
    if not payments:
        await message.answer("Kutilayotgan to'lov yo'q ✅")
        return
    for p in payments:
        pid, uid, amount, card_type, card_number, status, created, fname, uname = p
        kb = types.InlineKeyboardMarkup()
        kb.add(
            types.InlineKeyboardButton("✅ O'tkazildi", callback_data=f"papprove_{pid}"),
            types.InlineKeyboardButton("❌ Rad etish", callback_data=f"preject_{pid}")
        )
        await message.answer(
            f"💳 *To'lov #{pid}*\n"
            f"👤 {fname}\n"
            f"💳 {card_type.upper()}: `{card_number}`\n"
            f"💰 *{int(amount):,} so'm*",
            reply_markup=kb
        )

@dp.message_handler(lambda m: m.text == "📢 Xabar yuborish")
async def admin_broadcast_start(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("📢 Barcha foydalanuvchilarga yuboriladigan xabarni kiriting:")
    await AdminState.broadcast.set()

@dp.message_handler(state=AdminState.broadcast)
async def admin_broadcast(message: types.Message, state: FSMContext):
    users = await get_all_users()
    sent = failed = 0
    for u in users:
        try:
            await bot.send_message(u[0], message.text)
            sent += 1
            await asyncio.sleep(0.05)
        except:
            failed += 1
    await message.answer(f"📢 Yuborildi!\n✅ {sent} ta\n❌ {failed} ta", reply_markup=admin_kb())
    await state.finish()

@dp.message_handler(lambda m: m.text == "⚙️ Sozlamalar")
async def admin_settings(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    vote_reward = await get("vote_reward")
    ref_reward = await get("referral_reward")
    uzcard = await get("uzcard_numbers")
    humo = await get("humo_numbers")
    click = await get("click_numbers")
    payme = await get("payme_numbers")

    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("💰 Ovoz mukofoti", callback_data="sset_vote_reward"),
        types.InlineKeyboardButton("👥 Referral mukofoti", callback_data="sset_referral_reward"),
        types.InlineKeyboardButton("💳 Uzcard raqami", callback_data="sset_uzcard_numbers"),
        types.InlineKeyboardButton("💳 Humo raqami", callback_data="sset_humo_numbers"),
        types.InlineKeyboardButton("💚 Click raqami", callback_data="sset_click_numbers"),
        types.InlineKeyboardButton("🔴 Payme raqami", callback_data="sset_payme_numbers"),
        types.InlineKeyboardButton("📝 Xush kelibsiz matni", callback_data="sset_welcome_text"),
    )
    await message.answer(
        f"⚙️ *Sozlamalar*\n\n"
        f"💰 Ovoz mukofoti: *{int(vote_reward):,} so'm*\n"
        f"👥 Referral mukofoti: *{int(ref_reward):,} so'm*\n"
        f"💳 Uzcard: `{uzcard or '—'}`\n"
        f"💳 Humo: `{humo or '—'}`\n"
        f"💚 Click: `{click or '—'}`\n"
        f"🔴 Payme: `{payme or '—'}`",
        reply_markup=kb
    )

@dp.callback_query_handler(lambda c: c.data.startswith("sset_"))
async def admin_setting_edit(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    key = callback.data[5:]
    await state.update_data(setting_key=key)
    await callback.message.answer(f"✏️ *{key}* uchun yangi qiymatni kiriting:")
    await AdminState.edit_setting_val.set()
    await callback.answer()

@dp.message_handler(state=AdminState.edit_setting_val)
async def admin_save_setting(message: types.Message, state: FSMContext):
    data = await state.get_data()
    key = data.get("setting_key")
    await set_setting(key, message.text.strip())
    await message.answer(f"✅ *{key}* yangilandi!", reply_markup=admin_kb())
    await state.finish()

@dp.message_handler(lambda m: m.text == "🔙 Asosiy menyu")
async def back_main(message: types.Message):
    await message.answer("Asosiy menyu 👇", reply_markup=main_kb())

# ══════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════
async def health_server():
    """Koyeb health check uchun mini HTTP server"""
    from aiohttp import web
    async def handle(request):
        return web.Response(text="OK")
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8000)
    await site.start()
    logger.info("Health check server port 8000 da ishga tushdi")

if __name__ == "__main__":
    async def on_startup(dp):
        await init_db()
        await health_server()
        logger.info("Bot ishga tushdi ✅")

    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
