# bot.py — Telegram gold bot (stable for Render Free)
# Runs with polling, opens a tiny HTTP server for port binding,
# and deletes webhook via a sync HTTP call before polling.

import os, re, time, sys, threading, http.server, socketserver
from zoneinfo import ZoneInfo
import datetime
import urllib.parse
import requests
from bs4 import BeautifulSoup

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters


# ----------------- Logging helper -----------------
def dprint(*a):
    print(*a, flush=True)


# ----------------- ENV -----------------
RAW_TOKEN = os.getenv("BOT_TOKEN", "")
BASE_URL = (os.getenv("BASE_URL", "") or "").rstrip("/")

def normalize_ascii_digits(s: str) -> str:
    table = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩：", "01234567890123456789:")
    return s.translate(table) if isinstance(s, str) else s

RAW_TOKEN = normalize_ascii_digits(RAW_TOKEN)

dprint("== DEBUG ==")
dprint("BOT_TOKEN present:", bool(RAW_TOKEN), "True length:", len(RAW_TOKEN))
dprint("BASE_URL:", BASE_URL if BASE_URL else "<EMPTY>")

if not RAW_TOKEN:
    dprint("FATAL: BOT_TOKEN is empty. Set it in Render → Environment.")
    time.sleep(10)
    sys.exit(1)

TELEGRAM_TOKEN = RAW_TOKEN


# ----------------- Utils -----------------
def to_toman(v):
    if v is None: return None
    return int(round(float(v) / 10.0))

def fmt(n):
    return "N/A" if n is None else f"{int(round(n)):,}".replace(",", "٬")

def pct(a):
    return "N/A" if a is None else f"{a:.2f}%"

def now_tehran_str():
    tz = ZoneInfo("Asia/Tehran")
    return datetime.datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S %Z")


# ----------------- Sources -----------------
ALANCHAND_GOLD  = "https://alanchand.com/en/gold-price"
ALANCHAND_COINS = "https://alanchand.com/en/iran-gold-coin-price"
TGJU_USD_URL    = "https://www.tgju.org/profile/price_dollar_rl"

def _extract_row(text: str, label: str):
    # expects lines like: market IRR ... real IRR ... bubble IRR(bubble %)
    m = re.search(
        rf"{re.escape(label)}\s+([\d,]+)\s+[-\d\.]+\s+([\d,]+)\s+([\d,]+)\(([-\d\.]+)%\)",
        text
    )
    if not m: return None
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
    tag = soup.find(attrs={"data-market-row":"price_dollar_rl"}) or soup.find(id="price_dollar_rl")
    cand = None
    if tag and tag.has_attr("data-price"):
        cand = tag["data-price"]
    if not cand and tag:
        m = re.search(r"([\d,]{5,})", tag.get_text(" ", strip=True))
        cand = m.group(1) if m else None
    if not cand:
        txt = soup.get_text(" ", strip=True)
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
    labels = {"emami":"Imami Gold Coin","half":"Half Bahar Azadi","quarter":"Quarter Bahar Azadi"}
    out = {}
    for k, l in labels.items():
        row = _extract_row(text, l)
        if row: out[k] = row
    if not out: raise RuntimeError("coin_parse_error")
    return out

def fetch_kahroba():
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


# ----------------- Build Message -----------------
def build_message() -> str:
    lines = [f"⏱ زمان درخواست (تهران): {now_tehran_str()}"]

    # 1-2) طلا و حباب
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

    # 3) دلار آزاد
    try:
        usd = fetch_usd()
        lines += ["—", "③ دلار آزاد:", f"• قیمت: {fmt(usd['usd_toman'])} تومان"]
    except Exception as e:
        lines += [f"— ③ دلار آزاد: خطا: {e!r}"]

    # 4-5) سکه و حباب
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
        if qr: lines.append(f"• ربع: {fmt(qr['bubble_toman'])} تومان ({pct_]()
