import os
import threading
import time

# IP별 시도 타임스탬프 목록
_store = {}
_lock = threading.Lock()

MAX_ATTEMPTS = 5
WINDOW = 300  # 5분

# 리버스 프록시 뒤에 있을 때만 XFF 신뢰. 없으면 위조 가능
TRUST_PROXY = os.getenv("TRUST_PROXY") == "1"


def get_client_ip(request):
    if TRUST_PROXY:
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
