
import hashlib


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def format_number(value):
    return f"{value:,}"


def truncate(text, length=50):
    if len(text) <= length:
        return text
    return text[:length] + "..."
