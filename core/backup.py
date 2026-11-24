import glob
import os
import re
import shutil
import sqlite3
import subprocess
from datetime import datetime

from core.tz import KST, now_kst

def _dump_mariadb_python(dest_path):
    """외부 도구(mysqldump) 없이 PyMySQL만으로 모든 테이블 DDL 및 데이터를 .sql로 덤프"""
    import pymysql
    from core.db import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME

    conn = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
    )
    with conn.cursor() as cur, open(dest_path, "w", encoding="utf-8") as f:
        f.write("-- ====================================================================\n")
        f.write(f"-- WONE ERP MariaDB Backup Dump\n")
        f.write(f"-- Dump Date: {now_kst().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"-- Database: {DB_NAME}\n")
        f.write("-- ====================================================================\n\n")
        f.write("SET FOREIGN_KEY_CHECKS = 0;\n\n")

        cur.execute("SHOW TABLES")
        tables = [r[0] for r in cur.fetchall()]

        for tbl in tables:
            # CREATE TABLE DDL 덤프
            cur.execute(f"SHOW CREATE TABLE `{tbl}`")
            create_sql = cur.fetchone()[1]
            f.write(f"DROP TABLE IF EXISTS `{tbl}`;\n")
            f.write(f"{create_sql};\n\n")

            # 데이터 덤프
            cur.execute(f"SELECT * FROM `{tbl}`")
            rows = cur.fetchall()
            if not rows:
                continue

            cur.execute(f"DESCRIBE `{tbl}`")
            cols = [f"`{r[0]}`" for r in cur.fetchall()]
            cols_str = ", ".join(cols)

            batch_size = 200
            for i in range(0, len(rows), batch_size):
                batch = rows[i:i + batch_size]
                values_parts = []
                for row in batch:
                    formatted_vals = []
                    for val in row:
                        if val is None:
                            formatted_vals.append("NULL")
                        elif isinstance(val, (int, float)):
                            formatted_vals.append(str(val))
                        elif isinstance(val, bool):
                            formatted_vals.append("1" if val else "0")
                        else:
                            val_str = str(val).replace("\\", "\\\\").replace("'", "\\'")
                            formatted_vals.append(f"'{val_str}'")
                    values_parts.append(f"({', '.join(formatted_vals)})")
                f.write(f"INSERT INTO `{tbl}` ({cols_str}) VALUES\n  " + ",\n  ".join(values_parts) + ";\n\n")

        f.write("SET FOREIGN_KEY_CHECKS = 1;\n")
    conn.close()


def _run_mariadb_backup(dest_dir):
    from core.db import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME

    name = now_kst().strftime("erp-%Y%m%d-%H%M")
    path = os.path.join(dest_dir, f"{name}.sql")
    if os.path.exists(path):
        path = os.path.join(dest_dir, f"{name}-{now_kst().strftime('%S')}.sql")

    # 1. mariadb-dump 또는 mysqldump 바이너리 시도
    dump_bin = shutil.which("mariadb-dump") or shutil.which("mysqldump")
    if dump_bin:
        cmd = [
            dump_bin,
            f"-h{DB_HOST}",
            f"-P{DB_PORT}",
            f"-u{DB_USER}",
            f"--default-character-set=utf8mb4",
            "--single-transaction",
            "--routines",
            "--triggers",
            DB_NAME,
        ]
        env = os.environ.copy()
        if DB_PASSWORD:
            env["MYSQL_PWD"] = DB_PASSWORD
        try:
            with open(path, "w", encoding="utf-8") as f:
                res = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, env=env, check=True)
            return path
        except Exception:
            pass  # 실패 시 파이썬 내부 덤퍼로 fallback

    # 2. 파이썬 내장 덤퍼 실행
    _dump_mariadb_python(path)
    return path


def run(db_path, dest_dir, keep_days=14):
    os.makedirs(dest_dir, exist_ok=True)
    engine = os.getenv("DB_ENGINE", "sqlite").lower()

    if engine in ("mariadb", "mysql"):
        path = _run_mariadb_backup(dest_dir)
    else:
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

    # 보존 기간 지난 파일 정리 (db, sql, sql.gz)
    cutoff = now_kst().timestamp() - keep_days * 86400
    for pattern in ("erp-*.db", "erp-*.sql", "erp-*.sql.gz"):
        for f in glob.glob(os.path.join(dest_dir, pattern)):
            if os.path.getmtime(f) < cutoff:
                try:
                    os.remove(f)
                except Exception:
                    pass

    return path


def files(dest_dir):
    rows = []
    for pattern in ("erp-*.db", "erp-*.sql", "erp-*.sql.gz"):
        for f in glob.glob(os.path.join(dest_dir, pattern)):
            st = os.stat(f)
            rows.append({
                "name": os.path.basename(f),
                "size": st.st_size,
                "at": datetime.fromtimestamp(st.st_mtime, KST).strftime("%Y-%m-%d %H:%M:%S"),
            })
    rows.sort(key=lambda r: r["name"], reverse=True)
    return rows
