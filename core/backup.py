import glob
import os
import sqlite3
from datetime import datetime

from core.tz import KST, now_kst


def run(db_path, dest_dir, keep_days=14):
    os.makedirs(dest_dir, exist_ok=True)
    name = now_kst().strftime("erp-%Y%m%d-%H%M")
    path = os.path.join(dest_dir, f"{name}.db")
    if os.path.exists(path):
        path = os.path.join(dest_dir, f"{name}-{now_kst().strftime('%S')}.db")

    src = sqlite3.connect(db_path)
    try:
        dst = sqlite3.connect(path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    cutoff = now_kst().timestamp() - keep_days * 86400
    for f in glob.glob(os.path.join(dest_dir, "erp-*.db")):
        if os.path.getmtime(f) < cutoff:
            os.remove(f)

    return path


def files(dest_dir):
    rows = []
    for f in glob.glob(os.path.join(dest_dir, "erp-*.db")):
        st = os.stat(f)
        rows.append({
            "name": os.path.basename(f),
            "size": st.st_size,
            "at": datetime.fromtimestamp(st.st_mtime, KST).strftime("%Y-%m-%d %H:%M:%S"),
        })
    rows.sort(key=lambda r: r["name"], reverse=True)
    return rows
