import json
import sqlite3
from dataclasses import replace

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.config import Settings
from app.db import initialize_database
from app.main import create_app
from app.models import Category, CategoryField, MigrationMarker, Role


@pytest.fixture
def environment(tmp_path):
    settings = Settings(
        database_path=str(tmp_path / "knowledge.db"),
        fernet_key=Fernet.generate_key().decode(),
        session_secret="test-session-secret-with-enough-entropy",
        initial_admin_username="admin",
        initial_admin_password="AdminPassword!2026",
        cookie_secure=False,
    )
    with TestClient(create_app(settings)) as admin:
        yield admin, settings


def login(client, username, password):
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def register(client, username):
    response = client.post(
        "/api/auth/register",
        json={"username": username, "display_name": username.title(), "password": "MemberPassword!2026"},
    )
    assert response.status_code == 201, response.text


def enable(admin, headers, username):
    user = next(row for row in admin.get("/api/users").json() if row["username"] == username)
    response = admin.patch(
        f"/api/users/{user['id']}",
        json={"is_active": True},
        headers=headers,
    )
    assert response.status_code == 200, response.text


def make_client(app, username):
    client = TestClient(app)
    return client, login(client, username, "MemberPassword!2026")


def test_private_share_and_secret_boundaries(environment):
    admin, settings = environment
    admin_headers = login(admin, "admin", "AdminPassword!2026")
    register(admin, "alice")
    register(admin, "bob")
    enable(admin, admin_headers, "alice")
    enable(admin, admin_headers, "bob")
    category_response = admin.post(
        "/api/categories",
        json={"name": "数据库"},
        headers=admin_headers,
    )
    assert category_response.status_code == 201, category_response.text
    category_id = category_response.json()["id"]
    duplicate = admin.post(
        "/api/categories",
        json={"name": "数据库"},
        headers=admin_headers,
    )
    assert duplicate.status_code == 409
    alice, alice_headers = make_client(admin.app, "alice")
    bob, bob_headers = make_client(admin.app, "bob")
    project_response = alice.post(
        "/api/projects",
        json={"name": "用户中心", "description": "内部项目"},
        headers=alice_headers,
    )
    assert project_response.status_code == 201, project_response.text
    project_id = project_response.json()["id"]
    entry_response = alice.post(
        "/api/entries",
        json={
            "project_id": project_id,
            "category_id": category_id,
            "title": "UAT 数据库",
            "environment": "UAT",
            "content": "测试连接",
            "fields": [
                {"label": "主机", "value": "db.internal"},
                {"label": "密码", "field_type": "password", "is_sensitive": True, "value": "SuperSecret!"},
            ],
        },
        headers=alice_headers,
    )
    assert entry_response.status_code == 201, entry_response.text
    entry_id = entry_response.json()["id"]
    password_field = next(field for field in entry_response.json()["fields"] if field["label"] == "密码")
    assert password_field["value"] is None
    assert password_field["has_value"] is True

    with sqlite3.connect(settings.database_path) as connection:
        stored = connection.execute("SELECT fields_json FROM entry WHERE id = ?", (entry_id,)).fetchone()[0]
    assert "SuperSecret!" not in stored
    assert "db.internal" in stored

    own_list = alice.get("/api/entries").json()
    assert own_list["total"] == 1
    assert "SuperSecret!" not in str(own_list)
    assert bob.get("/api/entries").json()["total"] == 0


    assert admin.get("/api/entries").json()["total"] == 0
    assert bob.get(f"/api/entries/{entry_id}").status_code == 404
    assert admin.get(f"/api/entries/{entry_id}").status_code == 404
    assert bob.get(f"/api/projects/{project_id}/categories/summary").status_code == 404

    share_response = alice.post(
        f"/api/projects/{project_id}/shares",
        json={"username": "bob"},
        headers=alice_headers,
    )
    assert share_response.status_code == 201, share_response.text
    shared = bob.get(f"/api/entries/{entry_id}").json()
    assert next(field for field in shared["fields"] if field["label"] == "主机")["value"] == "db.internal"
    assert next(field for field in shared["fields"] if field["label"] == "密码")["value"] is None
    assert shared["can_edit"] is False
    assert bob.post(
        f"/api/entries/{entry_id}/reveal",
        json={"field_id": password_field["id"]},
        headers=bob_headers,
    ).status_code == 403
    assert bob.patch(
        f"/api/entries/{entry_id}",
        json={"title": "changed"},
        headers=bob_headers,
    ).status_code == 403

    reveal = alice.post(
        f"/api/entries/{entry_id}/reveal",
        json={"field_id": password_field["id"], "purpose": "copy"},
        headers=alice_headers,
    )
    assert reveal.status_code == 200
    assert reveal.json()["value"] == "SuperSecret!"
    audit_rows = alice.get(f"/api/projects/{project_id}/audit-logs").json()["items"]
    assert any(row["action"] == "reveal_copy" and row["detail"] == "密码" for row in audit_rows)
    assert "SuperSecret!" not in str(audit_rows)

    search = bob.post(
        "/api/entries/search",
        json={"q": "db.internal"},
        headers=bob_headers,
    )
    assert search.status_code == 200, search.text
    assert search.json()["total"] == 1
    secret_search = bob.post(
        "/api/entries/search",
        json={"q": "SuperSecret!"},
        headers=bob_headers,
    )
    assert secret_search.status_code == 200, secret_search.text
    assert secret_search.json()["total"] == 0
    assert bob.post(
        "/api/entries/summary/search",
        json={"q": "db.internal", "group_by": "project"},
        headers=bob_headers,
    ).json()[0]["count"] == 1

    assert admin.delete(f"/api/categories/{category_id}", headers=admin_headers).status_code == 409
    alice.delete(f"/api/projects/{project_id}/shares/{share_response.json()['user_id']}", headers=alice_headers)
    assert bob.get(f"/api/entries/{entry_id}").status_code == 404
    assert bob.get("/api/entries").json()["total"] == 0


