# 결재 대결, 구매요청 결재 엔진 이관, 초과근무신청서 양식 항목 추가
import json


def up(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS approval_deputies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL REFERENCES users(id),
            deputy_id INTEGER NOT NULL REFERENCES users(id),
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_approval_deputies_user ON approval_deputies(company_id, user_id, start_date, end_date);
    """)
    conn.execute("ALTER TABLE approval_lines ADD COLUMN acted_by INTEGER REFERENCES users(id)")
    conn.execute("ALTER TABLE purchase_requisitions ADD COLUMN doc_id INTEGER REFERENCES erp_docs(id)")

    # 초과근무신청서는 기존 그룹웨어 공용 양식에 근무일자/초과근무시간 항목 부재. 최종승인 시 근태 반영에 필요하므로 추가
    overtime_schema = json.dumps({"fields": [
        {"name": "work_date", "label": "근무일자", "type": "date", "required": True},
        {"name": "ot_minutes", "label": "초과근무(분)", "type": "number", "required": True, "placeholder": "예: 120"},
    ]}, ensure_ascii=False)
    conn.execute("UPDATE document_types SET form_schema=? WHERE name='overtime'", (overtime_schema,))

    # 결재대기 중 결재문서 없는 구매요청은 통합 전 자체 컬럼 처리분. 임시저장으로 되돌려 재요청
    conn.execute(
        "UPDATE purchase_requisitions SET status='draft' WHERE status='submitted' AND doc_id IS NULL"
    )
