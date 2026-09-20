import threading
import time

# IP별 시도 타임스탬프 목록
_store = {}
_lock = threading.Lock()

MAX_ATTEMPTS = 5
WINDOW = 300  # 5분


def get_client_ip(request):
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host


def check_login_rate(ip):
    now = time.time()
    cutoff = now - WINDOW
    with _lock:
        timestamps = [t for t in _store.get(ip, []) if t > cutoff]
        _store[ip] = timestamps
        return len(timestamps) >= MAX_ATTEMPTS


def record_login_attempt(ip):
    now = time.time()
    cutoff = now - WINDOW
    with _lock:
        timestamps = [t for t in _store.get(ip, []) if t > cutoff]
        timestamps.append(now)
        _store[ip] = timestamps


def clear_login_attempts(ip):
    with _lock:
        _store.pop(ip, None)