def test_project_tree_and_descendant_access(environment):
    admin, _ = environment
    admin_headers = login(admin, "admin", "AdminPassword!2026")
    register(admin, "alice")
    register(admin, "bob")
    enable(admin, admin_headers, "alice")
    enable(admin, admin_headers, "bob")
    category = admin.post(
        "/api/categories", json={"name": "需求文档"}, headers=admin_headers
    ).json()
    alice, alice_headers = make_client(admin.app, "alice")
    bob, bob_headers = make_client(admin.app, "bob")

    root = alice.post("/api/projects", json={"name": "订单系统"}, headers=alice_headers).json()
    child = alice.post(
        "/api/projects", json={"name": "支付模块", "parent_id": root["id"]}, headers=alice_headers
    ).json()
    grandchild = alice.post(
        "/api/projects", json={"name": "退款", "parent_id": child["id"]}, headers=alice_headers
    ).json()
    assert child["parent_id"] == root["id"]
    assert grandchild["parent_id"] == child["id"]
    assert len(alice.get("/api/projects").json()) == 3
    assert bob.get("/api/projects").json() == []

    entry = alice.post(
        "/api/entries",
        json={"project_id": grandchild["id"], "category_id": category["id"], "title": "退款需求"},
        headers=alice_headers,
    )
    assert entry.status_code == 201, entry.text
    assert alice.get(f"/api/entries?project_id={root['id']}").json()["total"] == 0
    assert alice.get(f"/api/entries?project_id={root['id']}&include_descendants=true").json()["total"] == 1
    assert alice.post(
        "/api/entries/search",
        json={"project_id": root["id"], "include_descendants": True, "q": "退款"},
        headers=alice_headers,
    ).json()["total"] == 1

    assert alice.patch(
        f"/api/projects/{root['id']}", json={"parent_id": grandchild["id"]}, headers=alice_headers
    ).status_code == 422
    assert alice.patch(
        f"/api/projects/{child['id']}", json={"parent_id": child["id"]}, headers=alice_headers
    ).status_code == 422
    assert alice.delete(f"/api/projects/{root['id']}", headers=alice_headers).status_code == 409
    assert bob.post(
        "/api/projects", json={"name": "非法子项目", "parent_id": root["id"]}, headers=bob_headers
    ).status_code == 404
    assert bob.get(f"/api/entries?project_id={root['id']}&include_descendants=true").status_code == 404

    alice.post(
        f"/api/projects/{root['id']}/shares", json={"username": "bob"}, headers=alice_headers
    )
    assert len(bob.get("/api/projects").json()) == 1
    assert bob.get(f"/api/entries?project_id={root['id']}&include_descendants=true").json()["total"] == 0
    alice.post(
        f"/api/projects/{grandchild['id']}/shares", json={"username": "bob"}, headers=alice_headers
    )
    assert bob.get(f"/api/entries?project_id={root['id']}&include_descendants=true").json()["total"] == 1
    assert bob.patch(
        f"/api/projects/{grandchild['id']}", json={"parent_id": None}, headers=bob_headers
    ).status_code == 403
    moved = alice.patch(
        f"/api/projects/{grandchild['id']}", json={"parent_id": None}, headers=alice_headers
    )
    assert moved.status_code == 200
    assert moved.json()["parent_id"] is None
    assert alice.get(f"/api/entries?project_id={root['id']}&include_descendants=true").json()["total"] == 0


