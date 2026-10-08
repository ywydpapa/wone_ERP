import base64
import hashlib
import hmac
import secrets

ITERATIONS = 600000


def hash_pw(password):
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    salt_b64 = base64.b64encode(salt).decode()
    hash_b64 = base64.b64encode(dk).decode()
    return f"pbkdf2_sha256${ITERATIONS}${salt_b64}${hash_b64}"


def verify_pw(password, stored):
    if stored.startswith("pbkdf2_sha256$"):
        _, iterations, salt_b64, hash_b64 = stored.split("$")
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iterations))
        return hmac.compare_digest(dk, expected)
    # 레거시 평문 sha256 호환
    legacy = hashlib.sha256(password.encode()).hexdigest()
    return hmac.compare_digest(legacy, stored)


DUMMY_HASH = hash_pw(secrets.token_hex(16))


def is_legacy(stored):
    return not stored.startswith("pbkdf2_sha256$")
