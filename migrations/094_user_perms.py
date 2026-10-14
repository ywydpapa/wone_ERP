# 사용자별 메뉴 그룹 권한. 역할 기본값보다 낮추는 용도만. 행 없으면 역할 기본 동작


def up(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS user_perms (
            user_id INTEGER NOT NULL REFERENCES users(id),
            group_key TEXT NOT NULL,
            level TEXT NOT NULL CHECK(level IN ('none','view','edit')),
            PRIMARY KEY (user_id, group_key)
        );
    """)