def test_default_categories_are_seeded_once(environment):
    admin, settings = environment
    seeded_settings = replace(settings, seed_default_categories=True)
    initialize_database(admin.app.state.engine, seeded_settings)
    initialize_database(admin.app.state.engine, seeded_settings)
    with Session(admin.app.state.engine) as db:
        categories = db.exec(select(Category)).all()
        assert {row.name for row in categories} == {
            "需求文档", "测试文档", "接口文档", "数据库", "服务器", "日志", "Nacos"
        }
        assert db.exec(select(CategoryField)).all() == []


def test_recovery_codes_are_single_use_and_admin_cannot_reset(environment):
    admin, _ = environment
    admin_headers = login(admin, "admin", "AdminPassword!2026")
    register(admin, "carol")
    enable(admin, admin_headers, "carol")
    carol, carol_headers = make_client(admin.app, "carol")
    codes_response = carol.post("/api/auth/recovery-codes", headers=carol_headers)
    assert codes_response.status_code == 200
    code = codes_response.json()["codes"][0]
    carol_user = next(row for row in admin.get("/api/users").json() if row["username"] == "carol")
    assert admin.patch(
        f"/api/users/{carol_user['id']}",
        json={"password": "AdminChosenPassword!"},
        headers=admin_headers,
    ).status_code == 422
    assert carol.get("/api/auth/me").status_code == 200
    assert admin.post(
        "/api/auth/recover",
        json={"username": "carol", "recovery_code": "wrong", "new_password": "AnotherPassword!2026"},
    ).status_code == 400
    recovered = carol.post(
        "/api/auth/recover",
        json={"username": "carol", "recovery_code": code, "new_password": "AnotherPassword!2026"},
    )
    assert recovered.status_code == 200
    assert carol.get("/api/auth/me").status_code == 401
    assert carol.post(
        "/api/auth/recover",
        json={"username": "carol", "recovery_code": code, "new_password": "ThirdPassword!2026"},
    ).status_code == 400
    assert login(carol, "carol", "AnotherPassword!2026")


def test_admin_resets_user_password(environment):
    admin, _ = environment
    admin_headers = login(admin, "admin", "AdminPassword!2026")
    register(admin, "dave")
    enable(admin, admin_headers, "dave")
    dave, dave_headers = make_client(admin.app, "dave")
    dave_user = next(row for row in admin.get("/api/users").json() if row["username"] == "dave")
    assert dave.post(
        f"/api/users/{dave_user['id']}/reset-password",
        headers=dave_headers,
    ).status_code == 403
    reset = admin.post(f"/api/users/{dave_user['id']}/reset-password", headers=admin_headers)
    assert reset.status_code == 200, reset.text
    assert reset.json()["password"] == "123456"
    assert dave.get("/api/auth/me").status_code == 401
    assert login(dave, "dave", "123456")
    admin_user = next(row for row in admin.get("/api/users").json() if row["username"] == "admin")
    assert admin.post(
        f"/api/users/{admin_user['id']}/reset-password",
        headers=admin_headers,
    ).status_code == 409
    assert admin.post("/api/users/9999/reset-password", headers=admin_headers).status_code == 404


