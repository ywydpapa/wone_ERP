from datetime import date, datetime

from fastapi import HTTPException

REQUEST_TRANSITIONS = {
    ('draft',       'submit'):     'submitted',
    ('submitted',   'review'):     'review',
    ('review',      'accept'):     'accepted',
    ('review',      'reject'):     'rejected',
    ('rejected',    'resubmit'):   'submitted',
    ('accepted',    'start'):      'in_progress',
    ('in_progress', 'complete'):   'completed',
    ('completed',   'close'):      'closed',
    ('draft',       'cancel'):     'cancelled',
    ('submitted',   'cancel'):     'cancelled',
}

REQUEST_ROLE_ACTIONS = {
    'client': {'submit', 'resubmit', 'cancel', 'close'},
}

TASK_TRANSITIONS = {
    ('pending',     'assign'):    'assigned',
    ('assigned',    'start'):     'in_progress',
    ('assigned',    'unassign'):  'pending',
    ('in_progress', 'submit'):    'review',
    ('review',      'approve'):   'completed',
    ('review',      'reject'):    'returned',
    ('returned',    'resubmit'):  'review',
    ('pending',     'cancel'):    'cancelled',
    ('assigned',    'cancel'):    'cancelled',
}

TASK_ROLE_ACTIONS = {
    'worker': {'start', 'submit', 'resubmit'},
    'client': {'approve', 'reject', 'cancel'},
}

_REQUEST_TS = {
    'submitted':  'submitted_at',
    'accepted':   'accepted_at',
    'rejected':   'rejected_at',
    'completed':  'completed_at',
    'closed':     'closed_at',
}

_TASK_TS = {
    'in_progress': 'started_at',
    'completed':   'completed_at',
}


