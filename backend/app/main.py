import json
import logging
import re
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from urllib.parse import urlparse

from cryptography.fernet import InvalidToken
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from sqlalchemy import String, and_, cast, func, or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from .config import Settings
from .db import initialize_database, make_engine
from .models import (
    ArchivedUser,
    AuditLog,
    Category,
    CategoryField,
    Entry,
    LoginSession,
    MenuItem,
    Project,
    ProjectParent,
    ProjectPosition,
    ProjectShare,
    RecoveryCode,
    Role,
    RoleStatus,
    User,
    utcnow,
)
from .schemas import (
    ENVIRONMENT_LABELS,
    CategoryIn,
    ChangePasswordIn,
    EntryIn,
    EntryFieldIn,
    EntryPatch,
    EntryQuery,
    LoginIn,
    MenuIn,
    MenuPatch,
    ProjectIn,
    ProjectPatch,
    RecoverIn,
    RegisterIn,
    RevealIn,
    RoleIn,
    RoleStatusPatch,
    ShareIn,
    SummaryQuery,
    UserPatch,
    UserCreate,
)
from .security import (
    COOKIE_NAME,
    SESSION_HOURS,
    AuthAttemptLimiter,
    current_identity,
    current_user,
    get_db,
    hash_password,
    make_fernet,
    new_session,
    token_hash,
    verify_password,
)


logger = logging.getLogger(__name__)


def fail(code: int, message: str):
    raise HTTPException(status_code=code, detail=message)


def save(db: Session, conflict_message: str = "数据冲突"):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=conflict_message) from exc


def audit(db: Session, user_id: int, action: str, target_type: str, target_id=None, project_id=None, detail=None):
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            project_id=project_id,
            detail=detail,
        )
    )


def audit_object_name(db: Session, row: AuditLog) -> str:
    if row.target_type in {"user", "auth"}:
        target = db.get(User, row.target_id) if row.target_id else None
        return target.display_name if target else "已删除用户"
    if row.target_type in {"project", "entry", "category"}:
        model = {"project": Project, "entry": Entry, "category": Category}[row.target_type]
        target = db.get(model, row.target_id) if row.target_id else None
        if target:
            return target.title if row.target_type == "entry" else target.name
        if row.action in {"create", "update", "delete"} and row.detail:
            return row.detail
        return {"project": "已删除项目", "entry": "已删除条目", "category": "已删除分类"}[row.target_type]
    if row.target_type in {"role", "menu"}:
        model = Role if row.target_type == "role" else MenuItem
        target = db.get(model, row.detail) if row.detail else None
        if target:
            return target.name if row.target_type == "role" else target.label
        if row.detail:
            return row.detail
        return "已删除角色" if row.target_type == "role" else "已删除菜单"
    return "未知对象"


def user_out(user: User):
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "is_active": user.is_active,
        "created_at": user.created_at,
    }


def permissions_for(db: Session, user: User) -> list[str]:
    role = db.get(Role, user.role)
    status = db.get(RoleStatus, user.role)
    return json.loads(role.permissions_json) if role and (status is None or status.is_enabled) else []


def role_enabled(db: Session, key: str) -> bool:
    status = db.get(RoleStatus, key)
    return status is None or status.is_enabled


def workspace_user(user: User = Depends(current_user), db: Session = Depends(get_db)) -> User:
    if "view_workspace" not in permissions_for(db, user):
        fail(403, "没有项目资料权限")
    return user


def require_permission(permission: str):
    def check(user: User = Depends(current_user), db: Session = Depends(get_db)):
        if permission not in permissions_for(db, user):
            fail(403, "没有此项管理权限")
        return user
    return check


def project_access(db: Session, project_id: int, user: User) -> tuple[Project, bool]:
    project = db.get(Project, project_id)
    if project is None:
        fail(404, "项目不存在")
    owner = project.owner_id == user.id
    if not owner:
        share = db.exec(
            select(ProjectShare).where(
                ProjectShare.project_id == project_id,
                ProjectShare.user_id == user.id,
            )
        ).first()
        if share is None:
            fail(404, "项目不存在")
    return project, owner


def owned_project(db: Session, project_id: int, user: User) -> Project:
    project, is_owner = project_access(db, project_id, user)
    if not is_owner:
        fail(403, "仅项目所有者可执行此操作")
    return project


def project_out(db: Session, project: Project, user: User):
    owner = db.get(User, project.owner_id)
    relation = db.get(ProjectParent, project.id)
    position = db.get(ProjectPosition, project.id)
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "owner_id": project.owner_id,
        "owner_name": owner.display_name if owner else "",
        "parent_id": relation.parent_id if relation else None,
        "sort_order": position.sort_order if position else 0,
        "is_owner": project.owner_id == user.id,
        "created_at": project.created_at,
    }


def descendant_ids(db: Session, project_id: int) -> set[int]:
    children: dict[int, list[int]] = {}
    for relation in db.exec(select(ProjectParent)):
        children.setdefault(relation.parent_id, []).append(relation.project_id)
    found = {project_id}
    pending = [project_id]
    while pending:
        for child_id in children.get(pending.pop(), []):
            if child_id not in found:
                found.add(child_id)
                pending.append(child_id)
    return found


def set_project_parent(db: Session, project: Project, parent_id: int | None, user: User):
    if parent_id == project.id or parent_id in descendant_ids(db, project.id) - {project.id}:
        fail(422, "不能将项目移动到自身或子项目下")
    if parent_id is not None:
        owned_project(db, parent_id, user)
    relation = db.get(ProjectParent, project.id)
    if relation and parent_id is None:
        db.delete(relation)
    elif relation:
        relation.parent_id = parent_id
        db.add(relation)
    elif parent_id is not None:
        db.add(ProjectParent(project_id=project.id, parent_id=parent_id))


def category_fields(db: Session, category_id: int) -> list[CategoryField]:
    return list(
        db.exec(
            select(CategoryField)
            .where(CategoryField.category_id == category_id)
            .order_by(CategoryField.sort_order, CategoryField.id)
        ).all()
    )


