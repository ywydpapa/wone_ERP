# 가지급금 인정이자. 가지급금(134), 가수금(258) 계정 추가


def up(conn):
    new_accounts = [
        ("134", "가지급금", "자산", 1),
        ("258", "가수금", "부채", 0),
    ]
    conn.executemany(
        "INSERT INTO accounts (company_id, code, name, category, is_debit, req_partner) VALUES (0,?,?,?,?,1)",
        new_accounts,
    )

    companies = [r["id"] for r in conn.execute("SELECT id FROM client_companies")]
    for cid in companies:
        conn.executemany(
            "INSERT OR IGNORE INTO accounts (company_id, code, name, category, is_debit, req_partner) VALUES (?,?,?,?,?,1)",
            [(cid, code, name, cat, is_debit) for code, name, cat, is_debit in new_accounts],
        )

    conn.commit()