def transition_request(conn, req_id, action, user_id, role, detail=''):
    allowed = REQUEST_ROLE_ACTIONS.get(role, set())
    if action not in allowed:
        raise HTTPException(status_code=403, detail="권한 없는 액션")

    row = conn.execute(
        "SELECT status FROM work_requests WHERE id=?", (req_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="요청 없음")

    old = row['status']
    new = REQUEST_TRANSITIONS.get((old, action))
    if not new:
        raise HTTPException(status_code=400, detail=f"'{old}' 상태에서 '{action}' 불가")

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    sets = ['status=?', 'updated_at=?']
    params = [new, now]

    ts_col = _REQUEST_TS.get(new)
    if ts_col:
        sets.append(f'{ts_col}=?')
        params.append(now)

    if action == 'reject':
        sets.append('reject_reason=?')
        params.append(detail)

    params.append(req_id)
    conn.execute(f"UPDATE work_requests SET {', '.join(sets)} WHERE id=?", params)

    _log_activity(conn, 'work_request', req_id, user_id, 'status_changed', f'{old} -> {new}')
    _notify_on_request_change(conn, req_id, action, user_id)
    conn.commit()

    return new


# 담당자 직접 지시 흐름의 자동 전진. staff 검토 단계를 대체한다
_AUTO_FORWARD = {
    'in_progress': ('submitted', 'accepted'),
    'completed':   ('in_progress',),
}


def advance_request(conn, req_id, new, user_id):
    row = conn.execute(
        "SELECT status FROM work_requests WHERE id=?", (req_id,)
    ).fetchone()
    if not row or row['status'] not in _AUTO_FORWARD.get(new, ()):
        return
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    sets = ['status=?', 'updated_at=?']
    params = [new, now]
    ts_col = _REQUEST_TS.get(new)
    if ts_col:
        sets.append(f'{ts_col}=?')
        params.append(now)
    params.append(req_id)
    conn.execute(f"UPDATE work_requests SET {', '.join(sets)} WHERE id=?", params)
    _log_activity(conn, 'work_request', req_id, user_id, 'status_changed', f"{row['status']} -> {new}")


def transition_task(conn, task_id, action, user_id, role, detail=''):
    allowed = TASK_ROLE_ACTIONS.get(role, set())
    if action not in allowed:
        raise HTTPException(status_code=403, detail="권한 없는 액션")

    row = conn.execute(
        "SELECT status FROM tasks WHERE id=?", (task_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="태스크 없음")

    old = row['status']
    new = TASK_TRANSITIONS.get((old, action))
    if not new:
        raise HTTPException(status_code=400, detail=f"'{old}' 상태에서 '{action}' 불가")

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    sets = ['status=?', 'updated_at=?']
    params = [new, now]

    ts_col = _TASK_TS.get(new)
    if ts_col:
        sets.append(f'{ts_col}=?')
        params.append(now)

    params.append(task_id)
    conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id=?", params)

    _log_activity(conn, 'task', task_id, user_id, 'status_changed', f'{old} -> {new}')
    _notify_on_task_change(conn, task_id, action, user_id)
    conn.commit()

    return new


def _log_activity(conn, target_type, target_id, user_id, action, detail):
    conn.execute(
        "INSERT INTO activity_logs (target_type, target_id, user_id, action, detail) "
        "VALUES (?, ?, ?, ?, ?)",
        (target_type, target_id, user_id, action, detail),
    )


def log_activity(conn, target_type, target_id, user_id, action, detail=''):
    _log_activity(conn, target_type, target_id, user_id, action, detail)
    conn.commit()


def _notify_on_request_change(conn, req_id, action, user_id):
    from core.notification import create_notification

    req = conn.execute(
        "SELECT title, requested_by FROM work_requests WHERE id=?", (req_id,)
    ).fetchone()
    if not req:
        return

    title = req['title']
    client_link = f'/client/requests/{req_id}'

    if action in ('submit', 'resubmit'):
        label = '재제출' if action == 'resubmit' else '새 업무요청'
        staff_ids = conn.execute(
            "SELECT id FROM users WHERE role='platform_staff'"
        ).fetchall()
        for s in staff_ids:
            create_notification(
                conn, s['id'],
                f'{label}: {title}',
                link=f'/platform/work-requests/{req_id}',
            )
    elif action == 'accept':
        create_notification(conn, req['requested_by'], f'요청 수락: {title}', link=client_link)
    elif action == 'reject':
        create_notification(conn, req['requested_by'], f'요청 반려: {title}', link=client_link)
    elif action == 'complete':
        create_notification(conn, req['requested_by'], f'업무 완료: {title}', link=client_link)


def _notify_on_task_change(conn, task_id, action, user_id):
    from core.notification import create_notification

    task = conn.execute(
        "SELECT t.title, t.work_request_id AS request_id, e.user_id AS worker_user_id "
        "FROM tasks t "
        "LEFT JOIN employees e ON e.id = t.assigned_to "
        "WHERE t.id=?",
        (task_id,),
    ).fetchone()
    if not task:
        return

    title = task['title']
    task_link = f'/task/{task_id}'
    worker_uid = task['worker_user_id']

    if action == 'assign' and worker_uid:
        create_notification(conn, worker_uid, f'업무 배정: {title}', link=task_link)
    elif action == 'submit':
        mgr_ids = conn.execute(
            "SELECT cu.user_id FROM client_users cu "
            "JOIN work_requests wr ON wr.company_id = cu.company_id "
            "WHERE wr.id=?",
            (task['request_id'],),
        ).fetchall()
        for m in mgr_ids:
            create_notification(
                conn, m['user_id'],
                f'검토 요청: {title}',
                link=f'/client/tasks/{task_id}',
            )
    elif action == 'approve' and worker_uid:
        create_notification(conn, worker_uid, f'업무 승인: {title}', link=task_link)
    elif action == 'reject' and worker_uid:
        create_notification(conn, worker_uid, f'업무 반려: {title}', link=task_link)


def get_activity_logs(conn, target_type, target_id, limit=50):
    return conn.execute(
        "SELECT al.*, COALESCE(u.name, '시스템') AS user_name "
        "FROM activity_logs al "
        "LEFT JOIN users u ON u.id = al.user_id "
        "WHERE al.target_type=? AND al.target_id=? "
        "ORDER BY al.created_at DESC LIMIT ?",
        (target_type, target_id, limit),
    ).fetchall()


def sync_request_volume(conn, req_id):
    row = conn.execute(
        "SELECT COALESCE(SUM(requested_volume),0) AS total, "
        "COALESCE(SUM(CASE WHEN status='completed' THEN completed_volume ELSE 0 END),0) AS done "
        "FROM tasks WHERE work_request_id=?",
        (req_id,),
    ).fetchone()
    conn.execute(
        "UPDATE work_requests SET total_volume=?, completed_volume=? WHERE id=?",
        (row["total"], row["done"], req_id),
    )


def get_due_status(due_date_str):
    if not due_date_str:
        return None
    try:
        due = date.fromisoformat(due_date_str[:10])
    except ValueError:
        return None
    today = date.today()
    if due < today:
        return 'overdue'
    if (due - today).days <= 3:
        return 'approaching'
    return 'normal'