def category_out(db: Session, category: Category):
    return {
        "id": category.id,
        "name": category.name,
        "icon": category.icon,
        "sort_order": category.sort_order,
        "is_builtin": category.is_builtin,
    }


def entry_out(db: Session, entry: Entry, user: User, full=False):
    project = db.get(Project, entry.project_id)
    category = db.get(Category, entry.category_id)
    created_by = db.get(User, entry.created_by)
    updated_by = db.get(User, entry.updated_by)
    fields = [
        {
            "id": field["id"],
            "label": field["label"],
            "field_type": field["field_type"],
            "is_sensitive": field["is_sensitive"],
            "value": None if field["is_sensitive"] else field.get("value"),
            "has_value": bool(field.get("value")),
        }
        for field in json.loads(entry.fields_json)
    ]
    return {
        "id": entry.id,
        "project_id": entry.project_id,
        "project_name": project.name if project else "",
        "category_id": entry.category_id,
        "category_name": category.name if category else "",
        "kind": entry.kind or "entry",
        "title": entry.title,
        "environment": entry.environment,
        "content": entry.content,
        "body": entry.body if full else None,
        "sheet_json": entry.sheet_json if full else None,
        "has_body": bool(entry.body or entry.sheet_json),
        "fields": fields,
        "can_edit": bool(project and project.owner_id == user.id),
        "created_by_name": created_by.display_name if created_by else "",
        "updated_by_name": updated_by.display_name if updated_by else "",
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
    }


def require_entry(db: Session, entry_id: int, user: User, owner=False) -> Entry:
    entry = db.get(Entry, entry_id)
    if entry is None:
        fail(404, "条目不存在")
    if owner:
        owned_project(db, entry.project_id, user)
    else:
        project_access(db, entry.project_id, user)
    return entry


def validate_values(values: list[EntryFieldIn], cipher, existing=None):
    previous = {field["id"]: field for field in (existing or [])}
    if len(values) > 50:
        fail(422, "单条信息最多 50 个字段")
    result = []
    used = set()
    for field in values:
        field_id = field.id or uuid.uuid4().hex
        if field_id in used or (field.id and field.id not in previous):
            fail(422, "字段标识无效或重复")
        used.add(field_id)
        old = previous.get(field_id)
        if field.keep_existing:
            if not old or not old["is_sensitive"] or not field.is_sensitive or field.value is not None or field.field_type != old["field_type"]:
                fail(422, "不能保留此字段的原值")
            value = old["value"]
        else:
            value = field.value or None
            if value and field.field_type == "table":
                value = normalize_table_value(value, field.label)
            if value and field.field_type == "url":
                url = urlparse(value)
                if url.scheme not in {"http", "https"} or not url.netloc:
                    fail(422, field.label + " 必须是 HTTP 或 HTTPS 地址")
            if value and field.is_sensitive:
                value = cipher.encrypt(value.encode()).decode()
        result.append({"id": field_id, "label": field.label, "field_type": field.field_type, "is_sensitive": field.is_sensitive, "value": value})
    return result


def normalize_table_value(value: str, label: str) -> str:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        fail(422, label + " 的表格格式无效")
    if not isinstance(payload, dict) or set(payload) != {"rows"} or not isinstance(payload["rows"], list):
        fail(422, label + " 的表格格式无效")
    rows = payload["rows"]
    if not 1 <= len(rows) <= 30 or not isinstance(rows[0], list) or not 1 <= len(rows[0]) <= 20:
        fail(422, label + " 的表格须为 1-30 行、1-20 列")
    width = len(rows[0])
    if any(not isinstance(row, list) or len(row) != width or any(not isinstance(cell, str) or len(cell) > 1000 for cell in row) for row in rows):
        fail(422, label + " 的表格单元格无效或行列不一致")
    return json.dumps({"rows": rows}, ensure_ascii=False, separators=(",", ":"))


DOCUMENT_BODY_LIMIT = 200_000
SHEET_SIZE_LIMIT = 500_000
SHEET_CELL_LIMIT = 2_000
SHEET_ROW_LIMIT = 200
SHEET_COLUMN_LIMIT = 30
DEFAULT_RESET_PASSWORD = "123456"


def normalize_document_body(body: str | None) -> str:
    if not body or not body.strip():
        fail(422, "文档内容不能为空")
    if len(body) > DOCUMENT_BODY_LIMIT:
        fail(422, f"文档内容不能超过 {DOCUMENT_BODY_LIMIT} 字符")
    return body


def normalize_sheet_value(value: str | None, label: str) -> str:
    if not value:
        fail(422, "表格内容不能为空")
    if len(value) > SHEET_SIZE_LIMIT:
        fail(422, f"表格内容不能超过 {SHEET_SIZE_LIMIT} 字符")
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        fail(422, label + " 的表格格式无效")
    if not isinstance(payload, dict) or set(payload) != {"rows"} or not isinstance(payload["rows"], list):
        fail(422, label + " 的表格格式无效")
    rows = payload["rows"]
    if not 1 <= len(rows) <= SHEET_ROW_LIMIT or not isinstance(rows[0], list) or not 1 <= len(rows[0]) <= SHEET_COLUMN_LIMIT:
        fail(422, f"{label} 须为 1-{SHEET_ROW_LIMIT} 行、1-{SHEET_COLUMN_LIMIT} 列")
    width = len(rows[0])
    if any(
        not isinstance(row, list)
        or len(row) != width
        or any(not isinstance(cell, str) or len(cell) > SHEET_CELL_LIMIT for cell in row)
        for row in rows
    ):
        fail(422, label + " 的单元格无效或行列不一致")
    return json.dumps({"rows": rows}, ensure_ascii=False, separators=(",", ":"))


