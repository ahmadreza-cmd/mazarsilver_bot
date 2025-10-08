# bot.py — Telegram gold bot (stable on Render Free)
# - Uses polling (not webhook)
# - Starts a tiny HTTP server to satisfy Render port binding
# - Always deletes webhook before polling to avoid Conflict

import os, re, time, sys, threading, http.server, socketserver, asyncio
from zoneinfo import ZoneInfo
import datetime
import urllib.parse

import requests
from bs4 import BeautifulSoup

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters


# ----------------- Logging helper -----------------
def dprint(*a):  # print with flush (visible in Render logs)
    print(*a, flush=True)


# ----------------- ENV -----------------
RAW_TOKEN = os.getenv("BOT_TOKEN", "")
BASE_URL = (os.getenv("BASE_URL", "") or "").rstrip("/")

def normalize_ascii_digits(s: str) -> str:
    # convert Persian/Arabic digits & colon to ASCII (if someone pasted them)
    table = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩：", "01234567890123456789:")
    return s.translate(table) if isinstance(s, str) else s

RAW_TOKEN = normalize_ascii_digits(RAW_TOKEN)

dprint("== DEBUG ==")
dprint("BOT_TOKEN present:", bool(RAW_TOKEN), "length:", len(RAW_TOKEN))
dprint("BASE_URL:", BASE_URL if BASE_URL else "<EMPTY>")

if not RAW_TOKEN:
    dprint("FATAL: BOT_TOKEN is empty. Set it in Render → Environment.")
    time.sleep(10)
    sys.exit(1)

TELEGRAM_TOKEN = RAW_TOKEN


# ----------------- Utils -----------------
def to_toman(v: int | float | None) -> int | None:
    if v is None: return None
    return int(round(float(v) / 10.0))

def fmt(n: int | float | None) -> str:
    return "N/A" if n is None else f"{int(round(n)):,}".replace(",", "٬")

def pct(a: float | None) -> str:
    return "N/A" if a is None else f"{a:.2f}%"

def now_tehran_str() -> str:
    tz = ZoneInfo("Asia/Tehran")
    return datetime.datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S %Z")


# ----------------- Sources -----------------
ALANCHAND_GOLD  = "https://alanchand.com/en/gold-price"
ALANCHAND_COINS = "https://alanchand.com/en/iran-gold-coin-price"
TGJU_USD_URL    = "https://www.tgju.org/profile/price_dollar_rl"


def _extract_row(text: str, label: str):
    # Matches: Market IRR, Real IRR, Bubble IRR, Bubble %
    m = re.search(
        rf"{re.escape(label)}\s+([\d,]+)\s+[-\d\.]+\s+([\d,]+)\s+([\d,]+)\(([-\d\.]+)%\)",
        text
    )
    if not m:
        return None
    market_irr = int(m.group(1).replace(",", ""))
    real_irr   = int(m.group(2).replace(",", ""))
    bubble_irr = int(m.group(3).replace(",", ""))
    bubble_pct = float(m.group(4))
    return {
        "market_toman": to_toman(market_irr),
        "real_toman":   to_toman(real_irr),
        "bubble_toman": to_toman(bubble_irr),
        "bubble_pct":   bubble_pct,
    }


