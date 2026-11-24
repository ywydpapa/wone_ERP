from core.tz import now_kst
from core.constants import COMPANY_INFO

# 담당자 발급, 인쇄 대상. 그 외 종류는 즉시 발급 유지
CERT_PRINTABLE_TYPES = ("재직증명서", "경력증명서")


def cert_context(conn, cert_id):
    row = conn.execute(
        "SELECT cr.*, e.name AS emp_name, e.employee_no, e.dept, e.position, "
        "e.hire_date, e.resign_date, e.company_id "
        "FROM certificate_requests cr JOIN employees e ON e.id = cr.employee_id "
        "WHERE cr.id=?", (cert_id,),
    ).fetchone()
    if not row or row["cert_type"] not in CERT_PRINTABLE_TYPES:
        return None
    cert = dict(row)
    if cert["company_id"]:
        co = conn.execute(
            "SELECT name, business_no, representative FROM client_companies WHERE id=?",
            (cert["company_id"],),
        ).fetchone()
        company = dict(co) if co else {}
    else:
        company = {
            "name": COMPANY_INFO["name"], "business_no": COMPANY_INFO["biz_no"],
            "representative": COMPANY_INFO["representative"],
        }
    cert["company"] = company
    cert["period"] = f"{cert['hire_date'] or '-'} ~ {cert['resign_date'] or '현재'}"
    return cert


def issue_cert(conn, cert_id, issued_by):
    now = now_kst()
    cert_number = f"CERT-{now.strftime('%Y%m%d')}-{cert_id:04d}"
    conn.execute(
        "UPDATE certificate_requests SET status='completed', cert_number=?, "
        "completed_at=datetime('now','localtime'), issued_by=? WHERE id=? AND status='pending'",
        (cert_number, issued_by, cert_id),
    )
    conn.commit()
