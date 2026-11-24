import os
import re
import sqlite3
import sys

# 프로젝트 루트 경로 추가
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

# 테스트 암호화 키 설정
os.environ.setdefault("ERP_RNO_KEY", "dZtI0HrOpAJBsjNYmgRF54TVg1H59OgeI4LGWXaLpLg=")

from migrate import run_migrations

def map_column_type(col_name: str, col_type: str, is_pk: bool, is_auto: bool) -> str:
    col_name_lower = col_name.lower()
    col_type_upper = (col_type or "TEXT").upper().strip()

    if is_pk:
        if "INT" in col_type_upper:
            return "BIGINT AUTO_INCREMENT PRIMARY KEY"
        return f"{col_type_upper} PRIMARY KEY"

    if "INT" in col_type_upper:
        if col_name_lower.startswith("is_") or col_name_lower.endswith("_yn") or col_name_lower in ("sampled", "must_change_password"):
            return "TINYINT(1)"
        return "BIGINT" if "id" in col_name_lower else "INT"

    if "REAL" in col_type_upper or "FLOAT" in col_type_upper or "DOUBLE" in col_type_upper:
        return "DECIMAL(15, 2)"

    if "BLOB" in col_type_upper:
        return "LONGBLOB"

    # TEXT 컬럼 길이 및 타입 세분화
    if "TEXT" in col_type_upper or "VARCHAR" in col_type_upper or "CHAR" in col_type_upper or not col_type:
        if col_name_lower in ("id", "code", "account_code", "status", "role", "dept", "job_code"):
            return "VARCHAR(50)"
        if col_name_lower in ("username", "name", "email", "phone", "mobile", "tel", "resident_no"):
            return "VARCHAR(100)"
        if col_name_lower.endswith("_date") or col_name_lower == "pay_date":
            return "VARCHAR(20)"
        if col_name_lower in ("created_at", "updated_at", "acted_at", "applied_at", "locked_until", "login_at"):
            return "DATETIME"
        if any(keyword in col_name_lower for keyword in ("memo", "desc", "note", "content", "reason", "json", "lines", "settings", "body")):
            return "TEXT"
        return "VARCHAR(255)"

    return col_type_upper

def clean_default(col_type: str, d_val: str) -> str:
    if not d_val:
        return ""
    val = d_val.strip()
    col_type_upper = (col_type or "").upper()

    # datetime('now'), datetime('now','localtime') 등 -> DEFAULT CURRENT_TIMESTAMP
    if re.search(r"datetime\s*\(", val, re.I) or re.search(r"CURRENT_TIMESTAMP", val, re.I):
        return "DEFAULT CURRENT_TIMESTAMP"

    # date('now'), date('now','localtime') 등
    if re.search(r"date\s*\(", val, re.I) or re.search(r"CURRENT_DATE", val, re.I):
        if "DATE" in col_type_upper and "VARCHAR" not in col_type_upper:
            return "DEFAULT CURRENT_DATE"
        return ""

    # TEXT / BLOB 컬럼은 MariaDB/MySQL 버전 호환성을 위해 DEFAULT 절 제거
    if "TEXT" in col_type_upper or "BLOB" in col_type_upper:
        return ""

    return f"DEFAULT {val}"

def generate_mariadb_ddl(sqlite_db_path: str, output_sql_path: str):
    conn = sqlite3.connect(sqlite_db_path)
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
    tables = [r[0] for r in cur.fetchall()]

    lines = []
    lines.append("-- ============================================================================")
    lines.append("-- WONE ERP MariaDB DDL Schema")
    lines.append("-- Generated automatically from latest SQLite migrations (120 versions)")
    lines.append("-- Character Set: utf8mb4 / Collation: utf8mb4_unicode_ci")
    lines.append("-- ============================================================================\n")
    lines.append("SET FOREIGN_KEY_CHECKS = 0;\n")

    for tbl in tables:
        cur.execute(f"PRAGMA table_info('{tbl}')")
        cols = cur.fetchall()
        # cid, name, type, notnull, dflt_value, pk

        # 기본 키 개수 확인 (복합 PK인지 단일 PK인지)
        pk_cols = [c[1] for c in cols if c[5] > 0]
        is_composite_pk = len(pk_cols) > 1

        col_defs = []
        for cid, col_name, col_type, notnull, dflt_val, pk in cols:
            is_pk = (pk > 0) and not is_composite_pk
            mapped_type = map_column_type(col_name, col_type, is_pk=is_pk, is_auto=is_pk)

            not_null_str = "NOT NULL" if notnull else "NULL"
            dflt_str = clean_default(mapped_type, dflt_val)

            parts = [f"`{col_name}`", mapped_type]
            if not is_pk:
                if notnull:
                    parts.append("NOT NULL")
                if dflt_str:
                    parts.append(dflt_str)

            col_defs.append("    " + " ".join(parts))

        if is_composite_pk:
            col_defs.append(f"    PRIMARY KEY (`{'`, `'.join(pk_cols)}`)")

        lines.append(f"DROP TABLE IF EXISTS `{tbl}`;")
        lines.append(f"CREATE TABLE `{tbl}` (")
        lines.append(",\n".join(col_defs))
        lines.append(") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;\n")

    # 인덱스 추출
    cur.execute("SELECT name, tbl_name, sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL AND name NOT LIKE 'sqlite_%'")
    indices = cur.fetchall()
    if indices:
        lines.append("-- ----------------------------------------------------------------------------")
        lines.append("-- Indexes")
        lines.append("-- ----------------------------------------------------------------------------\n")
        for idx_name, tbl_name, sql in indices:
            # CREATE [UNIQUE] INDEX name ON tbl (col1, col2)
            m = re.search(r"CREATE\s+(UNIQUE\s+)?INDEX\s+(\w+)\s+ON\s+(\w+)\s*\((.*?)\)", sql, re.IGNORECASE)
            if m:
                uniq = "UNIQUE " if m.group(1) else ""
                iname = m.group(2)
                tname = m.group(3)
                cols_part = m.group(4)
                cols_formatted = ", ".join([f"`{c.strip()}`" for c in cols_part.split(",")])
                lines.append(f"CREATE {uniq}INDEX `{iname}` ON `{tname}` ({cols_formatted});")

    lines.append("\nSET FOREIGN_KEY_CHECKS = 1;")

    conn.close()

    full_sql = "\n".join(lines)
    with open(output_sql_path, "w", encoding="utf-8") as f:
        f.write(full_sql)

    print(f"MariaDB DDL Schema generated successfully: {output_sql_path}")
    print(f"Total tables converted: {len(tables)}")

if __name__ == "__main__":
    temp_sqlite = os.path.join(ROOT_DIR, "temp_for_schema.db")
    if os.path.exists(temp_sqlite):
        os.remove(temp_sqlite)

    print("Running 120 migrations on temporary SQLite DB...")
    run_migrations(temp_sqlite)

    schema_sql_path = os.path.join(ROOT_DIR, "schema_mariadb.sql")
    generate_mariadb_ddl(temp_sqlite, schema_sql_path)

    if os.path.exists(temp_sqlite):
        os.remove(temp_sqlite)
