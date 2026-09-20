from core.tz import now_kst

def log_activity(conn, user_id, action, module, target_id, doc_number, summary):
    conn.execute(
        """INSERT INTO erp_activity_log
           (user_id, action, module, target_id, doc_number, summary, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (user_id, action, module, target_id, doc_number or "", summary,
         now_kst().strftime("%Y-%m-%d %H:%M:%S")),
    )
