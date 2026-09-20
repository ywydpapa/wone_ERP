def up(conn):
    # work_requests 컬럼 추가
    for col_name, col_def in [
        ("submitted_at",       "TEXT"),
        ("accepted_at",        "TEXT"),
        ("completed_at",       "TEXT"),
        ("closed_at",          "TEXT"),
        ("reject_reason",      "TEXT DEFAULT ''"),
        ("total_volume",       "INTEGER DEFAULT 0"),
        ("completed_volume",   "INTEGER DEFAULT 0"),
    ]:
        try:
            conn.execute(f"ALTER TABLE work_requests ADD COLUMN {col_name} {col_def}")
        except Exception:
            pass

    # tasks 컬럼 추가
    for col_name, col_def in [
        ("requested_volume",   "INTEGER DEFAULT 0"),
        ("completed_volume",   "INTEGER DEFAULT 0"),
        ("sort_order",         "INTEGER DEFAULT 0"),
    ]:
        try:
            conn.execute(f"ALTER TABLE tasks ADD COLUMN {col_name} {col_def}")
        except Exception:
            pass

    # 업무 요청 첨부파일
    conn.execute("""
        CREATE TABLE IF NOT EXISTS work_request_attachments (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id  INTEGER NOT NULL REFERENCES work_requests(id),
            user_id     INTEGER NOT NULL REFERENCES users(id),
            file_name   TEXT DEFAULT '',
            file_path   TEXT DEFAULT '',
            created_at  TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # 활동 로그
    conn.execute("""
        CREATE TABLE IF NOT EXISTS activity_logs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            target_type TEXT NOT NULL,
            target_id   INTEGER NOT NULL,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            action      TEXT NOT NULL,
            detail      TEXT DEFAULT '',
            created_at  TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_activity_target
        ON activity_logs(target_type, target_id)
    """)

    # 알림
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            title       TEXT NOT NULL,
            message     TEXT DEFAULT '',
            link        TEXT DEFAULT '',
            is_read     INTEGER DEFAULT 0,
            created_at  TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_notif_user
        ON notifications(user_id, is_read)
    """)

    # CHECK 제약 변경 (SQLite는 ALTER CHECK 불가 -> 테이블 재생성)
    # 이전 실패 시 잔존 테이블 정리
    conn.execute("DROP TABLE IF EXISTS _wr_old")
    cols = [r[1] for r in conn.execute("PRAGMA table_info(work_requests)").fetchall()]
    if 'status' in cols:
        col_list = ", ".join(cols)
        conn.execute("ALTER TABLE work_requests RENAME TO _wr_old")
        # 기존 DDL에서 CHECK만 교체
        old_ddl = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='_wr_old'"
        ).fetchone()[0]
        new_ddl = old_ddl.replace("_wr_old", "work_requests")
        old_check = "status IN ('pending','accepted','in_progress','completed','cancelled')"
        new_check = "status IN ('draft','submitted','review','accepted','rejected','in_progress','completed','closed','cancelled')"
        if old_check in new_ddl:
            new_ddl = new_ddl.replace(old_check, new_check)
        else:
            new_ddl = new_ddl.replace("_wr_old", "work_requests")
        conn.execute(new_ddl)
        conn.execute(f"INSERT INTO work_requests ({col_list}) SELECT {col_list} FROM _wr_old")
        conn.execute("DROP TABLE _wr_old")
        conn.execute("UPDATE work_requests SET status='submitted' WHERE status='pending'")

    conn.commit()
