# 로그인 화면 테스트 계정용 한양정밀 담당자. seed_sample.py 전용이므로 기존 운영 DB에 미존재
from core.auth import hash_pw


def up(conn):
    co = conn.execute("SELECT id, contact_name FROM client_companies WHERE name='한양정밀'").fetchone()
    if not co:
        return
    row = conn.execute("SELECT id FROM users WHERE username='hanyang_mgr'").fetchone()
    if row:
        uid = row[0]
        conn.execute("UPDATE users SET name='김주형' WHERE id=?", (uid,))
    else:
        uid = conn.execute(
            "INSERT INTO users (username, password, name, dept, role) VALUES ('hanyang_mgr', ?, '김주형', '한양정밀', 'client')",
            (hash_pw("1234"),),
        ).lastrowid
    if not conn.execute("SELECT 1 FROM client_users WHERE user_id=? AND company_id=?", (uid, co[0])).fetchone():
        conn.execute("INSERT INTO client_users (user_id, company_id, client_role) VALUES (?, ?, 'all')", (uid, co[0]))
    # 시드 기본값일 때만 교체. 운영 중 입력값 보존
    if co[1] == '김대표':
        conn.execute("UPDATE client_companies SET contact_name='김주형' WHERE id=?", (co[0],))
    conn.commit()