def entry_query(db: Session, user: User, params: EntryQuery):
    query = (
        select(Entry)
        .join(Project, Entry.project_id == Project.id)
        .outerjoin(
            ProjectShare,
            and_(ProjectShare.project_id == Project.id, ProjectShare.user_id == user.id),
        )
        .where(or_(Project.owner_id == user.id, ProjectShare.user_id == user.id))
    )
    if params.project_id is not None:
        if params.include_descendants:
            project_access(db, params.project_id, user)
        project_ids = descendant_ids(db, params.project_id) if params.include_descendants else {params.project_id}
        query = query.where(Entry.project_id.in_(project_ids))
    if params.category_id is not None:
        query = query.where(Entry.category_id == params.category_id)
    if params.environment:
        query = query.where(Entry.environment == params.environment.strip().upper())
    if params.q.strip():
        term = params.q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{term}%"
        values = func.json_each(Entry.fields_json).table_valued("key", "value")
        field_match = (
            select(1)
            .select_from(values)
            .where(
                func.json_extract(values.c.value, "$.is_sensitive") == 0,
                func.lower(cast(func.json_extract(values.c.value, "$.value"), String)).like(pattern, escape="\\"),
            )
            .correlate(Entry)
            .exists()
        )
        query = query.where(
            or_(
                func.lower(Entry.title).like(pattern, escape="\\"),
                func.lower(Entry.content).like(pattern, escape="\\"),
                func.lower(Entry.body).like(pattern, escape="\\"),
                func.lower(Entry.sheet_json).like(pattern, escape="\\"),
                field_match,
            )
        )
    return query


def paged_entries(db: Session, user: User, params: EntryQuery):
    query = entry_query(db, user, params)
    total = db.exec(select(func.count()).select_from(query.subquery())).one()
    rows = db.exec(
        query.order_by(Entry.updated_at.desc(), Entry.id.desc())
        .offset((params.page - 1) * params.page_size)
        .limit(params.page_size)
    ).all()
    return {
        "items": [entry_out(db, row, user) for row in rows],
        "total": total,
        "page": params.page,
        "page_size": params.page_size,
    }


def summarize_entries(db: Session, user: User, params: SummaryQuery):
    rows = db.exec(entry_query(db, user, params)).all()
    grouped = {}
    for entry in rows:
        key = entry.project_id if params.group_by == "project" else entry.category_id
        if key not in grouped:
            entity = db.get(Project if params.group_by == "project" else Category, key)
            grouped[key] = {
                "id": key,
                "name": entity.name if entity else "",
                "count": 0,
                "latest_updated_at": entry.updated_at,
            }
        grouped[key]["count"] += 1
        if entry.updated_at > grouped[key]["latest_updated_at"]:
            grouped[key]["latest_updated_at"] = entry.updated_at
    return sorted(grouped.values(), key=lambda item: (-item["count"], item["name"]))


