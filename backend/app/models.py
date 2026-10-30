from datetime import datetime, timezone

from sqlalchemy import Column, UniqueConstraint
from sqlalchemy.types import Text
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True, max_length=64)
    display_name: str = Field(max_length=80)
    password_hash: str
    role: str = Field(default="member", max_length=16)
    is_active: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utcnow)


class ArchivedUser(SQLModel, table=True):
    user_id: int = Field(foreign_key="user.id", primary_key=True)
    archived_at: datetime = Field(default_factory=utcnow)


class RecoveryCode(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    code_hash: str = Field(index=True)
    created_at: datetime = Field(default_factory=utcnow)


class LoginSession(SQLModel, table=True):
    token_hash: str = Field(primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    csrf_token: str
    expires_at: datetime = Field(index=True)
    created_at: datetime = Field(default_factory=utcnow)


class Project(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("owner_id", "name"),)

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=120, index=True)
    description: str | None = Field(default=None, sa_column=Column(Text))
    owner_id: int = Field(foreign_key="user.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)


class ProjectShare(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("project_id", "user_id"),)

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)


class ProjectParent(SQLModel, table=True):
    project_id: int = Field(foreign_key="project.id", primary_key=True)
    parent_id: int = Field(foreign_key="project.id", index=True)


class ProjectPosition(SQLModel, table=True):
    project_id: int = Field(foreign_key="project.id", primary_key=True)
    sort_order: int = Field(default=0)


class Role(SQLModel, table=True):
    key: str = Field(primary_key=True, max_length=16)
    name: str = Field(unique=True, max_length=80)
    permissions_json: str = Field(default="[]", sa_column=Column(Text))
    is_builtin: bool = Field(default=False)


class RoleStatus(SQLModel, table=True):
    role_key: str = Field(foreign_key="role.key", primary_key=True)
    is_enabled: bool = Field(default=True)


class MigrationMarker(SQLModel, table=True):
    key: str = Field(primary_key=True, max_length=80)


class MenuItem(SQLModel, table=True):
    key: str = Field(primary_key=True, max_length=32)
    label: str = Field(max_length=80)
    path: str = Field(max_length=80)
    sort_order: int = Field(default=0)
    is_enabled: bool = Field(default=True)
    is_builtin: bool = Field(default=False)


class Category(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True, max_length=80)
    icon: str | None = Field(default=None, max_length=40)
    sort_order: int = Field(default=0)
    is_builtin: bool = Field(default=False)


class CategoryField(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("category_id", "field_key"),)

    id: int | None = Field(default=None, primary_key=True)
    category_id: int = Field(foreign_key="category.id", index=True)
    field_key: str = Field(max_length=64)
    field_label: str = Field(max_length=80)
    field_type: str = Field(max_length=16)
    is_sensitive: bool = Field(default=False)
    sort_order: int = Field(default=0)


class Entry(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    category_id: int = Field(foreign_key="category.id", index=True)
    kind: str = Field(default="entry", index=True, max_length=16)
    title: str = Field(index=True, max_length=160)
    environment: str | None = Field(default=None, index=True, max_length=40)
    content: str | None = Field(default=None, sa_column=Column(Text))
    body: str | None = Field(default=None, sa_column=Column(Text))
    sheet_json: str | None = Field(default=None, sa_column=Column(Text))
    fields_json: str = Field(default="{}", sa_column=Column(Text))
    created_by: int = Field(foreign_key="user.id")
    updated_by: int = Field(foreign_key="user.id")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow, index=True)


class AuditLog(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    action: str = Field(max_length=40)
    target_type: str = Field(max_length=32)
    target_id: int | None = Field(default=None)
    project_id: int | None = Field(default=None, foreign_key="project.id", index=True)
    detail: str | None = Field(default=None, max_length=200)
    created_at: datetime = Field(default_factory=utcnow, index=True)