def fetch_gold_and_bubble():
    r = requests.get(ALANCHAND_GOLD, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    g18  = _extract_row(text, "18K Gold per Gram")
    msgl = _extract_row(text, "Raw 24K Gold (Mesghal)")
    if not (g18 and msgl):
        raise RuntimeError("gold_parse_error")
    return {"gram18": g18, "mesghal": msgl}


def fetch_usd():
    r = requests.get(TGJU_USD_URL, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    txt  = soup.get_text(" ", strip=True)

    # Prefer data attribute if exists
    tag = soup.find(attrs={"data-market-row": "price_dollar_rl"}) or soup.find(id="price_dollar_rl")
    cand = None
    if tag and tag.has_attr("data-price"):
        cand = tag["data-price"]
    if not cand and tag:
        m = re.search(r"([\d,]{5,})", tag.get_text(" ", strip=True))
        cand = m.group(1) if m else None
    if not cand:
        m = re.search(r"([\d,]{6,})\s*ریال", txt)
        cand = m.group(1) if m else None
    if not cand:
        raise RuntimeError("usd_parse_error")

    irr = int(cand.replace(",", ""))
    return {"usd_toman": to_toman(irr)}


def fetch_coins():
    r = requests.get(ALANCHAND_COINS, timeout=15)
    r.raise_for_status()
    text = BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True)

    labels = {
        "emami":  "Imami Gold Coin",
        "half":   "Half Bahar Azadi",
        "quarter":"Quarter Bahar Azadi",
    }
    out = {}
    for k, l in labels.items():
        row = _extract_row(text, l)
        if row: out[k] = row
    if not out:
        raise RuntimeError("coin_parse_error")
    return out


def fetch_kahroba():
    # TSETMC JSON endpoints
    try:
        q = urllib.parse.quote("کهربا")
        s = requests.get(
            f"https://cdn.tsetmc.com/api/Instrument/GetInstrumentSearch/{q}",
            timeout=15, headers={"User-Agent":"Mozilla/5.0"}
        ).json()
        items = s.get("instrumentSearch", []) if isinstance(s, dict) else s
        ins = next((i for i in items if i.get("lVal18AFC") == "کهربا"), (items[0] if items else None))
        if not ins:
            return {"symbol":"کهربا","price_toman":None,"nav_toman":None,"prem_toman":None,"prem_pct":None}

        code = ins.get("insCode")
        p = requests.get(
            f"https://cdn.tsetmc.com/api/ClosingPrice/GetClosingPriceInfo/{code}",
            timeout=15, headers={"User-Agent":"Mozilla/5.0"}
        ).json()
        price = (p.get("closingPriceInfo") or {}).get("pClosing") or (p.get("closingPriceInfo") or {}).get("pDrCotVal")

        f = requests.get(
            f"https://cdn.tsetmc.com/api/Fund/GetFund/{code}",
            timeout=15, headers={"User-Agent":"Mozilla/5.0"}
        ).json()
        nav = (f.get("fund") or {}).get("navPS")

        if not (price and nav):
            return {"symbol":ins.get("lVal18AFC"),"price_toman":None,"nav_toman":None,"prem_toman":None,"prem_pct":None}

        price_tmn = to_toman(price)
        nav_tmn   = to_toman(nav)
        prem_tmn  = price_tmn - nav_tmn
        prem_pctv = (prem_tmn / nav_tmn * 100.0) if nav_tmn else None

        return {
            "symbol": ins.get("lVal18AFC"),
            "price_toman": price_tmn,
            "nav_toman":   nav_tmn,
            "prem_toman":  prem_tmn,
            "prem_pct":    prem_pctv
        }
    except Exception:
        return {"symbol":"کهربا","price_toman":None,"nav_toman":None,"prem_toman":None,"prem_pct":None}


def build_message() -> str:
    lines = [f"⏱ زمان درخواست (تهران): {now_tehran_str()}"]

    # Gold & bubble
    try:
        g = fetch_gold_and_bubble()
        g18, ms = g["gram18"], g["mesghal"]
        lines += [
            "—",
            "① قیمت طلا (تومان):",
            f"• هر گرم ۱۸: {fmt(g18['market_toman'])}",
            f"• هر مثقال: {fmt(ms['market_toman'])}",
            "② حباب طلا:",
            f"• گرم ۱۸: {fmt(g18['bubble_toman'])} تومان ({pct(g18['bubble_pct'])})",
            f"• مثقال: {fmt(ms['bubble_toman'])} تومان ({pct(ms['bubble_pct'])})",
        ]
    except Exception as e:
        lines += [f"❗️دریافت قیمت طلا خطا: {e!r}"]

    # USD
    try:
        usd = fetch_usd()
        lines += ["—", "③ دلار آزاد:", f"• قیمت: {fmt(usd['usd_toman'])} تومان"]
    except Exception as e:
        lines += [f"— ③ دلار آزاد: خطا: {e!r}"]

    # Coins
    try:
        c = fetch_coins()
        em, hf, qr = c.get("emami"), c.get("half"), c.get("quarter")
        lines += ["—", "④ قیمت سکه:"]
        if em: lines.append(f"• امامی: {fmt(em['market_toman'])} تومان")
        if hf: lines.append(f"• نیم: {fmt(hf['market_toman'])} تومان")
        if qr: lines.append(f"• ربع: {fmt(qr['market_toman'])} تومان")
        lines += ["⑤ حباب سکه:"]
        if em: lines.append(f"• امامی: {fmt(em['bubble_toman'])} تومان ({pct(em['bubble_pct'])})")
        if hf: lines.append(f"• نیم: {fmt(hf['bubble_toman'])} تومان ({pct(hf['bubble_pct'])})")
        if qr: lines.append(f"• ربع: {fmt(qr['bubble_toman'])} تومان ({pct(qr['bubble_pct'])})")
    except Exception as e:
        lines += [f"— ④/⑤ سکه: خطا: {e!r}"]

    # ETF (Kahroba)
    k = fetch_kahroba()
    lines += [
        "—",
        f"⑥ صندوق طلا «{k.get('symbol','کهربا')}»:",
        f"• قیمت: {fmt(k['price_toman'])} تومان",
        f"• NAV: {fmt(k['nav_toman'])} تومان",
        f"• اختلاف با NAV: {'N/A' if k['prem_toman'] is None else (fmt(k['prem_toman'])+' تومان')} ({pct(k['prem_pct'])})",
    ]

    return "\n".join(lines)


# ----------------- Telegram handlers -----------------
async def send_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(build_message())

async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سلام! «طلا» یا «/gold» را بفرست.")


def make_application():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(CommandHandler("gold", send_reply))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, send_reply))
    return app


# ----------------- Tiny HTTP server (for Render port binding) -----------------
PORT = int(os.environ.get("PORT", "8080"))

class _Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stdout.write("[HTTP] " + (fmt % args) + "\n")
        sys.stdout.flush()
    def do_GET(self):
        msg = "ok\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(msg)))
        self.end_headers()
        self.wfile.write(msg.encode("utf-8"))

def _start_http_server():
    def _run():
        with socketserver.TCPServer(("", PORT), _Handler) as httpd:
            dprint(f"HTTP server listening on 0.0.0.0:{PORT}")
            httpd.serve_forever()
    threading.Thread(target=_run, daemon=True).start()


# ----------------- Main -----------------
if __name__ == "__main__":
    try:
        dprint("Starting tiny HTTP server + Telegram polling ...")
        _start_http_server()
        application = make_application()

        # مهم: قبل از polling وبهوک را حذف کن تا Conflict پیش نیاید
        asyncio.run(application.bot.delete_webhook(drop_pending_updates=True))

        # شروع polling
        application.run_polling(drop_pending_updates=True)

    except Exception as e:
        dprint("FATAL EXCEPTION:", repr(e))
        time.sleep(10)
        raise