def test_environment_options_and_entry_validation(environment):
    admin, _ = environment
    assert admin.get("/api/environments").status_code == 401
    headers = login(admin, "admin", "AdminPassword!2026")
    options = admin.get("/api/environments").json()
    assert options == [
        {"value": "DEV", "label": "DEV 开发"},
        {"value": "TEST", "label": "TEST 测试"},
        {"value": "SIT", "label": "SIT 集成"},
        {"value": "UAT", "label": "UAT 验收"},
        {"value": "PRE", "label": "PRE 灰度/预发"},
        {"value": "PROD", "label": "PROD 生产"},
    ]
    category = admin.post("/api/categories", json={"name": "接口文档"}, headers=headers).json()
    project = admin.post("/api/projects", json={"name": "用户中心"}, headers=headers).json()
    base = {"project_id": project["id"], "category_id": category["id"], "title": "文档"}
    created_ids = {}
    for option in options:
        response = admin.post(
            "/api/entries",
            json={**base, "environment": option["value"].lower()},
            headers=headers,
        )
        assert response.status_code == 201, response.text
        assert response.json()["environment"] == option["value"]
        created_ids[option["value"]] = response.json()["id"]
    assert admin.post(
        "/api/entries", json={**base, "environment": "STAGING"}, headers=headers
    ).status_code == 422
    assert admin.post(
        "/api/entries", json={**base, "environment": None}, headers=headers
    ).status_code == 201
    filtered = admin.get("/api/entries?environment=TEST").json()
    assert filtered["total"] == 1
    assert admin.patch(
        f"/api/entries/{created_ids['TEST']}",
        json={"environment": "STAGING"},
        headers=headers,
    ).status_code == 422
    updated = admin.patch(
        f"/api/entries/{created_ids['TEST']}",
        json={"environment": "pre"},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["environment"] == "PRE"
    renamed = admin.patch(
        f"/api/entries/{created_ids['TEST']}",
        json={"title": "新版文档"},
        headers=headers,
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["environment"] == "PRE"


def test_auth_attempts_are_limited_and_expire(environment):
    admin, _ = environment
    clock = [1000.0]
    admin.app.state.auth_attempts.clock = lambda: clock[0]
    bad_login = {"username": "admin", "password": "wrong"}
    for _ in range(5):
        assert admin.post("/api/auth/login", json=bad_login).status_code == 401
    locked = admin.post(
        "/api/auth/login", json={"username": "admin", "password": "AdminPassword!2026"}
    )
    assert locked.status_code == 429
    assert locked.headers["Retry-After"] == "900"
    clock[0] += 900
    headers = login(admin, "admin", "AdminPassword!2026")
    code = admin.post("/api/auth/recovery-codes", headers=headers).json()["codes"][0]
    for _ in range(5):
        assert admin.post(
            "/api/auth/recover",
            json={"username": "admin", "recovery_code": "wrong", "new_password": "NewPassword!2026"},
        ).status_code == 400
    locked_recovery = admin.post(
        "/api/auth/recover",
        json={"username": "admin", "recovery_code": code, "new_password": "NewPassword!2026"},
    )
    assert locked_recovery.status_code == 429
    clock[0] += 900
    recovered = admin.post(
        "/api/auth/recover",
        json={"username": "admin", "recovery_code": code, "new_password": "NewPassword!2026"},
    )
    assert recovered.status_code == 200
    headers = login(admin, "admin", "NewPassword!2026")
    for _ in range(5):
        assert admin.post(
            "/api/auth/change-password",
            json={"current_password": "wrong", "new_password": "FinalPassword!2026"},
            headers=headers,
        ).status_code == 400
    locked_change = admin.post(
        "/api/auth/change-password",
        json={"current_password": "NewPassword!2026", "new_password": "FinalPassword!2026"},
        headers=headers,
    )
    assert locked_change.status_code == 429
    clock[0] += 900
    changed = admin.post(
        "/api/auth/change-password",
        json={"current_password": "NewPassword!2026", "new_password": "FinalPassword!2026"},
        headers=headers,
    )
    assert changed.status_code == 200
    assert login(admin, "admin", "FinalPassword!2026")


def test_unknown_usernames_have_separate_login_limits(environment):
    admin, _ = environment
    clock = [1000.0]
    admin.app.state.auth_attempts.clock = lambda: clock[0]
    for _ in range(5):
        assert admin.post(
            "/api/auth/login", json={"username": "ghost", "password": "wrong"}
        ).status_code == 401
    assert admin.post(
        "/api/auth/login", json={"username": "ghost", "password": "wrong"}
    ).status_code == 429
    assert admin.post(
        "/api/auth/login", json={"username": "  GHOST  ", "password": "wrong"}
    ).status_code == 429
    assert admin.post(
        "/api/auth/login", json={"username": "phantom", "password": "wrong"}
    ).status_code == 401
    assert admin.post(
        "/api/auth/login", json={"username": "admin", "password": "AdminPassword!2026"}
    ).status_code == 200


def test_category_with_fields_can_be_deleted(environment):
    admin, _ = environment
    headers = login(admin, "admin", "AdminPassword!2026")
    created = admin.post("/api/categories", json={"name": "待删除分类"}, headers=headers)
    assert created.status_code == 201, created.text
    category_id = created.json()["id"]
    with Session(admin.app.state.engine) as db:
        db.add(
            CategoryField(
                category_id=category_id,
                field_key="host",
                field_label="主机",
                field_type="text",
            )
        )
        db.commit()
    deleted = admin.delete(f"/api/categories/{category_id}", headers=headers)
    assert deleted.status_code == 200, deleted.text
    assert all(row["id"] != category_id for row in admin.get("/api/categories").json())


def test_corrupt_secret_has_explicit_placeholder_without_copy_value(environment, caplog):
    admin, settings = environment
    headers = login(admin, "admin", "AdminPassword!2026")
    category = admin.post(
        "/api/categories",
        json={"name": "密钥"},
        headers=headers,
    ).json()
    project = admin.post("/api/projects", json={"name": "安全测试"}, headers=headers).json()
    entry = admin.post(
        "/api/entries",
        json={"project_id": project["id"], "category_id": category["id"], "title": "测试", "fields": [{"label": "令牌", "field_type": "password", "is_sensitive": True, "value": "ActualSecret"}]},
        headers=headers,
    ).json()
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute(
            "UPDATE entry SET fields_json = ? WHERE id = ?",
            (json.dumps([{**entry["fields"][0], "value": "broken-ciphertext"}]), entry["id"]),
        )
    assert admin.get(f"/api/entries/{entry['id']}").json()["fields"][0]["value"] is None
    with caplog.at_level("ERROR"):
        for purpose in ("view", "copy"):
            response = admin.post(
                f"/api/entries/{entry['id']}/reveal",
                json={"field_id": entry["fields"][0]["id"], "purpose": purpose},
                headers=headers,
            )
            assert response.status_code == 200
            assert response.json() == {
                "field_id": entry["fields"][0]["id"], "value": None, "unavailable": True, "placeholder": "无法解密"
            }
    assert "Cannot decrypt secret" in caplog.text
    assert "ActualSecret" not in caplog.text


def test_entry_fields_are_independent_repeatable_and_preserve_hidden_values(environment):
    admin, settings = environment
    headers = login(admin, "admin", "AdminPassword!2026")
    category = admin.post("/api/categories", json={"name": "需求文档"}, headers=headers).json()
    project = admin.post("/api/projects", json={"name": "资料库"}, headers=headers).json()
    created = admin.post("/api/entries", headers=headers, json={
        "project_id": project["id"], "category_id": category["id"], "title": "需求地址",
        "fields": [
            {"label": "账号", "value": "first.user"},
            {"label": "账号", "value": "second.user"},
            {"label": "密码", "field_type": "password", "is_sensitive": True, "value": "PrivateValue!"},
        ],
    })
    assert created.status_code == 201, created.text
    entry = created.json()
    assert [field["value"] for field in entry["fields"]] == ["first.user", "second.user", None]
    assert admin.post("/api/entries/search", headers=headers, json={"q": "second.user"}).json()["total"] == 1
    assert admin.post("/api/entries/search", headers=headers, json={"q": "PrivateValue!"}).json()["total"] == 0
    secret = entry["fields"][2]
    changed = admin.patch(f"/api/entries/{entry['id']}", headers=headers, json={
        "fields": [
            {"id": field["id"], "label": field["label"], "field_type": field["field_type"],
             "is_sensitive": field["is_sensitive"], "value": field["value"],
             "keep_existing": field["id"] == secret["id"]}
            for field in entry["fields"]
        ],
    })
    assert changed.status_code == 200, changed.text
    assert admin.post(f"/api/entries/{entry['id']}/reveal", headers=headers,
                      json={"field_id": secret["id"]}).json()["value"] == "PrivateValue!"
    assert admin.put(f"/api/categories/{category['id']}", headers=headers,
                     json={"name": "设计文档", "sort_order": 8}).status_code == 200
    assert admin.get(f"/api/entries/{entry['id']}").json()["fields"][2]["label"] == "密码"
    with sqlite3.connect(settings.database_path) as connection:
        stored = connection.execute("SELECT fields_json FROM entry WHERE id = ?", (entry["id"],)).fetchone()[0]
    assert "PrivateValue!" not in stored
    visible = admin.post("/api/entries", headers=headers, json={
        "project_id": project["id"], "category_id": category["id"], "title": "公开值",
        "fields": [{"label": "访问码", "field_type": "password", "is_sensitive": False, "value": "VisibleCode"}],
    })
    assert visible.status_code == 201, visible.text
    assert visible.json()["fields"][0]["value"] == "VisibleCode"


def test_document_and_spreadsheet_entries(environment):
    admin, _ = environment
    headers = login(admin, "admin", "AdminPassword!2026")
    category = admin.post("/api/categories", json={"name": "需求文档"}, headers=headers).json()
    project = admin.post("/api/projects", json={"name": "用户中心"}, headers=headers).json()
    base = {"project_id": project["id"], "category_id": category["id"], "title": "发布说明"}

    document = admin.post("/api/entries", headers=headers, json={**base, "kind": "document", "body": "<p>正文</p>"})
    assert document.status_code == 201, document.text
    document_id = document.json()["id"]
    assert document.json()["body"] == "<p>正文</p>"
    assert admin.post("/api/entries", headers=headers, json={**base, "kind": "document", "body": " "}).status_code == 422
    assert admin.post("/api/entries", headers=headers, json={
        **base, "kind": "document", "body": "<p>正文</p>", "fields": [{"label": "账号"}]
    }).status_code == 422
    updated = admin.patch(f"/api/entries/{document_id}", headers=headers, json={"body": "<p>更新正文</p>"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["body"] == "<p>更新正文</p>"
    detail = admin.get(f"/api/entries/{document_id}").json()
    assert detail["kind"] == "document"
    assert detail["body"] == "<p>更新正文</p>"
    row = next(item for item in admin.get("/api/entries").json()["items"] if item["id"] == document_id)
    assert row["kind"] == "document"
    assert row["body"] is None
    assert row["has_body"] is True

    sheet_rows = json.dumps({"rows": [["项目", "金额"], ["服务器", "1000"]]}, ensure_ascii=False)
    sheet = admin.post("/api/entries", headers=headers, json={
        **base, "kind": "spreadsheet", "title": "预算表", "sheet_json": sheet_rows,
    })
    assert sheet.status_code == 201, sheet.text
    assert json.loads(sheet.json()["sheet_json"])["rows"][1] == ["服务器", "1000"]
    assert admin.post("/api/entries", headers=headers, json={
        **base, "kind": "spreadsheet", "sheet_json": json.dumps({"rows": []}),
    }).status_code == 422
    assert admin.post("/api/entries", headers=headers, json={
        **base, "kind": "spreadsheet", "title": "坏表格", "sheet_json": "{bad",
    }).status_code == 422
    assert admin.patch(f"/api/entries/{sheet.json()['id']}", headers=headers, json={"body": "<p>x</p>"}).status_code == 422
    assert admin.post("/api/entries", headers=headers, json={**base, "kind": "unknown"}).status_code == 422
    assert admin.post("/api/entries/search", headers=headers, json={"q": "更新正文"}).json()["total"] == 1
    assert admin.post("/api/entries/search", headers=headers, json={"q": "服务器"}).json()["total"] == 1


def test_system_roles_menus_and_project_boundary(environment):
    admin, _ = environment
    headers = login(admin, "admin", "AdminPassword!2026")
    role = admin.post("/api/roles", headers=headers, json={
        "key": "operator", "name": "系统操作员", "permissions": ["manage_menus", "view_logs"]
    })
    assert role.status_code == 201, role.text
    created = admin.post("/api/users", headers=headers, json={
        "username": "operator", "display_name": "操作员", "password": "OperatorPassword!2026", "role": "operator"
    })
    assert created.status_code == 201, created.text
    operator = TestClient(admin.app)
    operator_headers = login(operator, "operator", "OperatorPassword!2026")
    assert operator.get("/api/users").status_code == 403
    assert operator.get("/api/admin/audit-logs").status_code == 200
    assert operator.get("/api/projects").status_code == 403
    assert operator.get("/api/entries").status_code == 403
    menu = operator.post("/api/menus", headers=operator_headers, json={
        "key": "workspace_alt", "label": "我的资料", "path": "/workspace", "sort_order": 2
    })
    assert menu.status_code == 201, menu.text
    assert any(row["key"] == "workspace_alt" for row in operator.get("/api/menus").json())
    assert operator.delete("/api/menus/workspace_alt", headers=operator_headers).status_code == 200
    assert admin.delete("/api/roles/operator", headers=headers).status_code == 409


def test_existing_template_values_migrate_without_losing_secret(environment):
    admin, settings = environment
    headers = login(admin, "admin", "AdminPassword!2026")
    category = admin.post("/api/categories", json={"name": "数据库"}, headers=headers).json()
    project = admin.post("/api/projects", json={"name": "旧项目"}, headers=headers).json()
    entry = admin.post("/api/entries", json={
        "project_id": project["id"], "category_id": category["id"], "title": "旧库"
    }, headers=headers).json()
    token = Fernet(settings.fernet_key.encode()).encrypt(b"LegacySecret!").decode()
    with Session(admin.app.state.engine) as db:
        db.add(CategoryField(category_id=category["id"], field_key="password", field_label="密码",
                             field_type="password", is_sensitive=True))
        db.commit()
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute("UPDATE entry SET fields_json = ? WHERE id = ?",
                           (json.dumps({"password": token}), entry["id"]))
    initialize_database(admin.app.state.engine, settings)
    migrated = admin.get(f"/api/entries/{entry['id']}").json()
    assert migrated["fields"][0]["label"] == "密码"
    assert migrated["fields"][0]["value"] is None
    assert admin.post(f"/api/entries/{entry['id']}/reveal", headers=headers,
                      json={"field_id": migrated["fields"][0]["id"]}).json()["value"] == "LegacySecret!"
    initialize_database(admin.app.state.engine, settings)
    assert admin.get(f"/api/entries/{entry['id']}").json()["fields"][0]["id"] == migrated["fields"][0]["id"]


def test_admin_tables_archive_user_and_keep_project_boundary(environment):
    admin, _ = environment
    headers = login(admin, "admin", "AdminPassword!2026")
    created = admin.post("/api/users", headers=headers, json={
        "username": "archivable", "display_name": "可删除成员",
        "password": "MemberPassword!2026", "role": "member",
    })
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]
    archived = admin.delete(f"/api/users/{user_id}", headers=headers)
    assert archived.status_code == 200, archived.text
    assert all(row["id"] != user_id for row in admin.get("/api/users").json())
    assert admin.patch(f"/api/users/{user_id}", headers=headers, json={"is_active": True}).status_code == 404
    assert admin.post("/api/auth/login", json={"username": "archivable", "password": "MemberPassword!2026"}).status_code == 403

    owner = admin.post("/api/users", headers=headers, json={
        "username": "owner", "display_name": "项目所有者",
        "password": "MemberPassword!2026", "role": "member",
    }).json()
    owner_client, owner_headers = make_client(admin.app, "owner")
    assert owner_client.post("/api/projects", headers=owner_headers, json={"name": "保留项目"}).status_code == 201
    assert admin.delete(f"/api/users/{owner['id']}", headers=headers).status_code == 409
    assert owner_client.get("/api/projects").json()[0]["name"] == "保留项目"

    menu = admin.post("/api/menus", headers=headers, json={"key": "extra_workspace", "label": "资料入口", "path": "/workspace"}).json()
    patched = admin.patch(f"/api/menus/{menu['key']}", headers=headers, json={"path": "/users"})
    assert patched.status_code == 200, patched.text
    assert patched.json()["path"] == "/users"
    assert admin.patch("/api/menus/workspace", headers=headers, json={"path": "/users"}).status_code == 409
    assert admin.patch(f"/api/menus/{menu['key']}", headers=headers, json={"path": None}).status_code == 422
    logs = admin.get("/api/admin/audit-logs", params={"q": "archive", "page_size": 10}).json()
    assert any(row["target_id"] == user_id for row in logs["items"])


def test_table_field_and_sensitive_visibility_change(environment):
    admin, settings = environment
    headers = login(admin, "admin", "AdminPassword!2026")
    category = admin.post("/api/categories", headers=headers, json={"name": "文档"}).json()
    project = admin.post("/api/projects", headers=headers, json={"name": "表格项目"}).json()
    created = admin.post("/api/entries", headers=headers, json={
        "project_id": project["id"], "category_id": category["id"], "title": "访问清单",
        "fields": [
            {"label": "清单", "field_type": "table", "value": json.dumps({"rows": [["地址", "账号"], ["https://example.test", "dev"]]})},
            {"label": "密码", "field_type": "password", "is_sensitive": True, "value": "keep-me"},
        ],
    })
    assert created.status_code == 201, created.text
    entry = created.json()
    table = next(field for field in entry["fields"] if field["field_type"] == "table")
    assert json.loads(table["value"])["rows"][1][1] == "dev"
    secret = next(field for field in entry["fields"] if field["is_sensitive"])
    revealed = admin.post(f"/api/entries/{entry['id']}/reveal", headers=headers, json={"field_id": secret["id"]})
    assert revealed.json()["value"] == "keep-me"
    changed = admin.patch(f"/api/entries/{entry['id']}", headers=headers, json={"fields": [
        {"id": table["id"], "label": "清单", "field_type": "table", "value": table["value"]},
        {"id": secret["id"], "label": "密码", "field_type": "password", "is_sensitive": False, "value": revealed.json()["value"]},
    ]})
    assert changed.status_code == 200, changed.text
    assert next(field for field in changed.json()["fields"] if field["id"] == secret["id"])["value"] == "keep-me"
    with sqlite3.connect(settings.database_path) as connection:
        stored = connection.execute("SELECT fields_json FROM entry WHERE id = ?", (entry["id"],)).fetchone()[0]
    assert json.loads(next(field["value"] for field in json.loads(stored) if field["field_type"] == "table"))["rows"][0] == ["地址", "账号"]
    invalid = admin.post("/api/entries", headers=headers, json={
        "project_id": project["id"], "category_id": category["id"], "title": "无效表格",
        "fields": [{"label": "清单", "field_type": "table", "value": '{"rows":[["a"],["b","c"]]}'}],
    })
    assert invalid.status_code == 422


def test_workspace_permission_role_status_and_named_audit(environment):
    admin, _ = environment
    headers = login(admin, "admin", "AdminPassword!2026")
    role = admin.post("/api/roles", headers=headers, json={
        "key": "viewer", "name": "项目查看", "permissions": ["view_workspace"],
    })
    assert role.status_code == 201, role.text
    member = admin.post("/api/users", headers=headers, json={
        "username": "viewer1", "display_name": "查看成员", "password": "abc123", "role": "viewer",
    })
    assert member.status_code == 201, member.text
    assert admin.post("/api/users", headers=headers, json={
        "username": "five_chars", "display_name": "短密码", "password": "abc12", "role": "viewer",
    }).status_code == 422
    viewer = TestClient(admin.app)
    viewer_headers = login(viewer, "viewer1", "abc123")
    own = viewer.post("/api/projects", headers=viewer_headers, json={"name": "成员私有项目"})
    assert own.status_code == 201, own.text
    assert admin.patch("/api/roles/viewer/status", headers=headers, json={"is_enabled": False}).status_code == 200
    assert viewer.get("/api/projects").status_code == 403
    assert admin.patch(f"/api/users/{member.json()['id']}", headers=headers, json={"display_name": "查看成员"}).status_code == 200
    assert admin.patch("/api/roles/viewer/status", headers=headers, json={"is_enabled": True}).status_code == 200
    assert viewer.get("/api/projects").status_code == 200
    updated = admin.put("/api/roles/viewer", headers=headers, json={"key": "viewer", "name": "项目查看", "permissions": []})
    assert updated.status_code == 200, updated.text
    assert viewer.get("/api/projects").status_code == 403
    assert viewer.get("/api/entries").status_code == 403
    admin.patch(f"/api/users/{member.json()['id']}", headers=headers, json={"role": "member"})
    assert admin.patch("/api/roles/viewer/status", headers=headers, json={"is_enabled": False}).status_code == 200
    assert admin.post("/api/users", headers=headers, json={
        "username": "viewer2", "display_name": "新成员", "password": "abc12", "role": "viewer",
    }).status_code == 422
    changed_password = viewer.post("/api/auth/change-password", headers=viewer_headers, json={
        "current_password": "abc123", "new_password": "newpass",
    })
    assert changed_password.status_code == 200, changed_password.text

    project = admin.post("/api/projects", headers=headers, json={"name": "管理员自有项目"}).json()
    admin.patch(f"/api/projects/{project['id']}", headers=headers, json={"description": "已更新"})
    category = admin.post("/api/categories", headers=headers, json={"name": "资料"}).json()
    entry = admin.post("/api/entries", headers=headers, json={
        "project_id": project["id"], "category_id": category["id"], "title": "需求地址",
    }).json()
    admin.patch(f"/api/entries/{entry['id']}", headers=headers, json={"content": "新版"})
    admin.post("/api/auth/recovery-codes", headers=headers)
    logs = admin.get("/api/admin/audit-logs", params={"page_size": 200}).json()["items"]
    assert any(row["target_type"] == "project" and row["action"] == "update" and row["object_name"] == "管理员自有项目" for row in logs)
    assert any(row["target_type"] == "entry" and row["action"] == "update" and row["object_name"] == "需求地址" for row in logs)
    assert any(row["target_type"] == "auth" and row["action"] == "rotate_recovery_codes" and row["object_name"] == "系统管理员" for row in logs)
    assert any(row["target_type"] == "auth" and row["action"] == "change_password" and row["object_name"] == "查看成员" for row in logs)
    assert all("成员私有项目" not in str(row) for row in logs)


def test_workspace_permission_migration_runs_once(environment):
    admin, settings = environment
    with Session(admin.app.state.engine) as db:
        role = db.get(Role, "member")
        role.permissions_json = "[]"
        db.add(role)
        db.delete(db.get(MigrationMarker, "workspace_permission_v1"))
        db.commit()
    initialize_database(admin.app.state.engine, settings)
    with Session(admin.app.state.engine) as db:
        assert "view_workspace" in json.loads(db.get(Role, "member").permissions_json)
        role = db.get(Role, "member")
        role.permissions_json = "[]"
        db.add(role)
        db.commit()
    initialize_database(admin.app.state.engine, settings)
    with Session(admin.app.state.engine) as db:
        assert json.loads(db.get(Role, "member").permissions_json) == []
