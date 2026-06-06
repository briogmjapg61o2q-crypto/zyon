import numpy as np
import sounddevice as sd
import subprocess
import time
import sys
from pathlib import Path

# ── Config ──────────────────────────────────────────────
ZYON_PATH      = Path(__file__).parent / "main.py"  # ✅ একই ফোল্ডারে আছে
CLAP_THRESHOLD = 0.6       # sensitivity (0.3 = বেশি sensitive, 0.9 = কম)
CLAP_COUNT     = 2         # কতটা clap লাগবে
CLAP_WINDOW    = 1.5       # কত সেকেন্ডের মধ্যে clap দিতে হবে
COOLDOWN       = 5         # ZYON launch হওয়ার পর কত সেকেন্ড wait
SAMPLE_RATE    = 44100
BLOCK_SIZE     = 1024
# ────────────────────────────────────────────────────────

clap_times    = []
zyon_process  = None
last_launch   = 0

def is_clap(indata):
    volume = np.max(np.abs(indata))
    return volume > CLAP_THRESHOLD

def launch_zyon():
    global zyon_process, last_launch
    now = time.time()
    if now - last_launch < COOLDOWN:
        return
    if zyon_process and zyon_process.poll() is None:
        print("[ZYON] Already running.")
        return
    if not ZYON_PATH.exists():
        print(f"[ZYON] ❌ main.py পাওয়া যাচ্ছে না: {ZYON_PATH}")
        return
    print("[ZYON] 👋 Clap detected! Launching ZYON...")
    zyon_process = subprocess.Popen([sys.executable, str(ZYON_PATH)])
    last_launch  = now

def audio_callback(indata, frames, time_info, status):
    global clap_times
    if is_clap(indata):
        now = time.time()
        clap_times.append(now)
        clap_times = [t for t in clap_times if now - t <= CLAP_WINDOW]
        if len(clap_times) >= CLAP_COUNT:
            clap_times.clear()
            launch_zyon()

print("=" * 40)
print("  ZYON Clap Launcher — Active")
print(f"  👏 {CLAP_COUNT} claps = ZYON launches")
print(f"  📁 Path: {ZYON_PATH}")
print("  Press Ctrl+C to stop")
print("=" * 40)

# Startup এ path check
if not ZYON_PATH.exists():
    print(f"\n⚠️  সতর্কতা: main.py পাওয়া যাচ্ছে না!")
    print(f"   খুঁজছে: {ZYON_PATH}")
    print(f"   নিশ্চিত করুন ZYON ফোল্ডারটি একই জায়গায় আছে।\n")

with sd.InputStream(callback=audio_callback,
                    channels=1,
                    samplerate=SAMPLE_RATE,
                    blocksize=BLOCK_SIZE):
    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n[ZYON] Clap Launcher stopped.")
