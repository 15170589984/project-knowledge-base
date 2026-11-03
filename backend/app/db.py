import json
import uuid
from pathlib import Path

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select

from .config import Settings
from .models import Category, CategoryField, Entry, MenuItem, MigrationMarker, ProjectShare, Role, User
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
            # 新建管理员用户也自动建一个私有分类
            seed_category_for_user(session, 1)
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
        migrate_category_owner_and_share_role(session)
        migrate_entry_fields(session)
        session.commit()


def seed_category_for_user(session: Session, user_id: int):
    """为新注册用户 seed 一个「项目地址」私有分类。"""
    exists = session.exec(
        select(Category).where(Category.owner_id == user_id, Category.name == "项目地址")
    ).first()
    if exists is None:
        session.add(Category(name="项目地址", owner_id=user_id, sort_order=0))
        session.flush()


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


def migrate_category_owner_and_share_role(session: Session):
    """Category 加 owner_id 并将旧全局分类迁移为每人私有；ProjectShare 加 role。"""
    if session.get(MigrationMarker, "category_owner_v1") is not None:
        return
    connection = session.connection()

    # Step 1: Category 表加 owner_id 列
    cat_cols = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(category)")}
    if "owner_id" not in cat_cols:
        connection.exec_driver_sql("ALTER TABLE category ADD COLUMN owner_id INTEGER REFERENCES user(id)")

    # Step 2: ProjectShare 表加 role 列
    share_cols = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(projectshare)")}
    if "role" not in share_cols:
        connection.exec_driver_sql("ALTER TABLE projectshare ADD COLUMN role VARCHAR(8) NOT NULL DEFAULT 'view'")

    # Step 3: 先重建 category 表，把 UNIQUE(name) 改成 UNIQUE(owner_id, name)
    # 否则复制同名分类给每个用户时会被旧 unique(name) 拦截
    _rebuild_category_table(connection)
    session.flush()

    # Step 4: 旧全局分类（owner_id=NULL）复制给每个用户一份私有
    global_categories = list(session.exec(select(Category).where(Category.owner_id == None)).all())
    users = list(session.exec(select(User)).all())

    # 记录 id 映射：旧全局 category_id -> {user_id: 新私有 category_id}
    id_map: dict[int, dict[int, int]] = {cat.id: {} for cat in global_categories}

    for user in users:
        for global_cat in global_categories:
            existing = session.exec(
                select(Category).where(Category.owner_id == user.id, Category.name == global_cat.name)
            ).first()
            if existing is None:
                new_cat = Category(
                    name=global_cat.name,
                    owner_id=user.id,
                    icon=global_cat.icon,
                    sort_order=global_cat.sort_order,
                    is_builtin=False,
                )
                session.add(new_cat)
                session.flush()
                id_map[global_cat.id][user.id] = new_cat.id
            else:
                id_map[global_cat.id][user.id] = existing.id

    # Step 5: 迁移 Entry.category_id：旧全局 id -> Entry.created_by 对应的私有 id
    for entry in session.exec(select(Entry)).all():
        if entry.category_id in id_map and entry.created_by in id_map[entry.category_id]:
            entry.category_id = id_map[entry.category_id][entry.created_by]
            session.add(entry)

    # Step 6: 把旧全局分类的 CategoryField 复制到各用户新私有分类
    for global_cat_id, user_map in id_map.items():
        old_fields = list(session.exec(
            select(CategoryField).where(CategoryField.category_id == global_cat_id)
        ).all())
        if not old_fields:
            continue
        for user_id, new_cat_id in user_map.items():
            for old_field in old_fields:
                existing = session.exec(
                    select(CategoryField).where(
                        CategoryField.category_id == new_cat_id,
                        CategoryField.field_key == old_field.field_key,
                    )
                ).first()
                if existing is None:
                    new_field = CategoryField(
                        category_id=new_cat_id,
                        field_key=old_field.field_key,
                        field_label=old_field.field_label,
                        field_type=old_field.field_type,
                        is_sensitive=old_field.is_sensitive,
                        sort_order=old_field.sort_order,
                    )
                    session.add(new_field)

    session.flush()

    # Step 7: 删掉旧全局分类及其 CategoryField
    for global_cat in global_categories:
        for old_field in session.exec(
            select(CategoryField).where(CategoryField.category_id == global_cat.id)
        ).all():
            session.delete(old_field)
        session.delete(global_cat)
    session.flush()

    session.add(MigrationMarker(key="category_owner_v1"))


def _rebuild_category_table(connection):
    """用 RENAME 方式重建 category 表，把 UNIQUE(name) 改成 UNIQUE(owner_id, name)。"""
    # 先读一下当前 schema 里有没有 owner_id 外键（SQLite 上 ALTER 加列不会建约束）
    # 读出现有数据后，重新建表
    connection.exec_driver_sql("PRAGMA foreign_keys=OFF")

    connection.exec_driver_sql("CREATE TABLE category_new ("
        "id INTEGER PRIMARY KEY, "
        "name VARCHAR(80) NOT NULL, "
        "owner_id INTEGER, "
        "icon VARCHAR(40), "
        "sort_order INTEGER NOT NULL DEFAULT 0, "
        "is_builtin INTEGER NOT NULL DEFAULT 0, "
        "UNIQUE(owner_id, name), "
        "FOREIGN KEY(owner_id) REFERENCES user(id)"
    ")")
    connection.exec_driver_sql(
        "INSERT INTO category_new (id, name, owner_id, icon, sort_order, is_builtin) "
        "SELECT id, name, owner_id, icon, sort_order, is_builtin FROM category"
    )
    connection.exec_driver_sql("DROP TABLE category")
    connection.exec_driver_sql("ALTER TABLE category_new RENAME TO category")

    # 重建索引
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_category_name ON category (name)")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_category_owner_id ON category (owner_id)")
    connection.exec_driver_sql("PRAGMA foreign_keys=ON")
