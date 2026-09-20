def create_notification(conn, user_id, title, message='', link=''):
    conn.execute(
        "INSERT INTO notifications (user_id, title, message, link) VALUES (?, ?, ?, ?)",
        (user_id, title, message, link),
    )
    conn.commit()


def create_bulk_notifications(conn, user_ids, title, message='', link=''):
    rows = [(uid, title, message, link) for uid in user_ids]
    conn.executemany(
        "INSERT INTO notifications (user_id, title, message, link) VALUES (?, ?, ?, ?)",
        rows,
    )
    conn.commit()


def get_unread_count(conn, user_id):
    row = conn.execute(
        "SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0",
        (user_id,),
    ).fetchone()
    return row[0]


def get_notifications(conn, user_id, limit=20, offset=0):
    return conn.execute(
        "SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (user_id, limit, offset),
    ).fetchall()


def mark_read(conn, notif_id, user_id):
    conn.execute(
        "UPDATE notifications SET is_read=1 WHERE id=? AND user_id=?",
        (notif_id, user_id),
    )
    conn.commit()


def mark_all_read(conn, user_id):
    conn.execute(
        "UPDATE notifications SET is_read=1 WHERE user_id=? AND is_read=0",
        (user_id,),
    )
    conn.commit()


def notify_all_staff(conn, title, message='', link=''):
    rows = conn.execute(
        "SELECT id FROM users WHERE role='platform_staff'"
    ).fetchall()
    user_ids = [r["id"] for r in rows]
    if user_ids:
        create_bulk_notifications(conn, user_ids, title, message, link)
