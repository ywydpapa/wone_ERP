import os

from cryptography.fernet import Fernet

ENC_PREFIX = "enc:"


def _fernet():
    key = os.getenv("ERP_RNO_KEY")
    if not key:
        raise RuntimeError("ERP_RNO_KEY가 설정되지 않았습니다")
    return Fernet(key.encode())


def enc_rno(value):
    if not value:
        return value
    return ENC_PREFIX + _fernet().encrypt(value.encode()).decode()


def dec_rno(value):
    if not value or not value.startswith(ENC_PREFIX):
        return value
    return _fernet().decrypt(value[len(ENC_PREFIX):].encode()).decode()


def valid_rno(value):
    digits = value.replace("-", "")
    return len(digits) == 13 and digits.isdigit()
