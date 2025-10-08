# debug.py — env check + tiny HTTP server for Render Web Service
import os, time, sys, threading, http.server, socketserver

print("=== DEBUG START ===", flush=True)
bt = os.getenv("BOT_TOKEN", "")
bu = os.getenv("BASE_URL", "")
print("BOT_TOKEN present:", bool(bt), "len:", len(bt), flush=True)
print("BASE_URL:", bu if bu else "<EMPTY>", flush=True)
print("Python:", sys.version, flush=True)

# ---- tiny HTTP server to satisfy Render port binding
PORT = int(os.environ.get("PORT", "8080"))

class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # چاپ درخواست‌ها در لاگ
        sys.stdout.write("[HTTP] " + (fmt % args) + "\n")
        sys.stdout.flush()
    def do_GET(self):
        msg = "ok\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(msg)))
        self.end_headers()
        self.wfile.write(msg.encode("utf-8"))

def run_server():
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"HTTP server listening on 0.0.0.0:{PORT}", flush=True)
        httpd.serve_forever()

t = threading.Thread(target=run_server, daemon=True)
t.start()

print("Looping (prints dots every 10s)...", flush=True)
i = 0
while True:
    time.sleep(10)
    i += 1
    print("." * (i % 6 or 6), flush=True)
