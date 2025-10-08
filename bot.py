# -*- coding: utf-8 -*-
# Telegram Gold/FX Bot — PTB 21.7 — Python 3.11
# نویسنده: شما :)
# نکته: توکن را از ENV با نام BOT_TOKEN بردارید.

import os, re, math, asyncio, logging, json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters
)

# -------------------- تنظیمات اصلی
TEHRAN_TZ = ZoneInfo("Asia/Tehran")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()

# اگر روی Render هستید، می‌توانید BASE_URL محیطی هم داشته باشید (اختیاری)
BASE_URL = os.environ.get("BASE_URL", "").strip()

# برای Render: پرتاب یک وب‌سرور کوچک تا Port-Binding برقرار باشد
# (این سرور فقط هدر پاسخ می‌دهد و کاری با بات ندارد)
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
PORT = int(os.environ.get("PORT", "10000"))

def start_tiny_http_server():
    class Handler(BaseHTTPRequestHandler):
        def do_HEAD(self):
            self.send_response(200); self.end_headers()
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type","text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"OK")
        def log_message(self, *args): return
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", PORT), Handler).serve_forever(), daemon=True).start()

# -------------------- کمک‌تابع‌ها
_re_num = re.compile(r"([0-9][0-9,\.]*)")

def ir_to_toman(x_irr: int | None) -> int | None:
    if x_irr is None: return None
    return int(round(x_irr / 10))

def to_int_digits(s: str | None) -> int | None:
    if not s: return None
    s = re.sub(r"[^\d]", "", s)
    return int(s) if s else None

def fmt_int(n: int | None) -> str:
    if n is None: return "N/A"
    return f"{n:,}".replace(",", "٬")  # جداکننده فارسی

def fmt_pct(x: float | None) -> str:
    if x is None: return "N/A"
    return f"{x:.2f}%"

def now_tehran_str() -> str:
    dt = datetime.now(TEHRAN_TZ)
    return dt.strftime("%Y-%m-%d %H:%M:%S %z")

# -------------------- منابع (AlanChand پایدار)
# طلا 18 عیار (گرم)
AL_GOLD18_URL = "https://alanchand.com/en/gold-price/18ayar"
# سکه‌ها
AL_SEKKEH_URL = "https://alanchand.com/en/gold-price/sekkeh"  # تمام (امامی)
AL_NIM_URL    = "https://alanchand.com/en/gold-price/nim"     # نیم
AL_ROB_URL    = "https://alanchand.com/en/gold-price/rob"     # ربع
# دلار آزاد — چند مسیر احتمالی (اولی که جواب داد)
USD_URLS = [
    "https://alanchand.com/en/currency/dollar",
    "https://alanchand.com/en/currency/usd",
    "https://alanchand.com/en/dollar-price",
]

MESGHAL_IN_GRAM = 4.608  # 1 mesghal ≈ 4.608 gram

UA = {"User-Agent": "Mozilla/5.0 (+TelegramBot; compatible; PTB/21.7)"}

def pull(url: str) -> BeautifulSoup:
    r = requests.get(url, timeout=20, headers=UA)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")

def alan_parse_market_and_real(soup: BeautifulSoup) -> tuple[int | None, int | None]:
    """
    از متن صفحه AlanChand مقدارهای «Market price ... [IRR]» و «Real Price ...» را در می‌آوریم.
    خروجی به ریال است.
    """
    txt = soup.get_text(" ", strip=True)
    # Market: جمله‌هایی شبیه "the price ... was X Iranian Rials"
    m1 = re.search(r"was\s+([0-9,]+)\s+Iranian Rials", txt, flags=re.I)
    market = to_int_digits(m1.group(1)) if m1 else None
    # Real Price
    m2 = re.search(r"Real Price\s*([0-9,]+)", txt, flags=re.I)
    real = to_int_digits(m2.group(1)) if m2 else None
    # fallback: بزرگ‌ترین عدد صفحه
    if market is None:
        cand = _re_num.findall(txt)
        if cand:
            market = to_int_digits(max(cand, key=lambda s: len(s)))
    return market, real

