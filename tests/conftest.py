import os
import re


def pytest_configure(config):
    # Importing the Flask module initializes its configured database; keep tests isolated.
    test_db_dir = config.rootpath / ".pytest_cache"
    test_db_dir.mkdir(exist_ok=True)
    os.environ["APAAR_DB_PATH"] = str(test_db_dir / "apaar-test.db")
    os.environ["DEMO_ADMIN_PASSWORD"] = "ChangeMe123!"
    os.environ["SECRET_KEY"] = "pytest-only-secret"


def login_client(client, username="admin", password="ChangeMe123!"):
    page = client.get("/login")
    match = re.search(rb'name="csrf_token" value="([^"]+)"', page.data)
    assert match, "Login page must provide its CSRF token"
    client.environ_base.pop("HTTP_X_CSRF_TOKEN", None)
    response = client.post("/login", data={
        "username": username, "password": password,
        "csrf_token": match.group(1).decode(),
    })
    with client.session_transaction() as user_session:
        client.environ_base["HTTP_X_CSRF_TOKEN"] = user_session["_csrf_token"]
    return response
