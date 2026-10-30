import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]{3,64}$")
FIELD_TYPES = {"text", "password", "url", "textarea", "table"}
ENTRY_KINDS = {"entry", "document", "spreadsheet"}
SYSTEM_PERMISSIONS = {"view_workspace", "manage_users", "manage_roles", "manage_menus", "manage_categories", "view_logs"}
ENVIRONMENT_LABELS = {
    "DEV": "开发",
    "TEST": "测试",
    "SIT": "集成",
    "UAT": "验收",
    "PRE": "灰度/预发",
    "PROD": "生产",
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def required_text(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("不能为空")
    return value


def valid_environment(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    if not normalized:
        return None
    if normalized not in ENVIRONMENT_LABELS:
        raise ValueError("环境必须是 DEV、TEST、SIT、UAT、PRE 或 PROD")
    return normalized


class RegisterIn(StrictModel):
    username: str
    display_name: str
    password: str = Field(min_length=6, max_length=128)

    @field_validator("username")
    @classmethod
    def valid_username(cls, value):
        value = value.strip().lower()
        if not USERNAME_PATTERN.fullmatch(value):
            raise ValueError("用户名需为 3-64 位字母、数字、下划线、点或短横线")
        return value

    @field_validator("display_name")
    @classmethod
    def valid_display_name(cls, value):
        return required_text(value)


class LoginIn(StrictModel):
    username: str
    password: str


class ChangePasswordIn(StrictModel):
    current_password: str
    new_password: str = Field(min_length=6, max_length=128)


class RecoverIn(StrictModel):
    username: str
    recovery_code: str
    new_password: str = Field(min_length=6, max_length=128)


class UserPatch(StrictModel):
    is_active: bool | None = None
    role: str | None = None
    display_name: str | None = Field(default=None, max_length=80)

    @field_validator("display_name")
    @classmethod
    def valid_display_name(cls, value):
        return required_text(value) if value is not None else value

    @field_validator("role")
    @classmethod
    def valid_role(cls, value):
        if value is not None and not re.fullmatch(r"[a-z][a-z0-9_]{1,15}", value):
            raise ValueError("角色无效")
        return value


class UserCreate(StrictModel):
    username: str
    display_name: str = Field(max_length=80)
    password: str = Field(min_length=6, max_length=128)
    role: str = "member"

    @field_validator("username")
    @classmethod
    def valid_username(cls, value):
        value = value.strip().lower()
        if not USERNAME_PATTERN.fullmatch(value):
            raise ValueError("用户名无效")
        return value

    @field_validator("display_name")
    @classmethod
    def valid_display_name(cls, value):
        return required_text(value)


class ProjectIn(StrictModel):
    name: str = Field(max_length=120)
    description: str | None = None
    parent_id: int | None = Field(default=None, gt=0)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        return required_text(value)


class ProjectPatch(StrictModel):
    name: str | None = Field(default=None, max_length=120)
    description: str | None = None
    parent_id: int | None = Field(default=None, gt=0)
    sort_order: int | None = Field(default=None, ge=-9999, le=9999)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        return required_text(value) if value is not None else value


class ShareIn(StrictModel):
    username: str

    @field_validator("username")
    @classmethod
    def valid_username(cls, value):
        return value.strip().lower()


class CategoryIn(StrictModel):
    name: str = Field(max_length=80)
    icon: str | None = Field(default=None, max_length=40)
    sort_order: int = 0

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        return required_text(value)


class EntryIn(StrictModel):
    project_id: int
    category_id: int
    kind: str = "entry"
    title: str = Field(max_length=160)
    environment: str | None = Field(default=None, max_length=40)
    content: str | None = None
    body: str | None = None
    sheet_json: str | None = None
    fields: list["EntryFieldIn"] = Field(default_factory=list)

    @field_validator("kind")
    @classmethod
    def valid_kind(cls, value):
        if value not in ENTRY_KINDS:
            raise ValueError("内容类型无效")
        return value

    @field_validator("title")
    @classmethod
    def valid_title(cls, value):
        return required_text(value)

    @field_validator("environment")
    @classmethod
    def normalize_environment(cls, value):
        return valid_environment(value)


class EntryPatch(StrictModel):
    title: str | None = Field(default=None, max_length=160)
    environment: str | None = Field(default=None, max_length=40)
    content: str | None = None
    body: str | None = None
    sheet_json: str | None = None
    fields: list["EntryFieldIn"] | None = None

    @field_validator("title")
    @classmethod
    def valid_title(cls, value):
        return required_text(value) if value is not None else value

    @field_validator("environment")
    @classmethod
    def normalize_environment(cls, value):
        return valid_environment(value)


class EntryQuery(StrictModel):
    project_id: int | None = None
    include_descendants: bool = False
    category_id: int | None = None
    environment: str | None = None
    q: str = Field(default="", max_length=200)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)


class SummaryQuery(EntryQuery):
    group_by: str

    @field_validator("group_by")
    @classmethod
    def valid_group_by(cls, value):
        if value not in {"project", "category"}:
            raise ValueError("group_by 无效")
        return value


class RevealIn(StrictModel):
    field_id: str
    purpose: str = "view"

    @field_validator("purpose")
    @classmethod
    def valid_purpose(cls, value):
        if value not in {"view", "copy"}:
            raise ValueError("用途无效")
        return value


class EntryFieldIn(StrictModel):
    id: str | None = Field(default=None, max_length=40)
    label: str = Field(max_length=80)
    field_type: str = "text"
    is_sensitive: bool = False
    value: str | None = Field(default=None, max_length=10000)
    keep_existing: bool = False

    @field_validator("label")
    @classmethod
    def valid_label(cls, value):
        return required_text(value)

    @field_validator("field_type")
    @classmethod
    def valid_type(cls, value):
        if value not in FIELD_TYPES:
            raise ValueError("字段类型无效")
        return value

class RoleIn(StrictModel):
    key: str
    name: str = Field(max_length=80)
    permissions: list[str] = Field(default_factory=list)

    @field_validator("key")
    @classmethod
    def valid_key(cls, value):
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,15}", value):
            raise ValueError("角色标识需为 2-16 位小写字母、数字或下划线")
        return value

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        return required_text(value)

    @field_validator("permissions")
    @classmethod
    def valid_permissions(cls, value):
        if len(value) != len(set(value)) or set(value) - SYSTEM_PERMISSIONS:
            raise ValueError("权限无效或重复")
        return value


class RoleStatusPatch(StrictModel):
    is_enabled: bool


class MenuPatch(StrictModel):
    label: str | None = Field(default=None, max_length=80)
    path: str | None = None
    sort_order: int | None = Field(default=None, ge=-9999, le=9999)
    is_enabled: bool | None = None

    @field_validator("label")
    @classmethod
    def valid_label(cls, value):
        return required_text(value) if value is not None else value

    @field_validator("path")
    @classmethod
    def valid_path(cls, value):
        if value is not None and value not in {"/workspace", "/users", "/roles", "/menus", "/logs"}:
            raise ValueError("请选择已有页面")
        return value


class MenuIn(StrictModel):
    key: str
    label: str = Field(max_length=80)
    path: str
    sort_order: int = Field(default=0, ge=-9999, le=9999)
    is_enabled: bool = True

    @field_validator("key")
    @classmethod
    def valid_key(cls, value):
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,31}", value):
            raise ValueError("菜单标识无效")
        return value

    @field_validator("label")
    @classmethod
    def valid_label(cls, value):
        return required_text(value)

    @field_validator("path")
    @classmethod
    def valid_path(cls, value):
        if value not in {"/workspace", "/users", "/roles", "/menus", "/logs"}:
            raise ValueError("请选择已有页面")
        return value
