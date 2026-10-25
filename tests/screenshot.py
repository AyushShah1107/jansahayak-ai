"""Boot Uvicorn in-process, screenshot the page with headless Chromium at desktop and mobile widths."""
import subprocess, sys, threading, time
from pathlib import Path
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
import main  # noqa

cfg = uvicorn.Config(main.app, host="127.0.0.1", port=8123, log_level="error")
server = uvicorn.Server(cfg)
th = threading.Thread(target=server.run, daemon=True)
th.start()
for _ in range(60):
    if server.started:
        break
    time.sleep(0.1)

def shot(path, size):
    subprocess.run([
        "chromium", "--headless=new", "--no-sandbox", "--disable-gpu",
        "--hide-scrollbars", f"--window-size={size}", f"--screenshot={path}",
        "--virtual-time-budget=4000", "http://127.0.0.1:8123/",
    ], check=False, capture_output=True)
    print("wrote", path)

shot("/scratch/work/ui_desktop.png", "1280,1100")
shot("/scratch/work/ui_mobile.png", "420,1400")
server.should_exit = True
th.join(timeout=5)
