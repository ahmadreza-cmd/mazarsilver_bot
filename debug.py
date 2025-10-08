# debug.py — keep-alive + env check
import os, time, sys
print("=== DEBUG START ===", flush=True)
bt = os.getenv("BOT_TOKEN", "")
bu = os.getenv("BASE_URL", "")
print("BOT_TOKEN present:", bool(bt), "len:", len(bt), flush=True)
print("BASE_URL:", bu if bu else "<EMPTY>", flush=True)
print("Python:", sys.version, flush=True)
print("Looping (will print a dot every 10s)...", flush=True)
i = 0
while True:
    time.sleep(10)
    i += 1
    print("." * (i % 6 or 6), flush=True)
