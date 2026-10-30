import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_path: str
    fernet_key: str
    session_secret: str
    initial_admin_username: str
    initial_admin_password: str
    cookie_secure: bool
    seed_default_categories: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        required = (
            "FERNET_KEY",
            "SESSION_SECRET",
            "INITIAL_ADMIN_USERNAME",
            "INITIAL_ADMIN_PASSWORD",
        )
        missing = [key for key in required if not os.getenv(key)]
        if missing:
            raise RuntimeError("Missing required environment variables: " + ", ".join(missing))
        return cls(
            database_path=os.getenv("DATABASE_PATH", "./data/knowledge.db"),
            fernet_key=os.environ["FERNET_KEY"],
            session_secret=os.environ["SESSION_SECRET"],
            initial_admin_username=os.environ["INITIAL_ADMIN_USERNAME"],
            initial_admin_password=os.environ["INITIAL_ADMIN_PASSWORD"],
            cookie_secure=os.getenv("COOKIE_SECURE", "true").lower() == "true",
            seed_default_categories=os.getenv("SEED_DEFAULT_CATEGORIES", "false").lower() == "true",
        )