def calc_bubble(market_tmn: int | None, real_tmn: int | None) -> tuple[int | None, float | None]:
    if not market_tmn or not real_tmn: return None, None
    diff = market_tmn - real_tmn
    pct  = (diff / real_tmn) * 100
    return diff, pct

# -------------------- طلا (گرم/مثقال)
def fetch_gold() -> dict:
    """
    خروجی به تومان:
    {
      'gram':    {'m':..., 'r':..., 'b_t':..., 'b_p':...},
      'mesghal': {'m':..., 'r':..., 'b_t':..., 'b_p':...}
    }
    """
    soup = pull(AL_GOLD18_URL)
    g_market_irr, g_real_irr = alan_parse_market_and_real(soup)
    if g_market_irr is None:
        raise RuntimeError("gold_parse_error")

    g_market = ir_to_toman(g_market_irr)
    g_real   = ir_to_toman(g_real_irr) if g_real_irr else None

    m_market = int(round((g_market or 0) * MESGHAL_IN_GRAM)) if g_market else None
    m_real   = int(round((g_real or 0)   * MESGHAL_IN_GRAM)) if g_real else None

    g_b_t, g_b_p = calc_bubble(g_market, g_real)
    m_b_t, m_b_p = calc_bubble(m_market, m_real)

    return {
        "gram":    {"m": g_market, "r": g_real, "b_t": g_b_t, "b_p": g_b_p},
        "mesghal": {"m": m_market, "r": m_real, "b_t": m_b_t, "b_p": m_b_p},
    }

# -------------------- دلار آزاد
def fetch_usd_free() -> int | None:
    """
    تلاش از چند URL و استخراج اولین عدد بزرگ به ریال → تبدیل به تومان.
    """
    for url in USD_URLS:
        try:
            soup = pull(url)
            market_irr, _ = alan_parse_market_and_real(soup)
            if market_irr:
                return ir_to_toman(market_irr)
            # fallback: بزرگ‌ترین عدد صفحه
            txt = soup.get_text(" ", strip=True)
            cand = _re_num.findall(txt)
            if cand:
                val_irr = to_int_digits(max(cand, key=lambda s: len(s)))
                if val_irr:
                    return ir_to_toman(val_irr)
        except Exception:
            continue
    return None

# -------------------- سکه‌ها
def fetch_coins() -> dict:
    """
    {
      'emami': {'m':..., 'r':..., 'b_t':..., 'b_p':...},
      'nim': {...}, 'rob': {...}
    }
    """
    def one(url: str) -> dict:
        soup = pull(url)
        m_irr, r_irr = alan_parse_market_and_real(soup)
        if m_irr is None:
            raise RuntimeError(f"coin_parse_error:{url}")
        m = ir_to_toman(m_irr)
        r = ir_to_toman(r_irr) if r_irr else None
        b_t, b_p = calc_bubble(m, r)
        return {"m": m, "r": r, "b_t": b_t, "b_p": b_p}

    return {
        "emami": one(AL_SEKKEH_URL),
        "nim":   one(AL_NIM_URL),
        "rob":   one(AL_ROB_URL),
    }

# -------------------- کهربا (جایگزین ساده)
def fetch_kahroba() -> dict:
    """
    چون منبع پایدار عمومی برای NAV آنلاین نداریم، این تابع فعلاً N/A می‌دهد.
    اگر بعداً نماد و API بدی (TSETMC/rahavard)، پرش می‌کنم.
    """
    return {"price": None, "nav": None, "prem_t": None, "prem_p": None}

