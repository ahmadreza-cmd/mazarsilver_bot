# bot.py — Telegram gold bot (Render Free, polling + tiny HTTP server)

import os, re, time, sys, threading, http.server, socketserver, asyncio
from zoneinfo import ZoneInfo
import datetime
import urllib.parse
import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

def dprint(*a): print(*a, flush=True)

# ---------- ENV ----------
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
    dprint("FATAL: BOT_TOKEN empty"); time.sleep(10); sys.exit(1)
TELEGRAM_TOKEN = RAW_TOKEN

# ---------- Utils ----------
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

# ---------- Sources ----------
ALANCHAND_GOLD  = "https://alanchand.com/en/gold-price"
A
