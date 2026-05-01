#!/usr/bin/env python3
"""
OBSCURA VAULT — Smart Launcher
Cross-platform: Windows, Mac, Linux

Double-click this file OR run:  python start.py
"""

import sys
import os
import subprocess
import platform
import webbrowser
import time
from pathlib import Path

BASE_DIR  = Path(__file__).parent
SERVER_PY = BASE_DIR / "server.py"
REQ_FILE  = BASE_DIR / "requirements.txt"

REQUIRED = ["edge-tts", "moviepy", "requests", "Pillow", "flask"]

def cprint(msg, color="white"):
    colors = {"red":"\033[91m","green":"\033[92m","yellow":"\033[93m",
              "cyan":"\033[96m","white":"\033[97m","reset":"\033[0m"}
    print(f"{colors.get(color,'')}{msg}{colors['reset']}")

def check_python():
    if sys.version_info < (3, 9):
        cprint("ERROR: Python 3.9+ required. Current: " + platform.python_version(), "red")
        cprint("Download from: https://python.org/downloads", "yellow")
        input("Press Enter to exit...")
        sys.exit(1)
    cprint(f"✓ Python {platform.python_version()}", "green")

def check_ffmpeg():
    try:
        result = subprocess.run(["ffmpeg", "-version"],
                                capture_output=True, timeout=5)
        if result.returncode == 0:
            cprint("✓ FFmpeg found", "green")
            return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    cprint("✗ FFmpeg not found in PATH", "red")
    system = platform.system()
    if system == "Linux":
        cprint("  Install with: sudo apt install ffmpeg", "yellow")
    elif system == "Darwin":
        cprint("  Install with: brew install ffmpeg", "yellow")
    elif system == "Windows":
        cprint("  Download from: https://ffmpeg.org/download.html", "yellow")
        cprint("  Then add the /bin folder to your System PATH", "yellow")
    cprint("  FFmpeg is required. Please install it and try again.", "red")
    return False

def check_packages():
    missing = []
    for pkg in REQUIRED:
        try:
            __import__(pkg.replace("-", "_"))
        except ImportError:
            missing.append(pkg)

    if not missing:
        cprint("✓ All Python packages installed", "green")
        return True

    cprint(f"⚠ Missing packages: {', '.join(missing)}", "yellow")
    cprint("  Installing now...", "cyan")

    # Try different pip invocations for cross-platform compatibility
    pip_cmds = [
        [sys.executable, "-m", "pip", "install"] + missing,
        [sys.executable, "-m", "pip", "install", "--break-system-packages"] + missing,
        ["pip3", "install"] + missing,
        ["pip", "install"] + missing,
    ]

    for cmd in pip_cmds:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                cprint("✓ Packages installed successfully", "green")
                return True
        except Exception:
            continue

    cprint("✗ Auto-install failed. Run manually:", "red")
    cprint(f"  pip install {' '.join(missing)}", "yellow")
    return False

def main():
    os.chdir(BASE_DIR)

    print()
    print("=" * 55)
    cprint("  OBSCURA VAULT — Video Pipeline", "cyan")
    cprint("  History They Buried. We Dig It Up.", "yellow")
    print("=" * 55)
    print()
    cprint("Checking system requirements...", "white")
    print()

    check_python()
    ffmpeg_ok = check_ffmpeg()
    pkgs_ok   = check_packages()

    print()
    if not ffmpeg_ok:
        cprint("WARNING: FFmpeg missing — video assembly will fail.", "red")
        cprint("You can still start the app to configure settings.", "yellow")

    print()
    cprint("Starting Obscura Vault UI...", "cyan")
    cprint("URL: http://localhost:5050", "green")
    cprint("(Keep this window open while using the app)", "yellow")
    print()
    print("=" * 55)
    print()

    # Open browser after short delay
    def open_browser():
        time.sleep(2)
        webbrowser.open("http://localhost:5050")

    import threading
    threading.Thread(target=open_browser, daemon=True).start()

    # Start Flask server
    try:
        subprocess.run([sys.executable, str(SERVER_PY)], check=True)
    except KeyboardInterrupt:
        print()
        cprint("Server stopped. Goodbye!", "yellow")
    except subprocess.CalledProcessError as e:
        cprint(f"Server error: {e}", "red")
        input("Press Enter to exit...")

if __name__ == "__main__":
    main()
