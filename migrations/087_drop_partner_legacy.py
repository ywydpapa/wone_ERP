# 086 이후 구 화면에서 입력된 계좌, 계산서 담당자 재동기화 후 구 컬럼 삭제
# 계좌가 하나도 없는 거래처, 역할 미지정 담당자만 대상. 신 화면에서 지운 값 부활 방지


def up(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(partners)")}
    if "bank_account" in cols:
        conn.execute("""
            INSERT INTO partner_banks (company_id, partner_id, bank, account_no, holder, is_default)
            SELECT company_id, id, COALESCE(bank_name, ''), bank_account, COALESCE(bank_holder, ''), 1
            FROM partners
            WHERE COALESCE(bank_account, '') != '' AND id NOT IN (SELECT partner_id FROM partner_banks)
        """)
        for c in ("bank_name", "bank_account", "bank_holder"):
            conn.execute(f"ALTER TABLE partners DROP COLUMN {c}")

    cols = {r[1] for r in conn.execute("PRAGMA table_info(partner_contacts)")}
    if "is_invoice" in cols:
        conn.execute("UPDATE partner_contacts SET roles='tax' WHERE is_invoice=1 AND roles=''")
        conn.execute("ALTER TABLE partner_contacts DROP COLUMN is_invoice")
