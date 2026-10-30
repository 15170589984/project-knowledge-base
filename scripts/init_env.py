import base64
import secrets
from pathlib import Path


root = Path(__file__).resolve().parents[1]
target = root / ".env"
if target.exists():
    raise SystemExit(".env already exists; it was not changed")

password = "admin123"
content = "\n".join(
    [
        "FERNET_KEY=" + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "SESSION_SECRET=" + secrets.token_urlsafe(48),
        "INITIAL_ADMIN_USERNAME=admin",
        "INITIAL_ADMIN_PASSWORD=" + password,
        "DATABASE_PATH=/data/knowledge.db",
        "COOKIE_SECURE=false",
        "HTTP_PORT=8080",
        "",
    ]
)
target.write_text(content, encoding="utf-8")
print(".env created. Initial admin username: admin")
print("Initial admin password: " + password)
