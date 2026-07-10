import json
import os
import hashlib
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes


VAULT_FILE = "vault.dat"
SALT_FILE = "salt.dat"

DEFAULT_VAULT = {
    "sites": [],
    "passwords": {},
    "api_keys": {},
    "settings": {
        "timeout": 20,
        "request_delay": 1.5,
        "proxy_url": "",
        "ai_provider": "gemini",
        "ai_model": "",
        "ai_tone": "neutral",
        "ai_language": "persian",
        "ai_temperature": 0.7,
        "ai_min_words": 10,
        "ai_max_words": 60,
        "schedule_interval": 3600,
    },
    "api_keys_ai": {},
}


def _get_vault_dir():
    if os.name == "nt":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
        d = os.path.join(base, "WPCommentManager")
    else:
        base = os.environ.get("HOME", os.path.expanduser("~"))
        d = os.path.join(base, ".wp_comment_manager")
    os.makedirs(d, exist_ok=True)
    return d


def _derive_key(master_pwd: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600000)
    return base64.urlsafe_b64encode(kdf.derive(master_pwd.encode()))


def _load_salt(vault_dir: str) -> bytes:
    sp = os.path.join(vault_dir, SALT_FILE)
    if os.path.exists(sp):
        with open(sp, "rb") as f:
            return f.read()
    salt = os.urandom(16)
    with open(sp, "wb") as f:
        f.write(salt)
    return salt


def _vault_path(vault_dir: str) -> str:
    return os.path.join(vault_dir, VAULT_FILE)


def vault_exists() -> bool:
    return os.path.exists(_vault_path(_get_vault_dir()))


def load_vault(master_pwd: str) -> dict:
    vd = _get_vault_dir()
    vp = _vault_path(vd)
    if not os.path.exists(vp):
        return dict(DEFAULT_VAULT)
    salt = _load_salt(vd)
    key = _derive_key(master_pwd, salt)
    try:
        cipher = Fernet(key)
        with open(vp, "rb") as f:
            encrypted = f.read()
        decrypted = cipher.decrypt(encrypted)
        data = json.loads(decrypted.decode())
        for k, v in DEFAULT_VAULT.items():
            data.setdefault(k, v)
        return data
    except Exception:
        return None


def save_vault(master_pwd: str, data: dict):
    vd = _get_vault_dir()
    salt = _load_salt(vd)
    key = _derive_key(master_pwd, salt)
    cipher = Fernet(key)
    encrypted = cipher.encrypt(json.dumps(data, ensure_ascii=False).encode())
    with open(_vault_path(vd), "wb") as f:
        f.write(encrypted)
