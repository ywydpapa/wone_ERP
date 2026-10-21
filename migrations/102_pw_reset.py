# 담당자 신규 발급 계정의 임시 비번 강제 변경용


def up(conn):
    conn.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0")
