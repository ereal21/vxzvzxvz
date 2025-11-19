#!/usr/bin/env python
# run.py

import sys

# --- Force UTF-8 encoding for stdout/stderr so emojis and other Unicode work in logs ---
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import importlib
import subprocess

REQUIRED_MODULES = [
    "yoomoney",
    "aiogram",
    "sqlalchemy",
    "requests",
    "alembic",
    "solana",
    "xrpl",
    "web3",
    "bitcoinrpc",
    "flask",
]

def ensure_requirements() -> None:
    """Install required packages if any are missing."""
    missing = []
    for module in REQUIRED_MODULES:
        try:
            importlib.import_module(module)
        except Exception:
            missing.append(module)

    if missing:
        subprocess.check_call([
            sys.executable,
            "-m",
            "pip",
            "install",
            "-r",
            "requirements.txt",
        ])

from threading import Thread
from bot.main import start_bot
from bot.ipn_server import app as ipn_app

def run_ipn() -> None:
    ipn_app.run(host="0.0.0.0", port=5000)

if __name__ == '__main__':
    ensure_requirements()
    # Start the IPN (HTTP) server in a daemon thread
    Thread(target=run_ipn, daemon=True).start()
    # Then start the Telegram bot (blocking)
    start_bot()
