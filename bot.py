# -*- coding: utf-8 -*-
# Telegram Gold/FX Bot — PTB 21.7 — Python 3.11
# نسخه: ver 2025-10-08-3-rial  (همه‌ی خروجی‌ها به «ریال»)

import os, re, math, asyncio, logging
from datetime import datetime
from zoneinfo import ZoneInfo
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# -------------------- تنظیمات
TEHRAN_TZ = ZoneInfo("Asia/Tehran")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
PORT = int(os.environ.get("PORT", "10000"))

UA = {"User-Agent": "Mozilla/5.0 (+TelegramBot; PTB/21.7)"}
MESGHAL_IN_GRAM = 4.608  # 1 mesghal ≈ 4.608 gram

# AlanChand – مسیرهای پایدار
AL_GOLD18_URL = "https://alanchand.com/en/gold-price/18ayar"
AL_SEKKEH_URL = "https://alanchand.com/en/gold-price/sekkeh"
AL_NIM_URL    = "https://alanchand.com/en/gold-price/nim"
AL_ROB_URL    = "https://alanchand.com/en/gold-price/rob"
USD_URLS = [
    "https://alanchand.com/en/currency/dollar",
    "https://alanchand.com/en/currency/usd",
    "https://alanchand.com/en/dollar-price",
]

# -------------------- وب‌سرور کوچک برای Render (Port Binding)
def start_tiny_http_server():
    class Handler(BaseHTTPRequestHandler):
        def do_HEAD(self): self.send_response(200); self.end_headers()
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type","text/plain; charset=utf-8")
            self.end_headers(); self.wfile.write(b"OK")
        def log_message(self, *args): return
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", PORT), Handler).serve_forever(),
                     daemon=True).start()

# -------------------- کمک‌تابع‌ها
def now_tehran_str() -> str:
    return datetime.now(TEHRAN_TZ).strftime("%Y-%m-%d %H:%M:%S %z")

def fmt_int(n: int | None) -> str:
    return "N/A" if n is None else f"{n:,}".replace(",", "٬")

def fmt_pct(x: float | None) -> str:
    return "N/A" if x is None else f"{x:.2f}%"

def rial(n_toman: int | None) -> int | None:
    """تبدیل تومان به ریال (همه خروجی‌ها ریالی است)."""
    return None if n_toman is None else int(n_toman) * 10

def pull(url: str) -> BeautifulSoup:
    r = requests.get(url, timeout=25, headers=UA)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")

# --- تشخیص عدد + واحد (Rial/Toman) از متن انگلیسی صفحه
NUM = r"([0-9][0-9,\.]*)"
def to_int_digits(s: str | None) -> int | None:
    if not s: return None
    s = re.sub(r"[^\d]", "", s)
    return int(s) if s else None

