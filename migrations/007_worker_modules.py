def up(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            work_date TEXT,
            category TEXT,
            title TEXT NOT NULL,
            details TEXT,
            issues TEXT,
            dept TEXT DEFAULT '공통 업무',
            due_label TEXT DEFAULT '',
            status TEXT DEFAULT 'progress',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            sender TEXT NOT NULL,
            recipient TEXT DEFAULT '',
            body TEXT NOT NULL,
            time_label TEXT DEFAULT '',
            is_read INTEGER DEFAULT 0,
            direction TEXT DEFAULT 'in',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS approval_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id INTEGER NOT NULL,
            step INTEGER NOT NULL,
            approver_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            comment TEXT DEFAULT '',
            acted_at TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS doc_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            user_name TEXT NOT NULL DEFAULT '',
            action TEXT NOT NULL,
            comment TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS slip_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id INTEGER NOT NULL,
            line_no INTEGER NOT NULL,
            account_name TEXT NOT NULL,
            account_code TEXT DEFAULT '',
            debit INTEGER DEFAULT 0,
            credit INTEGER DEFAULT 0,
            partner TEXT DEFAULT '',
            summary TEXT DEFAULT ''
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            is_debit INTEGER DEFAULT 1,
            parent_code TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS partners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            biz_no TEXT DEFAULT '',
            representative TEXT DEFAULT '',
            biz_type TEXT DEFAULT '',
            biz_item TEXT DEFAULT '',
            address TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS trans_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            translator_name TEXT NOT NULL,
            service_type TEXT DEFAULT '',
            request_date TEXT DEFAULT '',
            request_time TEXT DEFAULT '',
            duration TEXT DEFAULT '',
            meeting_link TEXT DEFAULT '',
            details TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # erp_docs 컬럼 추가
    erp_docs_columns = [
        ("doc_number", "TEXT DEFAULT ''"),
        ("dept", "TEXT DEFAULT ''"),
        ("attachment", "TEXT DEFAULT ''"),
        ("visibility", "TEXT DEFAULT '공개'"),
        ("retention_period", "TEXT DEFAULT '3년'"),
        ("effective_date", "TEXT DEFAULT ''"),
        ("approved_by", "INTEGER"),
        ("approved_at", "TEXT"),
        ("reject_reason", "TEXT DEFAULT ''"),
        ("slip_type", "TEXT DEFAULT ''"),
        ("slip_date", "TEXT DEFAULT ''"),
        ("slip_total", "INTEGER DEFAULT 0"),
        ("extra_fields", "TEXT DEFAULT '{}'"),
        ("due_label", "TEXT DEFAULT ''"),
        ("doc_type_id", "INTEGER"),
    ]
    for col_name, col_def in erp_docs_columns:
        try:
            conn.execute(f"ALTER TABLE erp_docs ADD COLUMN {col_name} {col_def}")
        except Exception:
            pass

    # document_types 컬럼 추가
    doc_type_columns = [
        ("category", "TEXT DEFAULT '공통'"),
        ("form_schema", "TEXT DEFAULT '{}'"),
        ("doc_number_prefix", "TEXT DEFAULT 'DOC'"),
        ("is_active", "INTEGER DEFAULT 1"),
    ]
    for col_name, col_def in doc_type_columns:
        try:
            conn.execute(f"ALTER TABLE document_types ADD COLUMN {col_name} {col_def}")
        except Exception:
            pass

    # code → name 별칭 추가 (SQLite는 컬럼 이름 변경 안 됨)
    try:
        conn.execute("ALTER TABLE document_types ADD COLUMN name TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        conn.execute("UPDATE document_types SET name = code WHERE name = '' OR name IS NULL")
        conn.commit()
    except Exception:
        pass

    # users 컬럼 추가
    users_columns = [
        ("position", "TEXT DEFAULT ''"),
        ("phone", "TEXT DEFAULT ''"),
    ]
    for col_name, col_def in users_columns:
        try:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}")
        except Exception:
            pass

    conn.commit()
