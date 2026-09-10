def up(conn):
    conn.execute(
        "ALTER TABLE attendance ADD COLUMN appeal_reject_reason TEXT DEFAULT ''"
    )
