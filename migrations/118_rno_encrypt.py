# 개인정보 보호법 제24조의2. 평문(enc: 없는 값)만 암호화, 재실행해도 안전
from core.crypto import enc_rno, ENC_PREFIX


def up(conn):
    rows = conn.execute(
        "SELECT id, resident_no FROM employees WHERE resident_no IS NOT NULL AND resident_no != ''"
    ).fetchall()
    for r in rows:
        rno = r[1]
        if rno.startswith(ENC_PREFIX):
            continue
        conn.execute("UPDATE employees SET resident_no=? WHERE id=?", (enc_rno(rno), r[0]))
    conn.commit()