def create_app(settings: Settings | None = None):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings or Settings.from_env()
        app.state.cipher = make_fernet(app.state.settings)
        app.state.engine = make_engine(app.state.settings)
        app.state.auth_attempts = AuthAttemptLimiter()
        initialize_database(app.state.engine, app.state.settings)
        yield
        app.state.engine.dispose()

    app = FastAPI(title="项目信息知识库", lifespan=lifespan)

    @app.middleware("http")
    async def no_store_api(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/environments")
    def list_environments(user: User = Depends(workspace_user)):
        return [
            {"value": code, "label": f"{code} {name}"}
            for code, name in ENVIRONMENT_LABELS.items()
        ]

    @app.post("/api/auth/register", status_code=201)
    def register(data: RegisterIn, db: Session = Depends(get_db)):
        if not role_enabled(db, "member"):
            fail(409, "成员角色已停用，暂不能申请账号")
        user = User(
            username=data.username,
            display_name=data.display_name,
            password_hash=hash_password(data.password),
            role="member",
            is_active=False,
        )
        db.add(user)
        save(db, "用户名已存在")
        return {"message": "注册已提交，等待管理员启用"}

    @app.post("/api/auth/login")
    def login(data: LoginIn, response: Response, request: Request, db: Session = Depends(get_db)):
        username = data.username.strip().lower()
        user = db.exec(select(User).where(User.username == username)).first()
        request.app.state.auth_attempts.consume("login", username)
        if user is None or not verify_password(data.password, user.password_hash):
            fail(401, "用户名或密码错误")
        if not user.is_active:
            fail(403, "账号尚未启用或已停用")
        token, session = new_session(db, user, request.app.state.settings.session_secret)
        response.set_cookie(
            COOKIE_NAME,
            token,
            max_age=SESSION_HOURS * 3600,
            httponly=True,
            secure=request.app.state.settings.cookie_secure,
            samesite="lax",
            path="/",
        )
        audit(db, user.id, "login", "auth", user.id)
        db.commit()
        request.app.state.auth_attempts.clear("login", username)
        return {"user": {**user_out(user), "permissions": permissions_for(db, user)}, "csrf_token": session.csrf_token}

    @app.get("/api/auth/me")
    def me(identity=Depends(current_identity), db: Session = Depends(get_db)):
        user, session = identity
        return {"user": {**user_out(user), "permissions": permissions_for(db, user)}, "csrf_token": session.csrf_token}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response, identity=Depends(current_identity), db: Session = Depends(get_db)):
        _, session = identity
        db.delete(session)
        db.commit()
        response.delete_cookie(COOKIE_NAME, path="/")
        return {"message": "已退出"}

    @app.post("/api/auth/change-password")
    def change_password(
        data: ChangePasswordIn,
        request: Request,
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        request.app.state.auth_attempts.consume("change_password", user.id)
        if not verify_password(data.current_password, user.password_hash):
            fail(400, "当前密码错误")
        user.password_hash = hash_password(data.new_password)
        db.add(user)
        for login_session in db.exec(select(LoginSession).where(LoginSession.user_id == user.id)):
            db.delete(login_session)
        audit(db, user.id, "change_password", "auth", user.id)
        db.commit()
        request.app.state.auth_attempts.clear("change_password", user.id)
        return {"message": "密码已更新，请重新登录"}

    @app.post("/api/auth/recovery-codes")
    def generate_recovery_codes(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
        for record in db.exec(select(RecoveryCode).where(RecoveryCode.user_id == user.id)):
            db.delete(record)
        codes = [secrets.token_urlsafe(18) for _ in range(8)]
        for code in codes:
            db.add(
                RecoveryCode(
                    user_id=user.id,
                    code_hash=token_hash(code, request.app.state.settings.session_secret),
                )
            )
        audit(db, user.id, "rotate_recovery_codes", "auth", user.id)
        db.commit()
        return {"codes": codes}

    @app.post("/api/auth/recover")
    def recover(data: RecoverIn, request: Request, db: Session = Depends(get_db)):
        username = data.username.strip().lower()
        user = db.exec(select(User).where(User.username == username)).first()
        request.app.state.auth_attempts.consume("recover", username)
        record = None
        if user:
            record = db.exec(
                select(RecoveryCode).where(
                    RecoveryCode.user_id == user.id,
                    RecoveryCode.code_hash == token_hash(data.recovery_code, request.app.state.settings.session_secret),
                )
            ).first()
        if user is None or record is None:
            fail(400, "用户名或恢复码无效")
        user.password_hash = hash_password(data.new_password)
        db.add(user)
        db.delete(record)
        for login_session in db.exec(select(LoginSession).where(LoginSession.user_id == user.id)):
            db.delete(login_session)
        audit(db, user.id, "recover_password", "auth", user.id)
        db.commit()
        request.app.state.auth_attempts.clear("recover", username)
        return {"message": "密码已重置，请登录"}

    @app.get("/api/users")
    def list_users(admin: User = Depends(require_permission("manage_users")), db: Session = Depends(get_db)):
        return [user_out(row) for row in db.exec(
            select(User).outerjoin(ArchivedUser, ArchivedUser.user_id == User.id)
            .where(ArchivedUser.user_id == None).order_by(User.created_at.desc())
        )]

    @app.post("/api/users", status_code=201)
    def create_user(data: UserCreate, admin: User = Depends(require_permission("manage_users")), db: Session = Depends(get_db)):
        role = db.get(Role, data.role)
        if role is None:
            fail(422, "角色不存在")
        if not role_enabled(db, role.key):
            fail(422, "角色已停用")
        if set(json.loads(role.permissions_json)) - set(permissions_for(db, admin)):
            fail(403, "不能授予超出自身的权限")
        target = User(username=data.username, display_name=data.display_name, password_hash=hash_password(data.password), role=data.role, is_active=True)
        db.add(target)
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail="用户名已存在") from exc
        audit(db, admin.id, "create", "user", target.id)
        db.commit()
        return user_out(target)

    @app.get("/api/users/available")
    def available_users(user: User = Depends(workspace_user), db: Session = Depends(get_db)):
        return [
            {"id": row.id, "username": row.username, "display_name": row.display_name}
            for row in db.exec(
                select(User).outerjoin(ArchivedUser, ArchivedUser.user_id == User.id)
                .where(User.is_active == True, User.id != user.id, ArchivedUser.user_id == None)
                .order_by(User.display_name)
            )
        ]

    @app.patch("/api/users/{user_id}")
    def update_user(user_id: int, data: UserPatch, admin: User = Depends(require_permission("manage_users")), db: Session = Depends(get_db)):
        target = db.get(User, user_id)
        if target is None or db.get(ArchivedUser, user_id):
            fail(404, "用户不存在")
        next_role = data.role if data.role is not None else target.role
        next_active = data.is_active if data.is_active is not None else target.is_active
        role = db.get(Role, next_role)
        if role is None:
            fail(422, "角色不存在")
        if next_role != target.role and not role_enabled(db, role.key):
            fail(422, "角色已停用")
        if next_role != target.role:
            own_permissions = set(permissions_for(db, admin))
            current_role = db.get(Role, target.role)
            if (set(json.loads(role.permissions_json)) | set(json.loads(current_role.permissions_json))) - own_permissions:
                fail(403, "不能调整超出自身的角色权限")
        if target.role == "admin" and target.is_active and (next_role != "admin" or not next_active):
            others = db.exec(
                select(User).where(User.role == "admin", User.is_active == True, User.id != target.id)
            ).first()
            if others is None:
                fail(409, "必须保留至少一名启用的管理员")
        target.role = next_role
        target.is_active = next_active
        if data.display_name is not None:
            target.display_name = data.display_name
        db.add(target)
        if not next_active:
            for login_session in db.exec(select(LoginSession).where(LoginSession.user_id == target.id)):
                db.delete(login_session)
        audit(db, admin.id, "update_user", "user", target.id)
        db.commit()
        return user_out(target)

    @app.post("/api/users/{user_id}/reset-password")
    def reset_user_password(user_id: int, request: Request, admin: User = Depends(require_permission("manage_users")), db: Session = Depends(get_db)):
        target = db.get(User, user_id)
        if target is None or db.get(ArchivedUser, user_id):
            fail(404, "用户不存在")
        if target.id == admin.id:
            fail(409, "不能重置当前登录账号的密码")
        target.password_hash = hash_password(DEFAULT_RESET_PASSWORD)
        db.add(target)
        for login_session in db.exec(select(LoginSession).where(LoginSession.user_id == target.id)):
            db.delete(login_session)
        request.app.state.auth_attempts.clear("login", target.username)
        audit(db, admin.id, "reset_user_password", "user", target.id)
        db.commit()
        return {"message": "密码已重置", "password": DEFAULT_RESET_PASSWORD}

    @app.delete("/api/users/{user_id}")
    def archive_user(user_id: int, admin: User = Depends(require_permission("manage_users")), db: Session = Depends(get_db)):
        target = db.get(User, user_id)
        if target is None or db.get(ArchivedUser, user_id):
            fail(404, "用户不存在")
        if target.id == admin.id:
            fail(409, "不能删除当前登录账号")
        target_role = db.get(Role, target.role)
        if target_role and set(json.loads(target_role.permissions_json)) - set(permissions_for(db, admin)):
            fail(403, "不能删除权限高于自身的用户")
        if db.exec(select(Project.id).where(Project.owner_id == user_id).limit(1)).first() is not None:
            fail(409, "该用户仍有项目，请先由本人处理项目")
        target.is_active = False
        db.add(target)
        db.add(ArchivedUser(user_id=user_id))
        for login_session in db.exec(select(LoginSession).where(LoginSession.user_id == user_id)):
            db.delete(login_session)
        for share in db.exec(select(ProjectShare).where(ProjectShare.user_id == user_id)):
            db.delete(share)
        for code in db.exec(select(RecoveryCode).where(RecoveryCode.user_id == user_id)):
            db.delete(code)
        audit(db, admin.id, "archive", "user", user_id)
        db.commit()
        return {"message": "用户已删除，历史记录已保留"}

    @app.get("/api/roles")
    def list_roles(user: User = Depends(current_user), db: Session = Depends(get_db)):
        return [
            {"key": role.key, "name": role.name, "permissions": json.loads(role.permissions_json), "is_builtin": role.is_builtin,
             "is_enabled": role_enabled(db, role.key),
             "user_count": db.exec(
                 select(func.count()).select_from(User)
                 .outerjoin(ArchivedUser, ArchivedUser.user_id == User.id)
                 .where(User.role == role.key, ArchivedUser.user_id == None)
             ).one()}
            for role in db.exec(select(Role).order_by(Role.is_builtin.desc(), Role.key))
        ]

    @app.post("/api/roles", status_code=201)
    def create_role(data: RoleIn, admin: User = Depends(require_permission("manage_roles")), db: Session = Depends(get_db)):
        if set(data.permissions) - set(permissions_for(db, admin)):
            fail(403, "不能授予超出自身的权限")
        role = Role(key=data.key, name=data.name, permissions_json=json.dumps(data.permissions))
        db.add(role)
        audit(db, admin.id, "create", "role", detail=data.name)
        save(db, "角色标识或名称已存在")
        return {"key": role.key, "name": role.name, "permissions": data.permissions, "is_builtin": False, "is_enabled": True, "user_count": 0}

    @app.put("/api/roles/{key}")
    def update_role(key: str, data: RoleIn, admin: User = Depends(require_permission("manage_roles")), db: Session = Depends(get_db)):
        role = db.get(Role, key)
        if role is None:
            fail(404, "角色不存在")
        if data.key != key:
            fail(409, "角色标识不能修改")
        if key == "admin" and not {"manage_users", "manage_roles"}.issubset(data.permissions):
            fail(409, "管理员必须保留用户和角色管理权限")
        if (set(data.permissions) | set(json.loads(role.permissions_json))) - set(permissions_for(db, admin)):
            fail(403, "不能调整超出自身的角色权限")
        role.name = data.name
        role.permissions_json = json.dumps(data.permissions)
        db.add(role)
        audit(db, admin.id, "update", "role", detail=role.name)
        save(db, "角色名称已存在")
        return {"key": key, "name": role.name, "permissions": data.permissions, "is_builtin": role.is_builtin, "is_enabled": role_enabled(db, key)}

    @app.patch("/api/roles/{key}/status")
    def update_role_status(key: str, data: RoleStatusPatch, admin: User = Depends(require_permission("manage_roles")), db: Session = Depends(get_db)):
        role = db.get(Role, key)
        if role is None:
            fail(404, "角色不存在")
        if key == "admin" and not data.is_enabled:
            fail(409, "管理员角色不能停用")
        status = db.get(RoleStatus, key) or RoleStatus(role_key=key)
        status.is_enabled = data.is_enabled
        db.add(status)
        audit(db, admin.id, "enable" if data.is_enabled else "disable", "role", detail=role.name)
        db.commit()
        return {"key": key, "is_enabled": status.is_enabled}

    @app.delete("/api/roles/{key}")
    def delete_role(key: str, admin: User = Depends(require_permission("manage_roles")), db: Session = Depends(get_db)):
        role = db.get(Role, key)
        if role is None:
            fail(404, "角色不存在")
        if role.is_builtin:
            fail(409, "不能删除内置角色")
        if db.exec(select(User.id).outerjoin(ArchivedUser, ArchivedUser.user_id == User.id)
                   .where(User.role == key, ArchivedUser.user_id == None).limit(1)).first() is not None:
            fail(409, "请先移走该角色的用户")
        status = db.get(RoleStatus, key)
        if status is not None:
            db.delete(status)
        db.delete(role)
        audit(db, admin.id, "delete", "role", detail=role.name)
        db.commit()
        return {"message": "角色已删除"}

    @app.get("/api/menus")
    def list_menus(user: User = Depends(current_user), db: Session = Depends(get_db)):
        permissions = set(permissions_for(db, user))
        required = {"/workspace": "view_workspace", "/users": "manage_users", "/roles": "manage_roles", "/menus": "manage_menus", "/logs": "view_logs"}
        return [
            {"key": row.key, "label": row.label, "path": row.path, "sort_order": row.sort_order, "is_enabled": row.is_enabled, "is_builtin": row.is_builtin}
            for row in db.exec(select(MenuItem).order_by(MenuItem.sort_order, MenuItem.key))
            if (row.is_enabled or "manage_menus" in permissions) and (
                "manage_menus" in permissions or row.path not in required or required[row.path] in permissions
            )
        ]

    @app.post("/api/menus", status_code=201)
    def create_menu(data: MenuIn, admin: User = Depends(require_permission("manage_menus")), db: Session = Depends(get_db)):
        row = MenuItem(**data.model_dump())
        db.add(row)
        audit(db, admin.id, "create", "menu", detail=row.label)
        save(db, "菜单标识已存在")
        return {"key": row.key, "label": row.label, "path": row.path, "sort_order": row.sort_order, "is_enabled": row.is_enabled, "is_builtin": False}

    @app.patch("/api/menus/{key}")
    def update_menu(key: str, data: MenuPatch, admin: User = Depends(require_permission("manage_menus")), db: Session = Depends(get_db)):
        row = db.get(MenuItem, key)
        if row is None:
            fail(404, "菜单不存在")
        changes = data.model_dump(exclude_unset=True)
        if any(value is None for value in changes.values()):
            fail(422, "菜单字段不能为空")
        if row.is_builtin and data.path is not None and data.path != row.path:
            fail(409, "内置菜单的目标页面不能修改")
        for name, value in changes.items():
            setattr(row, name, value)
        db.add(row)
        audit(db, admin.id, "update", "menu", detail=row.label)
        db.commit()
        return {"key": row.key, "label": row.label, "path": row.path, "sort_order": row.sort_order, "is_enabled": row.is_enabled, "is_builtin": row.is_builtin}

    @app.delete("/api/menus/{key}")
    def delete_menu(key: str, admin: User = Depends(require_permission("manage_menus")), db: Session = Depends(get_db)):
        row = db.get(MenuItem, key)
        if row is None:
            fail(404, "菜单不存在")
        if row.is_builtin:
            fail(409, "内置菜单不能删除，可以停用")
        db.delete(row)
        audit(db, admin.id, "delete", "menu", detail=row.label)
        db.commit()
        return {"message": "菜单已删除"}

    @app.get("/api/projects")
    def list_projects(user: User = Depends(workspace_user), db: Session = Depends(get_db)):
        rows = db.exec(
            select(Project)
            .outerjoin(ProjectShare, and_(ProjectShare.project_id == Project.id, ProjectShare.user_id == user.id))
            .where(or_(Project.owner_id == user.id, ProjectShare.user_id == user.id))
            .order_by(Project.name)
        ).all()
        return [project_out(db, row, user) for row in rows]

    @app.post("/api/projects", status_code=201)
    def create_project(data: ProjectIn, user: User = Depends(workspace_user), db: Session = Depends(get_db)):
        if data.parent_id is not None:
            owned_project(db, data.parent_id, user)
        project = Project(name=data.name, description=data.description, owner_id=user.id)
        db.add(project)
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail="你的项目中已存在同名项目") from exc
        if data.parent_id is not None:
            db.add(ProjectParent(project_id=project.id, parent_id=data.parent_id))
        db.add(ProjectPosition(project_id=project.id, sort_order=0))
        audit(db, user.id, "create", "project", project.id, project.id, project.name)
        save(db, "你的项目中已存在同名项目")
        db.refresh(project)
        return project_out(db, project, user)

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: int, user: User = Depends(workspace_user), db: Session = Depends(get_db)):
        project, _ = project_access(db, project_id, user)
        return project_out(db, project, user)

    @app.patch("/api/projects/{project_id}")
    def update_project(project_id: int, data: ProjectPatch, user: User = Depends(workspace_user), db: Session = Depends(get_db)):
        project = owned_project(db, project_id, user)
        changes = data.model_dump(exclude_unset=True)
        if "parent_id" in changes:
            set_project_parent(db, project, changes.pop("parent_id"), user)
        if "sort_order" in changes:
            order = changes.pop("sort_order")
            position = db.get(ProjectPosition, project.id) or ProjectPosition(project_id=project.id)
            position.sort_order = order
            db.add(position)
        for key, value in changes.items():
            setattr(project, key, value)
        db.add(project)
        audit(db, user.id, "update", "project", project.id, project.id, project.name)
        save(db, "你的项目中已存在同名项目")
        return project_out(db, project, user)

    @app.delete("/api/projects/{project_id}")
    def delete_project(project_id: int, user: User = Depends(workspace_user), db: Session = Depends(get_db)):
        project = owned_project(db, project_id, user)
        if db.exec(select(Entry.id).where(Entry.project_id == project_id).limit(1)).first() is not None:
            fail(409, "请先删除项目中的条目")
        if db.exec(select(ProjectParent.project_id).where(ProjectParent.parent_id == project_id).limit(1)).first() is not None:
            fail(409, "请先移走或删除子项目")
        relation = db.get(ProjectParent, project_id)
        if relation is not None:
            db.delete(relation)
        position = db.get(ProjectPosition, project_id)
        if position is not None:
            db.delete(position)
        for share in db.exec(select(ProjectShare).where(ProjectShare.project_id == project_id)):
            db.delete(share)
        for record in db.exec(select(AuditLog).where(AuditLog.project_id == project_id)):
            record.project_id = None
            db.add(record)
        audit(db, user.id, "delete", "project", project_id, detail=project.name)
        db.delete(project)
        db.commit()
        return {"message": "项目已删除"}

    @app.get("/api/projects/{project_id}/shares")
    def list_shares(project_id: int, user: User = Depends(workspace_user), db: Session = Depends(get_db)):
        owned_project(db, project_id, user)
        result = []
        for share in db.exec(select(ProjectShare).where(ProjectShare.project_id == project_id)):
            recipient = db.get(User, share.user_id)
            if recipient:
                result.append({"id": share.id, "user_id": recipient.id, "username": recipient.username, "display_name": recipient.display_name})
        return result

    @app.post("/api/projects/{project_id}/shares", status_code=201)
    def add_share(project_id: int, data: ShareIn, user: User = Depends(workspace_user), db: Session = Depends(get_db)):
        owned_project(db, project_id, user)
        recipient = db.exec(select(User).where(User.username == data.username, User.is_active == True)).first()
        if recipient is None or recipient.id == user.id:
            fail(422, "请选择其他已启用成员")
        share = ProjectShare(project_id=project_id, user_id=recipient.id)
        db.add(share)
        audit(db, user.id, "share", "project", project_id, project_id, recipient.username)
        save(db, "此成员已获得查看权限")
        return {"id": share.id, "user_id": recipient.id, "username": recipient.username, "display_name": recipient.display_name}

    @app.delete("/api/projects/{project_id}/shares/{user_id}")
    def remove_share(project_id: int, user_id: int, user: User = Depends(workspace_user), db: Session = Depends(get_db)):
        owned_project(db, project_id, user)
        share = db.exec(select(ProjectShare).where(ProjectShare.project_id == project_id, ProjectShare.user_id == user_id)).first()
        if share is None:
            fail(404, "分享不存在")
        db.delete(share)
        audit(db, user.id, "revoke_share", "project", project_id, project_id, str(user_id))
        db.commit()
        return {"message": "查看权限已撤销"}

    @app.get("/api/categories")
    def list_categories(user: User = Depends(workspace_user), db: Session = Depends(get_db)):
        rows = db.exec(select(Category).order_by(Category.sort_order, Category.name)).all()
        return [category_out(db, row) for row in rows]

    @app.post("/api/categories", status_code=201)
    def create_category(data: CategoryIn, admin: User = Depends(require_permission("manage_categories")), db: Session = Depends(get_db)):
        category = Category(name=data.name, icon=data.icon, sort_order=data.sort_order)
        db.add(category)
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail="分类名称已存在") from exc
        audit(db, admin.id, "create", "category", category.id, detail=category.name)
        save(db, "分类名称已存在")
        return category_out(db, category)

    @app.get("/api/categories/{category_id}")
    def get_category(category_id: int, user: User = Depends(workspace_user), db: Session = Depends(get_db)):
        category = db.get(Category, category_id)
        if category is None:
            fail(404, "分类不存在")
        return category_out(db, category)

    @app.put("/api/categories/{category_id}")
    def update_category(category_id: int, data: CategoryIn, admin: User = Depends(require_permission("manage_categories")), db: Session = Depends(get_db)):
        category = db.get(Category, category_id)
        if category is None:
            fail(404, "分类不存在")
        category.name = data.name
        category.icon = data.icon
        category.sort_order = data.sort_order
        db.add(category)
        audit(db, admin.id, "update", "category", category_id, detail=category.name)
        save(db, "分类名称已存在")
        return category_out(db, category)

    @app.delete("/api/categories/{category_id}")
    def delete_category(category_id: int, admin: User = Depends(require_permission("manage_categories")), db: Session = Depends(get_db)):
        category = db.get(Category, category_id)
        if category is None:
            fail(404, "分类不存在")
        if db.exec(select(Entry.id).where(Entry.category_id == category_id).limit(1)).first() is not None:
            fail(409, "分类仍被使用")
        for field in category_fields(db, category_id):
            db.delete(field)
        db.flush()
        audit(db, admin.id, "delete", "category", category_id, detail=category.name)
        db.delete(category)
        db.commit()
        return {"message": "分类已删除"}

    @app.get("/api/projects/{project_id}/categories/summary")
    def project_categories_summary(
        project_id: int,
        environment: str | None = None,
        user: User = Depends(workspace_user),
        db: Session = Depends(get_db),
    ):
        project_access(db, project_id, user)
        query = select(Entry).where(Entry.project_id == project_id)
        if environment:
            query = query.where(Entry.environment == environment.strip().upper())
        counts = {}
        for entry in db.exec(query):
            counts[entry.category_id] = counts.get(entry.category_id, 0) + 1
        return [
            {
                "id": category.id,
                "name": category.name,
                "count": counts.get(category.id, 0),
            }
            for category in db.exec(select(Category).order_by(Category.sort_order, Category.name))
        ]

    @app.get("/api/entries")
    def list_entries(
        project_id: int | None = None,
        include_descendants: bool = False,
        category_id: int | None = None,
        environment: str | None = None,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=200),
        user: User = Depends(workspace_user),
        db: Session = Depends(get_db),
    ):
        params = EntryQuery(
            project_id=project_id,
            include_descendants=include_descendants,
            category_id=category_id,
            environment=environment,
            page=page,
            page_size=page_size,
        )
        return paged_entries(db, user, params)

    @app.post("/api/entries/search")
    def search_entries(params: EntryQuery, user: User = Depends(workspace_user), db: Session = Depends(get_db)):
        return paged_entries(db, user, params)

    @app.get("/api/entries/summary")
    def entries_summary(
        group_by: str,
        project_id: int | None = None,
        category_id: int | None = None,
        environment: str | None = None,
        user: User = Depends(workspace_user),
        db: Session = Depends(get_db),
    ):
        params = SummaryQuery(
            group_by=group_by,
            project_id=project_id,
            category_id=category_id,
            environment=environment,
        )
        return summarize_entries(db, user, params)

    @app.post("/api/entries/summary/search")
    def search_summary(params: SummaryQuery, user: User = Depends(workspace_user), db: Session = Depends(get_db)):
        return summarize_entries(db, user, params)

    @app.get("/api/entries/{entry_id}")
    def get_entry(entry_id: int, user: User = Depends(workspace_user), db: Session = Depends(get_db)):
        return entry_out(db, require_entry(db, entry_id, user), user, full=True)

    @app.post("/api/entries", status_code=201)
    def create_entry(data: EntryIn, request: Request, user: User = Depends(workspace_user), db: Session = Depends(get_db)):
        owned_project(db, data.project_id, user)
        if db.get(Category, data.category_id) is None:
            fail(404, "分类不存在")
        stored, body, sheet = [], None, None
        if data.kind == "entry":
            if data.body or data.sheet_json:
                fail(422, "条目类型不支持文档或表格内容")
            stored = validate_values(data.fields, request.app.state.cipher)
        elif data.kind == "document":
            if data.sheet_json or data.fields:
                fail(422, "文档类型不支持表格或自定义字段")
            body = normalize_document_body(data.body)
        else:
            if data.body or data.fields:
                fail(422, "表格类型不支持文档正文或自定义字段")
            sheet = normalize_sheet_value(data.sheet_json, data.title)
        entry = Entry(
            project_id=data.project_id,
            category_id=data.category_id,
            kind=data.kind,
            title=data.title,
            environment=data.environment,
            content=data.content,
            body=body,
            sheet_json=sheet,
            fields_json=json.dumps(stored, ensure_ascii=False),
            created_by=user.id,
            updated_by=user.id,
        )
        db.add(entry)
        db.flush()
        audit(db, user.id, "create", "entry", entry.id, entry.project_id, entry.title)
        db.commit()
        return entry_out(db, entry, user, full=True)

    @app.patch("/api/entries/{entry_id}")
    def update_entry(
        entry_id: int,
        data: EntryPatch,
        request: Request,
        user: User = Depends(workspace_user),
        db: Session = Depends(get_db),
    ):
        entry = require_entry(db, entry_id, user, owner=True)
        changes = data.model_dump(exclude_unset=True)
        for key in ("title", "environment", "content"):
            if key in changes:
                if key == "title" and changes[key] is None:
                    fail(422, "标题不能为空")
                setattr(entry, key, changes[key])
        if entry.kind == "entry":
            if changes.get("fields") is not None:
                stored = json.loads(entry.fields_json)
                validated = validate_values(data.fields, request.app.state.cipher, stored)
                entry.fields_json = json.dumps(validated, ensure_ascii=False)
            if changes.get("body") is not None or changes.get("sheet_json") is not None:
                fail(422, "条目类型不支持文档或表格内容")
        elif entry.kind == "document":
            if changes.get("fields") is not None or changes.get("sheet_json") is not None:
                fail(422, "文档类型不支持表格或自定义字段")
            if changes.get("body") is not None:
                entry.body = normalize_document_body(changes["body"])
        else:
            if changes.get("fields") is not None or changes.get("body") is not None:
                fail(422, "表格类型不支持文档正文或自定义字段")
            if changes.get("sheet_json") is not None:
                entry.sheet_json = normalize_sheet_value(changes["sheet_json"], entry.title)
        entry.updated_by = user.id
        entry.updated_at = utcnow()
        db.add(entry)
        audit(db, user.id, "update", "entry", entry.id, entry.project_id, entry.title)
        db.commit()
        return entry_out(db, entry, user, full=True)

    @app.delete("/api/entries/{entry_id}")
    def delete_entry(entry_id: int, user: User = Depends(workspace_user), db: Session = Depends(get_db)):
        entry = require_entry(db, entry_id, user, owner=True)
        audit(db, user.id, "delete", "entry", entry.id, entry.project_id, entry.title)
        entry.fields_json = "[]"
        db.add(entry)
        db.flush()
        db.delete(entry)
        db.commit()
        return {"message": "条目已删除"}

    @app.post("/api/entries/{entry_id}/reveal")
    def reveal_entry(
        entry_id: int,
        data: RevealIn,
        request: Request,
        user: User = Depends(workspace_user),
        db: Session = Depends(get_db),
    ):
        entry = require_entry(db, entry_id, user, owner=True)
        field = next((row for row in json.loads(entry.fields_json) if row["id"] == data.field_id), None)
        if field is None or not field["is_sensitive"]:
            fail(404, "敏感字段不存在")
        token = field.get("value")
        if not token:
            fail(404, "此字段未设置")
        try:
            value = request.app.state.cipher.decrypt(token.encode()).decode()
        except (InvalidToken, UnicodeDecodeError):
            logger.error("Cannot decrypt secret for entry_id=%s field_id=%s", entry.id, data.field_id)
            return {"field_id": data.field_id, "value": None, "unavailable": True, "placeholder": "无法解密"}
        audit(db, user.id, "reveal_" + data.purpose, "entry", entry.id, entry.project_id, field["label"])
        db.commit()
        return {"field_id": data.field_id, "value": value}

    @app.get("/api/projects/{project_id}/audit-logs")
    def project_audit_logs(
        project_id: int,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=200),
        user: User = Depends(workspace_user),
        db: Session = Depends(get_db),
    ):
        owned_project(db, project_id, user)
        query = select(AuditLog).where(AuditLog.project_id == project_id)
        total = db.exec(select(func.count()).select_from(query.subquery())).one()
        rows = db.exec(
            query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return {
            "items": [
                {
                    "id": row.id,
                    "action": row.action,
                    "target_type": row.target_type,
                    "target_id": row.target_id,
                    "detail": row.detail,
                    "created_at": row.created_at,
                }
                for row in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    @app.get("/api/admin/audit-logs")
    def admin_audit_logs(
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=200),
        target_type: str | None = None,
        q: str | None = Query(default=None, max_length=100),
        admin: User = Depends(require_permission("view_logs")),
        db: Session = Depends(get_db),
    ):
        system_types = {"user", "category", "auth", "role", "menu"}
        personal_types = {"project", "entry"}
        allowed_types = system_types | personal_types
        if target_type is not None and target_type not in allowed_types:
            fail(422, "日志类型无效")
        query = select(AuditLog).where(or_(
            AuditLog.target_type.in_(system_types),
            and_(AuditLog.target_type.in_(personal_types), AuditLog.user_id == admin.id),
        ))
        if target_type:
            query = query.where(AuditLog.target_type == target_type)
        if q and q.strip():
            term = f"%{q.strip().lower()}%"
            matching_users = select(User.id).where(func.lower(User.display_name).like(term))
            query = query.where(or_(
                func.lower(AuditLog.action).like(term),
                func.lower(AuditLog.detail).like(term),
                AuditLog.user_id.in_(matching_users),
            ))
        total = db.exec(select(func.count()).select_from(query.subquery())).one()
        rows = db.exec(
            query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return {
            "items": [
                {
                    "id": row.id,
                    "user_id": row.user_id,
                    "username": (db.get(User, row.user_id).display_name if db.get(User, row.user_id) else "已删除用户"),
                    "action": row.action,
                    "target_type": row.target_type,
                    "target_id": row.target_id,
                    "object_name": audit_object_name(db, row),
                    "detail": row.detail,
                    "created_at": row.created_at,
                }
                for row in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    return app


app = create_app()
