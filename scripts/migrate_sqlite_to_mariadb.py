import os
import sqlite3
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from dotenv import load_dotenv
load_dotenv()

from migrate_mariadb import get_raw_connection

def migrate_data():
    sqlite_path = os.path.join(ROOT_DIR, "erp.db")
    if not os.path.exists(sqlite_path):
        print(f"SQLite database not found: {sqlite_path}. Nothing to migrate.")
        return

    s_conn = sqlite3.connect(sqlite_path)
    s_conn.row_factory = sqlite3.Row
    s_cur = s_conn.cursor()

    m_conn = get_raw_connection()
    m_cur = m_conn.cursor()

    s_cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != 'schema_versions' ORDER BY name")
    tables = [r[0] for r in s_cur.fetchall()]

    print(f"Starting data migration for {len(tables)} tables from SQLite to MariaDB...")

    m_cur.execute("SET FOREIGN_KEY_CHECKS = 0;")

    for tbl in tables:
        s_cur.execute(f"PRAGMA table_info('{tbl}')")
        cols = [r["name"] for r in s_cur.fetchall()]
        if not cols:
            continue

        s_cur.execute(f"SELECT COUNT(*) FROM `{tbl}`")
        count = s_cur.fetchone()[0]
        if count == 0:
            continue

        cols_str = ", ".join([f"`{c}`" for c in cols])
        placeholders = ", ".join(["%s"] * len(cols))
        insert_sql = f"INSERT INTO `{tbl}` ({cols_str}) VALUES ({placeholders})"

        print(f"  Migrating {tbl} ({count} rows)...")

        batch_size = 500
        offset = 0
        while offset < count:
            s_cur.execute(f"SELECT * FROM `{tbl}` LIMIT ? OFFSET ?", (batch_size, offset))
            rows = [tuple(r[c] for c in cols) for r in s_cur.fetchall()]
            if not rows:
                break
            m_cur.executemany(insert_sql, rows)
            offset += len(rows)

    # schema_versions 이전
    s_cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_versions'")
    if s_cur.fetchone():
        s_cur.execute("SELECT * FROM schema_versions")
        versions = s_cur.fetchall()
        for v in versions:
            m_cur.execute("INSERT IGNORE INTO schema_versions (version, applied_at) VALUES (%s, %s)",
                          (v["version"], v["applied_at"]))

    m_cur.execute("SET FOREIGN_KEY_CHECKS = 1;")
    m_conn.commit()

    s_conn.close()
    m_conn.close()
    print("All data migrated successfully from SQLite to MariaDB!")

if __name__ == "__main__":
    migrate_data()
