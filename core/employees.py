from core.crypto import enc_rno


def _vals(f):
    return {
        "name": f["name"], "employee_no": f["employee_no"] or None, "dept": f["dept"],
        "position": f["position"], "hire_date": f["hire_date"], "status": f["status"],
        "gender": f["gender"], "birth_date": f["birth_date"], "phone": f["phone"],
        "email": f["email"], "address": f["address"],
        "disability_type": f["disability_type"], "disability_grade": f["disability_grade"],
        "emergency_contact": f["emergency_contact"], "emergency_phone": f["emergency_phone"],
        "notes": f["notes"], "job_title": f["job_title"], "job_code": f["job_code"] or None,
        "renew_date": f["renew_date"], "contract_end": f["contract_end"], "career": f["career"],
        "education": f["education"], "military": f["military"], "license": f["license"],
        "training": f["training"], "disability_class": f["disability_class"],
        "veteran_grade": f["veteran_grade"], "disability_date": f["disability_date"],
    }


def add(conn, f):
    v = _vals(f) | {"company_id": f["company_id"], "resident_no": enc_rno(f["resident_no"]),
                    "disability_cert_file": f["cert_path"]}
    cur = conn.execute(
        f"INSERT INTO employees ({', '.join(v)}) VALUES ({','.join('?' * len(v))})", list(v.values()))
    return cur.lastrowid


# company 지정 시 해당 고객사 직원만 수정, 미지정(스태프) 시 소속 고객사 변경 허용
def update(conn, emp_id, f, company=None):
    v = _vals(f)
    if company is None:
        v["company_id"] = f["company_id"]
    if f["cert_path"]:
        v["disability_cert_file"] = f["cert_path"]
    sets = dict(v)
    if f["resident_no"].strip():
        sets["resident_no"] = enc_rno(f["resident_no"])
    sql = f"UPDATE employees SET {', '.join(k + '=?' for k in sets)}, updated_at=datetime('now','localtime') WHERE id=?"
    args = [*sets.values(), emp_id]
    if company is not None:
        sql += " AND company_id=?"
        args.append(company)
    conn.execute(sql, args)
    return v
