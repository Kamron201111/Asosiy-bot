import aiohttp
import asyncio
import re
import logging
from PIL import Image
import pytesseract
import io
import base64

logger = logging.getLogger(__name__)

BASE_URL = "https://openbudget.uz"

async def submit_phone(session: aiohttp.ClientSession, project_url: str, phone: str):
    """Saytga telefon raqamini kiritadi va SMS yuboradi"""
    try:
        # Avval saytni ochib session olamiz
        async with session.get(project_url) as resp:
            html = await resp.text()

        # CSRF token izlash
        csrf = re.search(r'name=["\']_token["\'] value=["\']([^"\']+)["\']', html)
        csrf_token = csrf.group(1) if csrf else ""

        # Captcha rasm URL ni topish
        captcha_url = re.search(r'src=["\']([^"\']*captcha[^"\']*)["\']', html)

        captcha_text = ""
        if captcha_url:
            cap_url = captcha_url.group(1)
            if not cap_url.startswith("http"):
                cap_url = BASE_URL + cap_url
            captcha_text = await solve_captcha(session, cap_url)

        # Telefon raqamni formatlash
        clean_phone = phone.replace("+", "").replace(" ", "").replace("-", "")
        if clean_phone.startswith("998"):
            clean_phone = clean_phone[3:]

        # Form data
        form_data = {
            "_token": csrf_token,
            "phone": clean_phone,
            "captcha": captcha_text,
        }

        # Form action URL topish
        action = re.search(r'<form[^>]*action=["\']([^"\']+)["\']', html)
        post_url = action.group(1) if action else project_url
        if not post_url.startswith("http"):
            post_url = BASE_URL + post_url

        async with session.post(post_url, data=form_data, allow_redirects=True) as resp:
            result_html = await resp.text()
            # SMS kod yuborildi belgisi
            if any(x in result_html.lower() for x in ["sms", "kod", "code", "tasdiqlash", "confirm"]):
                return True, result_html
            else:
                return False, result_html

    except Exception as e:
        logger.error(f"submit_phone xato: {e}")
        return False, str(e)

async def submit_sms_code(session: aiohttp.ClientSession, project_url: str, phone: str, code: str):
    """SMS kodni saytga kiritadi"""
    try:
        clean_phone = phone.replace("+", "").replace(" ", "").replace("-", "")
        if clean_phone.startswith("998"):
            clean_phone = clean_phone[3:]

        # Tasdiqlash sahifasini ochish
        confirm_url = project_url
        async with session.get(confirm_url) as resp:
            html = await resp.text()

        csrf = re.search(r'name=["\']_token["\'] value=["\']([^"\']+)["\']', html)
        csrf_token = csrf.group(1) if csrf else ""

        action = re.search(r'<form[^>]*action=["\']([^"\']+)["\']', html)
        post_url = action.group(1) if action else project_url
        if not post_url.startswith("http"):
            post_url = BASE_URL + post_url

        form_data = {
            "_token": csrf_token,
            "phone": clean_phone,
            "code": code,
            "sms_code": code,
            "otp": code,
        }

        async with session.post(post_url, data=form_data, allow_redirects=True) as resp:
            result_html = await resp.text()
            status_code = resp.status

            if any(x in result_html.lower() for x in ["muvaffaqiyatli", "success", "tasdiqlandi", "rahmat"]):
                return True, "success"
            elif any(x in result_html.lower() for x in ["xato", "error", "noto'g'ri", "wrong"]):
                return False, "wrong_code"
            else:
                return True, "submitted"

    except Exception as e:
        logger.error(f"submit_sms_code xato: {e}")
        return False, str(e)

async def solve_captcha(session: aiohttp.ClientSession, captcha_url: str) -> str:
    """Captcha rasmini o'qiydi — oddiy kulrang fon, oq raqamlar"""
    try:
        async with session.get(captcha_url) as resp:
            img_bytes = await resp.read()

        img = Image.open(io.BytesIO(img_bytes))
        # Kulrang fon, oq matn — kontrast oshirish
        img = img.convert("L")  # grayscale
        # Oq raqamlarni ajratish
        from PIL import ImageEnhance, ImageFilter
        img = img.filter(ImageFilter.SHARPEN)
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(3.0)

        text = pytesseract.image_to_string(
            img,
            config="--psm 8 -c tessedit_char_whitelist=0123456789"
        )
        result = re.sub(r"[^0-9]", "", text).strip()
        logger.info(f"Captcha o'qildi: {result}")
        return result
    except Exception as e:
        logger.error(f"Captcha xato: {e}")
        return ""

async def check_vote_result(phone: str, check_url: str, vote_time: str) -> bool:
    """1 soatdan keyin ovoz natijasini tekshiradi"""
    try:
        clean_phone = phone.replace("+", "").replace(" ", "").replace("-", "")
        last4 = clean_phone[-4:]

        async with aiohttp.ClientSession() as session:
            async with session.get(check_url) as resp:
                html = await resp.text()

        # Oxirgi 4 raqamni topish
        if last4 in html:
            return True
        return False
    except Exception as e:
        logger.error(f"check_vote_result xato: {e}")
        return False
