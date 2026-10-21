import json

from fastapi import HTTPException

from core.tz import now_kst
from core.rate_limit import get_client_ip


def log(conn, uid, action, target_type, target_id, summary, detail=None, company_id=None, ip=None):
    u = conn.execute("SELECT name, role FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    conn.execute(
        """INSERT INTO audit_logs (at, user_id, user_name, role, company_id, action, target_type, target_id,
               summary, detail, ip) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (now_kst().strftime("%Y-%m-%d %H:%M:%S"), uid, u["name"] if u else None, u["role"] if u else None,
         company_id, action, target_type, target_id, summary,
         json.dumps(detail, ensure_ascii=False) if detail else None, ip),
    )


# 폼 문자열과 DB 숫자 비교를 위해 문자열로 변환 후 비교
def diff(old, new):
    return {k: [old.get(k), v] for k, v in new.items()
            if k in old and str(old[k] if old[k] is not None else "") != str(v if v is not None else "")}


# 개인정보 포함 다운로드/인쇄는 사유 기록 필수
def require_reason(reason: str = ""):
    reason = reason.strip()
    if not reason or len(reason) > 200:
        raise HTTPException(status_code=400, detail="사유를 입력하세요.")
    return reason


def log_pii_export(conn, user, request, reason, doc_name, count, company_id=None, action="download"):
    log(conn, user["id"], action, "pii_export", None, doc_name,
        detail={"reason": reason, "count": count}, company_id=company_id, ip=get_client_ip(request))
    conn.commit()
