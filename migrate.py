import importlib.util
import os
import re
import sqlite3


MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations")


def _load_module(path):
    spec = importlib.util.spec_from_file_location("_migration", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_migrations(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_versions (
            version    INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.commit()

    applied = {row["version"] for row in conn.execute("SELECT version FROM schema_versions")}

    pattern = re.compile(r"^(\d{3})_.*\.py$")
    files = sorted(
        f for f in os.listdir(MIGRATIONS_DIR) if pattern.match(f)
    )

    for filename in files:
        version = int(pattern.match(filename).group(1))
        if version in applied:
            continue

        filepath = os.path.join(MIGRATIONS_DIR, filename)
        mod = _load_module(filepath)
        mod.up(conn)
        conn.execute(
            "INSERT INTO schema_versions (version) VALUES (?)", (version,)
        )
        conn.commit()
        print(f"  Applied migration {filename}")

    conn.close()
