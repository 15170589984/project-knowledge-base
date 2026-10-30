"""Browser regression for entry editing and shared-project permissions."""

import http.cookiejar
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from cryptography.fernet import Fernet
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for(url, process):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Server exited with status {process.returncode}: {url}")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.2)
    raise RuntimeError(f"Server did not become ready: {url}")


class ApiClient:
    def __init__(self, base_url):
        self.base_url = base_url
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        self.csrf_token = None

    def request(self, method, path, body=None):
        headers = {}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if self.csrf_token and method not in ("GET", "HEAD"):
            headers["X-CSRF-Token"] = self.csrf_token
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
            method=method,
        )
        with self.opener.open(request, timeout=5) as response:
            return json.load(response)

    def login(self, username, password):
        result = self.request("POST", "/api/auth/login", {"username": username, "password": password})
        self.csrf_token = result["csrf_token"]


class WorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="kb-ui-test-", ignore_cleanup_errors=True)
        cls.processes = []
        try:
            cls.database_path = Path(cls.temp_dir.name) / "knowledge.db"
            backend_port = free_port()
            frontend_port = free_port()
            cls.base_url = f"http://127.0.0.1:{frontend_port}"
            api_url = f"http://127.0.0.1:{backend_port}"
            admin_password = "AdminPassword!2026"
            backend_env = os.environ.copy()
            backend_env.update({
                "DATABASE_PATH": str(cls.database_path),
                "FERNET_KEY": Fernet.generate_key().decode(),
                "SESSION_SECRET": "ui-test-" + os.urandom(32).hex(),
                "INITIAL_ADMIN_USERNAME": "admin",
                "INITIAL_ADMIN_PASSWORD": admin_password,
                "COOKIE_SECURE": "false",
            })
            backend_python = os.environ.get("KB_BACKEND_PYTHON", sys.executable)
            cls.processes.append(subprocess.Popen(
                [backend_python, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(backend_port)],
                cwd=BACKEND, env=backend_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            ))
            wait_for(api_url + "/api/health", cls.processes[-1])

            frontend_env = os.environ.copy()
            frontend_env["VITE_API_PROXY"] = api_url
            vite = FRONTEND / "node_modules" / "vite" / "bin" / "vite.js"
            if not vite.exists():
                raise RuntimeError("Run npm install in frontend before the UI workflow test")
            subprocess.run(
                ["node", str(vite), "build", "--configLoader", "runner"],
                cwd=FRONTEND, env=frontend_env, check=True, timeout=30,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            )
            cls.processes.append(subprocess.Popen(
                ["node", str(vite), "preview", "--configLoader", "runner", "--host", "127.0.0.1", "--port", str(frontend_port), "--strictPort"],
                cwd=FRONTEND, env=frontend_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            ))
            wait_for(cls.base_url + "/login", cls.processes[-1])

            admin = ApiClient(api_url)
            admin.login("admin", admin_password)
            for username in ("alice", "bob"):
                admin.request("POST", "/api/auth/register", {
                    "username": username, "display_name": username.title(), "password": "MemberPassword!2026",
                })
            for user in admin.request("GET", "/api/users"):
                if user["username"] in ("alice", "bob"):
                    admin.request("PATCH", f"/api/users/{user['id']}", {"is_active": True})
            cls.category = admin.request("POST", "/api/categories", {"name": "数据库"})
            cls.alice_api = ApiClient(api_url)
            cls.alice_api.login("alice", "MemberPassword!2026")
            cls.project = cls.alice_api.request("POST", "/api/projects", {"name": "用户中心"})
        except Exception:
            cls.stop_services()
            raise

    @classmethod
    def stop_services(cls):
        for process in reversed(getattr(cls, "processes", [])):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        if hasattr(cls, "temp_dir"):
            cls.temp_dir.cleanup()

    @classmethod
    def tearDownClass(cls):
        cls.stop_services()

    def test_entry_form_reveal_and_shared_read_only_view(self):
        with sync_playwright() as playwright:
            channel = os.environ.get("KB_BROWSER_CHANNEL", "chrome")
            browser = playwright.chromium.launch(headless=True, **({"channel": channel} if channel else {}))
            try:
                alice = browser.new_context()
                page = alice.new_page()
                page_errors = []
                network_events = []
                page.on("pageerror", lambda error: page_errors.append(str(error)))
                page.on("response", lambda response: network_events.append((response.status, response.url)) if "/api/" in response.url else None)
                page.on("requestfailed", lambda request: network_events.append(("failed", request.url)))
                page.goto(self.base_url + "/login")
                page.get_by_placeholder("请输入用户名").fill("alice")
                page.get_by_placeholder("请输入密码").fill("MemberPassword!2026")
                page.get_by_role("button", name="登录").click()
                page.locator(".filter-bar").get_by_role("button", name="新建条目").click()
                page.get_by_placeholder("例如：生产数据库").fill("TEST 数据库")
                page.locator(".entry-modal .n-select").nth(2).click()
                page.get_by_text("TEST 测试", exact=True).click()
                page.get_by_role("button", name="+ 账号").click()
                page.get_by_role("button", name="+ 密码").click()
                page.locator(".entry-field-editor").nth(0).locator(".n-input").nth(0).locator("input").fill("主机")
                page.locator(".entry-field-editor").nth(0).locator(".n-input").nth(1).locator("input").fill("db.internal")
                page.locator(".entry-field-editor").nth(1).locator(".n-input").nth(1).locator("input").fill("UiSecret!2026")
                page.get_by_role("button", name="保存", exact=True).click()
                page.get_by_text("条目已创建").wait_for()

                project_id = self.project["id"]
                category_id = self.category["id"]
                page.goto(self.base_url + f"/workspace?project_id={project_id}&category_id={category_id}")
                page.get_by_text("TEST 数据库", exact=True).wait_for()
                self.assertTrue(page.get_by_text("●●●●●●").count())
                page.get_by_text("TEST 数据库", exact=True).click()
                page.get_by_role("button", name="显示敏感值").click()
                page.get_by_text("UiSecret!2026", exact=True).wait_for()
                mutations = []
                page.on("request", lambda request: mutations.append(request.url) if request.method == "PATCH" and "/api/entries/" in request.url else None)
                page.locator(".n-drawer").get_by_role("button", name="编辑", exact=True).click()
                page.get_by_role("button", name="保存", exact=True).wait_for()
                self.assertEqual(mutations, [])
                page.get_by_role("button", name="取消", exact=True).click()

                page.goto(self.base_url + f"/workspace?project_id={project_id}")
                page.get_by_role("button", name="用户中心 操作").click()
                page.get_by_text("分享", exact=True).click()
                page.locator(".share-add .n-select").click()
                page.get_by_text("Bob · bob", exact=True).click()
                page.get_by_role("button", name="添加", exact=True).click()
                page.get_by_text("已授予只读权限").wait_for()
                self.assertEqual(
                    self.alice_api.request("GET", f"/api/projects/{project_id}/shares")[0]["username"],
                    "bob",
                )

                bob = browser.new_context()
                shared = bob.new_page()
                shared.goto(self.base_url + "/login")
                shared.get_by_placeholder("请输入用户名").fill("bob")
                shared.get_by_placeholder("请输入密码").fill("MemberPassword!2026")
                shared.get_by_role("button", name="登录").click()
                shared.wait_for_url("**/workspace**")
                shared.goto(self.base_url + f"/workspace?project_id={project_id}&category_id={category_id}")
                try:
                    shared.get_by_text("TEST 数据库", exact=True).click(timeout=10000)
                except Exception as exc:
                    raise AssertionError(f"Shared view did not show the entry: {shared.locator('body').inner_text()}") from exc
                self.assertTrue(shared.get_by_text("●●●●●●").count())
                self.assertEqual(shared.get_by_role("button", name="显示敏感值").count(), 0)
                self.assertEqual(shared.get_by_role("button", name="复制敏感值").count(), 0)
                self.assertEqual(shared.get_by_role("button", name="编辑", exact=True).count(), 0)

                entry = self.alice_api.request("GET", "/api/entries")["items"][0]
                with sqlite3.connect(self.database_path) as connection:
                    connection.execute(
                        "UPDATE entry SET fields_json = ? WHERE id = ?",
                        (json.dumps([{**field, "value": "broken-ciphertext"} if field["is_sensitive"] else {**field} for field in self.alice_api.request("GET", f"/api/entries/{entry['id']}")["fields"]]), entry["id"]),
                    )
                self.assertEqual(self.alice_api.request("GET", "/api/entries")["total"], 1)
                response = page.goto(self.base_url + f"/workspace?project_id={project_id}&category_id={category_id}")
                try:
                    page.get_by_text("TEST 数据库", exact=True).click(timeout=10000)
                except Exception as exc:
                    raise AssertionError(
                        f"Owner view missing: status={response.status if response else None}, "
                        f"url={page.url}, body={page.locator('body').inner_text()}, "
                        f"errors={page_errors}, network={network_events[-10:]}, "
                        f"auth_status={page.request.get(self.base_url + '/api/auth/me').status}, "
                        f"html={page.content()[:300]}"
                    ) from exc
                page.get_by_role("button", name="显示敏感值").click()
                page.get_by_text("无法解密", exact=True).wait_for()
                page.get_by_role("button", name="复制敏感值").click()
                self.assertEqual(page.get_by_text("已复制", exact=True).count(), 0)
                alice.close()
                bob.close()
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
