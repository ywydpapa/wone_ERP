# funchub.py

import hashlib


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def format_number(value: int) -> str:
    return f"{value:,}"


def truncate(text: str, length: int = 50) -> str:
    if len(text) <= length:
        return text
    return text[:length] + "..."