# -------------------- پیام‌ساز
def build_message() -> str:
    lines = []
    lines.append(f"⏱ زمان درخواست (تهران): {now_tehran_str()}")

    # 1/2 طلا
    try:
        g = fetch_gold()
        lines.append("① طلا ۱۸ عیار (گرم):")
        lines.append(f"* قیمت: {fmt_int(g['gram']['m'])} تومان")
        lines.append(f"* حباب: {fmt_int(g['gram']['b_t'])} تومان ({fmt_pct(g['gram']['b_p'])})")
        lines.append("② طلا (مثقال):")
        lines.append(f"* قیمت: {fmt_int(g['mesghal']['m'])} تومان")
        lines.append(f"* حباب: {fmt_int(g['mesghal']['b_t'])} تومان ({fmt_pct(g['mesghal']['b_p'])})")
    except Exception as e:
        lines.append(f"❗️دریافت قیمت طلا خطا: {repr(e)}")

    # 3 دلار
    try:
        usd = fetch_usd_free()
        if usd:
            lines.append("③ دلار آزاد:")
            lines.append(f"* قیمت: {fmt_int(usd)} تومان")
        else:
            lines.append("③ دلار آزاد: N/A")
    except Exception as e:
        lines.append(f"③ دلار آزاد: خطا: {repr(e)}")

    # 4/5 سکه
    try:
        c = fetch_coins()
        lines.append("④/⑤ سکه (بازار):")
        lines.append(f"* تمام (امامی): {fmt_int(c['emami']['m'])} تومان — حباب: {fmt_int(c['emami']['b_t'])} ({fmt_pct(c['emami']['b_p'])})")
        lines.append(f"* نیم: {fmt_int(c['nim']['m'])} تومان — حباب: {fmt_int(c['nim']['b_t'])} ({fmt_pct(c['nim']['b_p'])})")
        lines.append(f"* ربع: {fmt_int(c['rob']['m'])} تومان — حباب: {fmt_int(c['rob']['b_t'])} ({fmt_pct(c['rob']['b_p'])})")
    except Exception as e:
        lines.append(f"④/⑤ سکه: خطا: {repr(e)}")

    # 6 کهربا
    try:
        k = fetch_kahroba()
        lines.append("⑥ صندوق طلا «کهربا»:")
        lines.append(f"* قیمت: {fmt_int(k['price'])} تومان")
        lines.append(f"* NAV: {fmt_int(k['nav'])} تومان")
        if k['prem_t'] is None:
            lines.append(f"* اختلاف با NAV: N/A (N/A)")
        else:
            lines.append(f"* اختلاف با NAV: {fmt_int(k['prem_t'])} ({fmt_pct(k['prem_p'])})")
    except Exception as e:
        lines.append(f"⑥ کهربا: خطا: {repr(e)}")

    return "\n".join(lines)

# -------------------- هندلرها
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "سلام! برای دریافت قیمت‌ها «طلا» رو بفرست.\n"
        "دستورات: /start /help"
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("کلمهٔ «طلا» یا دستور /gold را بفرست.")

async def cmd_gold(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = build_message()
    await update.message.reply_text(msg, disable_web_page_preview=True)

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    txt = (update.message.text or "").strip()
    if txt and ("طلا" in txt or "قیمت" in txt):
        return await cmd_gold(update, context)
    # اگر چیز دیگری بود:
    await update.message.reply_text("برای دریافت قیمت‌ها «طلا» را بفرست.")

# -------------------- main
def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN not set")

    # وب‌سرور کوچک برای Render
    start_tiny_http_server()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("gold", cmd_gold))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    # چون روی Render از Polling استفاده می‌کنیم، مطمئن می‌شویم Webhook خاموش است
    async def _run():
        try:
            await app.bot.delete_webhook(drop_pending_updates=True)
        except Exception:
            pass
        await app.initialize()
        await app.start()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        # نگه‌داشتن حلقه
        while True:
            await asyncio.sleep(3600)

    asyncio.run(_run())

if __name__ == "__main__":
    main()
