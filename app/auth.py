"""Password hashing (scrypt, stdlib) and a simple login rate limiter."""
import base64
import hashlib
import hmac
import os
import time

_N, _R, _P = 2 ** 14, 8, 1


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_b64, dk_b64 = stored.split("$")
        salt, dk = base64.b64decode(salt_b64), base64.b64decode(dk_b64)
    except ValueError:
        return False
    test = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=len(dk))
    return hmac.compare_digest(test, dk)


class RateLimiter:
    """Max `limit` failed logins per IP within `window` seconds."""

    def __init__(self, limit=8, window=600):
        self.limit, self.window, self.fails = limit, window, {}

    def blocked(self, ip):
        now = time.time()
        self.fails[ip] = [t for t in self.fails.get(ip, []) if now - t < self.window]
        return len(self.fails[ip]) >= self.limit

    def fail(self, ip):
        self.fails.setdefault(ip, []).append(time.time())

    def reset(self, ip):
        self.fails.pop(ip, None)


def load_secret(data_dir):
    env = os.environ.get("SECRET_KEY")
    if env:
        return env
    path = os.path.join(data_dir, "secret.key")
    if os.path.exists(path):
        with open(path) as f:
            return f.read().strip()
    key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    os.makedirs(data_dir, exist_ok=True)
    with open(path, "w") as f:
        f.write(key)
    os.chmod(path, 0o600)
    return key
