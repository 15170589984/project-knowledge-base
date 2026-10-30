import json
import uuid
from pathlib import Path

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select

from .config import Settings
from .models import Category, CategoryField, Entry, MenuItem, MigrationMarker, Role, User
from .security import hash_password


def make_engine(settings: Settings):
    database_path = Path(settings.database_path).resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )

    @event.listens_for(engine, "connect")
    def set_pragmas(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    return engine


def initialize_database(engine, settings: Settings):
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        users = session.exec(select(User).limit(1)).first()
        if users is None:
            if len(settings.initial_admin_password) < 6:
                raise RuntimeError("INITIAL_ADMIN_PASSWORD must contain at least 6 characters")
            session.add(
                User(
                    username=settings.initial_admin_username.strip().lower(),
                    display_name="系统管理员",
                    password_hash=hash_password(settings.initial_admin_password),
                    role="admin",
                    is_active=True,
                )
            )
            session.commit()
        elif session.exec(select(User).where(User.role == "admin", User.is_active == True)).first() is None:
            raise RuntimeError("Database has no active admin; refusing to create a new one")
        if settings.seed_default_categories and session.exec(select(Category.id).limit(1)).first() is None:
            seed_default_categories(session)
        if session.get(Role, "admin") is None:
            session.add(Role(key="admin", name="管理员", permissions_json=json.dumps(["view_workspace", "manage_users", "manage_roles", "manage_menus", "manage_categories", "view_logs"]), is_builtin=True))
        if session.get(Role, "member") is None:
            session.add(Role(key="member", name="成员", permissions_json='["view_workspace"]', is_builtin=True))
        session.flush()
        if session.get(MigrationMarker, "workspace_permission_v1") is None:
            for role in session.exec(select(Role)):
                permissions = json.loads(role.permissions_json)
                if "view_workspace" not in permissions:
                    role.permissions_json = json.dumps(["view_workspace", *permissions])
                    session.add(role)
            session.add(MigrationMarker(key="workspace_permission_v1"))
        for key, label, path, order in (
            ("workspace", "项目资料", "/workspace", 0),
            ("users", "用户管理", "/users", 10),
            ("roles", "角色管理", "/roles", 20),
            ("menus", "菜单管理", "/menus", 30),
            ("logs", "操作日志", "/logs", 40),
        ):
            if session.get(MenuItem, key) is None:
                session.add(MenuItem(key=key, label=label, path=path, sort_order=order, is_builtin=True))
        migrate_entry_kind(session)
        migrate_entry_fields(session)
        session.commit()


def seed_default_categories(session: Session):
    names = ("需求文档", "测试文档", "接口文档", "数据库", "服务器", "日志", "Nacos")
    for position, name in enumerate(names):
        session.add(Category(name=name, sort_order=position * 10))
    session.commit()


def migrate_entry_fields(session: Session):
    definitions = {category.id: {} for category in session.exec(select(Category))}
    for field in session.exec(select(CategoryField)):
        definitions.setdefault(field.category_id, {})[field.field_key] = field
    for entry in session.exec(select(Entry)):
        stored = json.loads(entry.fields_json)
        if isinstance(stored, list):
            continue
        converted = []
        for key, value in stored.items():
            definition = definitions.get(entry.category_id, {}).get(key)
            converted.append({
                "id": uuid.uuid4().hex,
                "label": definition.field_label if definition else key,
                "field_type": definition.field_type if definition else "password",
                "is_sensitive": definition.is_sensitive if definition else True,
                "value": value,
            })
        entry.fields_json = json.dumps(converted, ensure_ascii=False)
        session.add(entry)


def migrate_entry_kind(session: Session):
    connection = session.connection()
    columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(entry)")}
    if "kind" not in columns:
        connection.exec_driver_sql("ALTER TABLE entry ADD COLUMN kind VARCHAR(16) NOT NULL DEFAULT 'entry'")
    if "body" not in columns:
        connection.exec_driver_sql("ALTER TABLE entry ADD COLUMN body TEXT")
    if "sheet_json" not in columns:
        connection.exec_driver_sql("ALTER TABLE entry ADD COLUMN sheet_json TEXT")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_entry_kind ON entry (kind)")