def parse_value_with_unit(page_text: str) -> tuple[int | None, str | None]:
    """
    مقدار بازار را با واحد می‌خوانیم؛ خروجی «تومان» است اگر واحد تومان بود
    و اگر واحد ریال بود به تومان تبدیل می‌کنیم (÷۱۰). بعداً برای نمایش ×۱۰
    می‌شود و همه چیز به ریال خواهد بود.
    """
    txt = page_text

    # 1) was X Iranian Rials
    m = re.search(rf"was\s+{NUM}\s+Iranian\s+Rials", txt, re.I)
    if m:
        val = to_int_digits(m.group(1))
        return ((val // 10) if val is not None else None), "Rial"

    # 2) was X (Iranian )?Tomans
    m = re.search(rf"was\s+{NUM}\s+(Iranian\s+)?Tomans?", txt, re.I)
    if m:
        val = to_int_digits(m.group(1))
        return (val, "Toman")

    # 3) Real Price X (Rials/Tomans)
    m = re.search(rf"Real\s+Price\s*{NUM}\s*(Iranian\s+)?(Rials?|Tomans?)?", txt, re.I)
    if m:
        val = to_int_digits(m.group(1))
        unit = (m.group(2) or "").lower()
        if "rial" in unit:
            return (val // 10 if val else None), "Rial"
        return (val, "Toman")

    # 4) فالبک
    cands = re.findall(NUM, txt)
    if cands:
        val = to_int_digits(max(cands, key=lambda s: len(s)))
        if val is None: return None, None
        if val >= 10_000_000:
            return val // 10, "Rial?"
        return val, "Toman?"

    return None, None

def alan_market_and_real(soup: BeautifulSoup) -> tuple[int | None, int | None]:
    txt = soup.get_text(" ", strip=True)
    # market
    m_val, _ = parse_value_with_unit(txt)
    # real price
    real = None
    m2 = re.search(rf"Real\s+Price\s*{NUM}\s*(Iranian\s+)?(Rials?|Tomans?)?", txt, re.I)
    if m2:
        v = to_int_digits(m2.group(1))
        unit = (m2.group(2) or "").lower()
        real = (v // 10) if (v and "rial" in unit) else v
    return m_val, real

def calc_bubble(market_tmn: int | None, real_tmn: int | None) -> tuple[int | None, float | None]:
    if not market_tmn or not real_tmn: return None, None
    diff = market_tmn - real_tmn
    pct  = (diff / real_tmn) * 100
    return diff, pct

# -------------------- طلا (بر حسب تومان خوانده می‌شود، ریالی گزارش می‌شود)
def fetch_gold() -> dict:
    soup = pull(AL_GOLD18_URL)
    g_market, g_real = alan_market_and_real(soup)
    if g_market is None:
        raise RuntimeError("gold_parse_error")

    m_market = int(round(g_market * MESGHAL_IN_GRAM)) if g_market else None
    m_real   = int(round(g_real   * MESGHAL_IN_GRAM)) if g_real   else None

    g_b_t, g_b_p = calc_bubble(g_market, g_real)
    m_b_t, m_b_p = calc_bubble(m_market, m_real)
    return {
        # تومان
        "gram_tmn":    {"m": g_market, "r": g_real, "b_t": g_b_t, "b_p": g_b_p},
        "mesghal_tmn": {"m": m_market, "r": m_real, "b_t": m_b_t, "b_p": m_b_p},
    }

# -------------------- دلار آزاد (تومان → ریال)
def fetch_usd_free_tmn() -> int | None:
    for url in USD_URLS:
        try:
            soup = pull(url)
            val, _ = parse_value_with_unit(soup.get_text(" ", strip=True))
            if val: return val
        except Exception:
            continue
    return None

# -------------------- سکه‌ها (تومان → ریال)
def fetch_coins_tmn() -> dict:
    def one(url: str) -> dict:
        soup = pull(url)
        m, r = alan_market_and_real(soup)
        if m is None: raise RuntimeError(f"coin_parse_error:{url}")
        b_t, b_p = calc_bubble(m, r)
        return {"m": m, "r": r, "b_t": b_t, "b_p": b_p}
    return {
        "emami": one(AL_SEKKEH_URL),
        "nim":   one(AL_NIM_URL),
        "rob":   one(AL_ROB_URL),
    }

# -------------------- کهربا (فعلاً N/A)
def fetch_kahroba_tmn() -> dict:
    return {"price": None, "nav": None, "prem_t": None, "prem_p": None}

# -------------------- پیام‌ساز (همه چیز به ریال)
VERSION = "ver 2025-10-08-3-rial"

def build_message() -> str:
    lines = []
    lines.append(f"⏱ زمان درخواست (تهران): {now_tehran_str()} — {VERSION}")
    lines.append("✅ همه مقادیر: «ریال»")

    # طلا
    try:
        g = fetch_gold()
        # تبدیل تومان → ریال
        gram_m = rial(g["gram_tmn"]["m"])
        gram_r = rial(g["gram_tmn"]["r"])
        gram_bt = rial(g["gram_tmn"]["b_t"]) if g["gram_tmn"]["b_t"] is not None else None

        mes_m = rial(g["mesghal_tmn"]["m"])
        mes_r = rial(g["mesghal_tmn"]["r"])
        mes_bt = rial(g["mesghal_tmn"]["b_t"]) if g["mesghal_tmn"]["b_t"] is not None else None

        lines.append("① طلا ۱۸ عیار:")
        lines.append(f"* قیمت (هر گرم): {fmt_int(gram_m)} ریال")
        lines.append(f"* حباب (گرم): {fmt_int(gram_bt)} ریال ({fmt_pct(g['gram_tmn']['b_p'])})")
        lines.append(f"* قیمت (هر مثقال): {fmt_int(mes_m)} ریال")
        lines.append(f"* حباب (مثقال): {fmt_int(mes_bt)} ریال ({fmt_pct(g['mesghal_tmn']['b_p'])})")
    except Exception as e:
        lines.append(f"❗️دریافت قیمت طلا خطا: {repr(e)}")

    # دلار
    try:
        usd_tmn = fetch_usd_free_tmn()
        usd_irr = rial(usd_tmn)
        lines.append("③ دلار آزاد:")
        lines.append(f"* قیمت: {fmt_int(usd_irr)} ریال" if usd_irr else "* قیمت: N/A")
    except Exception as e:
        lines.append(f"③ دلار آزاد: خطا: {repr(e)}")

    # سکه‌ها
    try:
        c = fetch_coins_tmn()
        em_m, em_bt = rial(c["emami"]["m"]), rial(c["emami"]["b_t"]) if c["emami"]["b_t"] is not None else None
        nm_m, nm_bt = rial(c["nim"]["m"]),   rial(c["nim"]["b_t"])   if c["nim"]["b_t"]   is not None else None
        rb_m, rb_bt = rial(c["rob"]["m"]),   rial(c["rob"]["b_t"])   if c["rob"]["b_t"]   is not None else None
        lines.append("④/⑤ سکه:")
        lines.append(f"* تمام (امامی): {fmt_int(em_m)} ریال — حباب: {fmt_int(em_bt)} ریال ({fmt_pct(c['emami']['b_p'])})")
        lines.append(f"* نیم: {fmt_int(nm_m)} ریال — حباب: {fmt_int(nm_bt)} ریال ({fmt_pct(c['nim']['b_p'])})")
        lines.append(f"* ربع: {fmt_int(rb_m)} ریال — حباب: {fmt_int(rb_bt)} ریال ({fmt_pct(c['rob']['b_p'])})")
    except Exception as e:
        lines.append(f"④/⑤ سکه: خطا: {repr(e)}")

    # کهربا
    try:
        k = fetch_kahroba_tmn()
        lines.append("⑥ صندوق طلا «کهربا»:")
        lines.append(f"* قیمت: {fmt_int(rial(k['price']))} ریال" if k["price"] else "* قیمت: N/A")
        lines.append(f"* NAV: {fmt_int(rial(k['nav']))} ریال" if k["nav"] else "* NAV: N/A")
        prem_t_irr = rial(k["prem_t"]) if k["prem_t"] is not None else None
        lines.append(f"* اختلاف با NAV: " + (f"{fmt_int(prem_t_irr)} ریال ({fmt_pct(k['prem_p'])})" if prem_t_irr is not None else "N/A (N/A)"))
    except Exception as e:
        lines.append(f"⑥ کهربا: خطا: {repr(e)}")

    return "\n".join(lines)

# -------------------- هندلرها
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("سلام! برای دریافت قیمت‌ها «طلا» یا /gold را بفرست.\nهمه اعداد به «ریال» هستند.\n"+VERSION)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("کلمهٔ «طلا» یا دستور /gold را بفرست.\nهمه اعداد به «ریال» هستند.\n"+VERSION)

async def cmd_gold(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(build_message(), disable_web_page_preview=True)

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    txt = (update.message.text or "").strip()
    if "طلا" in txt or "قیمت" in txt:
        return await cmd_gold(update, context)
    await update.message.reply_text("برای دریافت قیمت‌ها «طلا» را بفرست.\nهمه اعداد به «ریال» هستند.\n"+VERSION)

# -------------------- main
def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN not set")

    start_tiny_http_server()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("gold", cmd_gold))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    async def _run():
        try:
            await app.bot.delete_webhook(drop_pending_updates=True)
        except Exception:
            pass
        await app.initialize(); await app.start()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        while True:
            await asyncio.sleep(3600)

    asyncio.run(_run())

if __name__ == "__main__":
    main()
