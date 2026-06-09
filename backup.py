"""Backup DB and config — run: python backup.py"""
import shutil, os
from datetime import datetime
from pathlib import Path

BACKUP_DIR = Path("backups")
DATA_DIR = Path("data")
BACKUP_DIR.mkdir(exist_ok=True)

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
db = DATA_DIR / "db.sqlite3"
if db.exists():
    shutil.copy2(db, BACKUP_DIR / f"db_{ts}.sqlite3")
    shutil.copy2(db, BACKUP_DIR / "db_latest.sqlite3")
    size = db.stat().st_size
    print(f"OK  db.sqlite3 ({size/1024:.0f}KB) -> backups/db_{ts}.sqlite3")
else:
    print("SKIP  db.sqlite3 not found")

if Path(".env").exists():
    shutil.copy2(".env", BACKUP_DIR / f"env_{ts}.backup")
    print("OK  .env backed up")

print(f"Done. Backups in {BACKUP_DIR}/")
