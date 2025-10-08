
# --- همه‌ی import های فعلی‌ات بماند ---
import os, re, datetime, urllib.parse, time, sys, threading, http.server, socketserver
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

def dprint(*a): print(*a, flush=True)

RAW_TOKEN = os.getenv("BOT_TOKEN", "")
BASE_URL = (os.getenv("BASE_URL", "") or "").rstrip("/")

# اعداد فارسی به لاتین
def normalize_ascii_digits(s: str) -> str:
    tr = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩：", "01234567890123456789:")
    return s.translate(tr) if isinstance(s, str) else s

RAW_TOKEN = normalize_ascii_digits(RAW_TOKEN)
dprint("== DEBUG ==")
dprint("BOT_TOKEN present:", bool(RAW_TOKEN), "length:", len(RAW_TOKEN))
dprint("BASE_URL:", BASE_URL if BASE_URL else "<EMPTY>")

if not RAW_TOKEN:
    dprint("FATAL: Set BOT_TOKEN env var"); time.sleep(10); sys.exit(1)

TELEGRAM_TOKEN = RAW_TOKEN

# ---------- (بقیه‌ی توابع fetch_... و build_message و ...) همانی که داشتیم ----------

TRIGGERS = ("طلا","/gold","gold","قیمت طلا","gram18","mesghal","سکه","کهربا")

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

# ---- وب‌سرور خیلی کوچک برای Render (پورت‌بایند)
PORT = int(os.environ.get("PORT", "8080"))

class _Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stdout.write("[HTTP] " + (fmt % args) + "\n"); sys.stdout.flush()
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

if __name__ == "__main__":
    try:
        dprint("Starting tiny HTTP server + Telegram polling ...")
        _start_http_server()                 # پورت را باز نگه می‌داریم
        application = make_application()
        # به‌جای وب‌هوک از polling استفاده می‌کنیم (برای پلن رایگان ساده‌تر و پایدارتر است)
        application.run_polling(drop_pending_updates=True)
    except Exception as e:
        dprint("FATAL EXCEPTION:", repr(e))
        time.sleep(10); raise
