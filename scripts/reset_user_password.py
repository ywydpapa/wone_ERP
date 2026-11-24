import os
import sys

# 프로젝트 루트 경로 추가
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from dotenv import load_dotenv
load_dotenv()

from core.auth import hash_pw
from core.db import get_connection

def reset_password(username: str, new_password: str):
    if not username or not new_password:
        print("사용법: python scripts/reset_user_password.py <아이디> <새_비밀번호>")
        return

    # PBKDF2-HMAC-SHA256 해시 생성 (600,000회 반복)
    hashed = hash_pw(new_password)

    conn = get_connection()
    try:
        cur = conn.execute("SELECT id, username, name, role FROM users WHERE username=?", (username,))
        user = cur.fetchone()

        if not user:
            print(f"[오류] 사용자 '{username}'을(를) 찾을 수 없습니다.")
            return

        conn.execute(
            """UPDATE users 
               SET password = ?, 
                   must_change_password = 0, 
                   locked_until = NULL, 
                   sess_ver = sess_ver + 1 
               WHERE id = ?""",
            (hashed, user["id"]),
        )
        conn.commit()
        print(f"[성공] 사용자 '{username}' ({user['name']}, {user['role']})의 비밀번호가 성공적으로 변경되었습니다.")
        print("  - 기존 로그인 세션이 모두 무효화(강제 로그아웃)되었습니다.")
        print("  - 계정 잠금(Locked)이 해제되었습니다.")
    finally:
        conn.close()

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("사용법: python scripts/reset_user_password.py <아이디> <새_비밀번호>")
        sys.exit(1)

    username_arg = sys.argv[1]
    new_pw_arg = sys.argv[2]
    reset_password(username_arg, new_pw_arg)
