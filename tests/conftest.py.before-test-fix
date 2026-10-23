
import os
import re


def pytest_configure(config):
    # Keep automated tests isolated from the application's normal database.
    test_db_dir = config.rootpath / ".pytest_cache"
    test_db_dir.mkdir(exist_ok=True)
    os.environ["APAAR_DB_PATH"] = str(test_db_dir / "apaar-test.db")
    os.environ["DEMO_ADMIN_PASSWORD"] = "ChangeMe123!"
    os.environ["SECRET_KEY"] = "pytest-only-secret"


def login_client(client, username="admin", password="ChangeMe123!"):
    import app as app_module

    page = client.get("/login")
    match = re.search(rb'name="csrf_token" value="([^"]+)"', page.data)
    assert match, "Login page must provide its CSRF token"

    client.environ_base.pop("HTTP_X_CSRF_TOKEN", None)

    # Record existing test-only OTP codes so we can identify the new code.
    codes_before = dict(
        app_module.app.extensions.get("test_auth_codes", {})
    )

    response = client.post(
        "/login",
        data={
            "username": username,
            "password": password,
            "csrf_token": match.group(1).decode(),
        },
    )

    with client.session_transaction() as user_session:
        pending_otp = user_session.get("pending_otp_username")

    if pending_otp == username:
        codes_after = app_module.app.extensions.get("test_auth_codes", {})
        changed_codes = [
            code
            for key, code in codes_after.items()
            if codes_before.get(key) != code
        ]
        assert changed_codes, (
            "No test OTP captured; check that Flask TESTING mode is enabled"
        )

        otp_page = client.get("/verify-otp")
        otp_match = re.search(
            rb'name="csrf_token" value="([^"]+)"',
            otp_page.data,
        )
        assert otp_match, "OTP page must provide its CSRF token"

        response = client.post(
            "/verify-otp",
            data={
                "code": changed_codes[-1],
                "csrf_token": otp_match.group(1).decode(),
            },
        )

    # Failed logins are expected in tests that exercise throttling.
    # Only configure the API CSRF header after successful authentication.
    with client.session_transaction() as user_session:
        authenticated = user_session.get("username") == username
        csrf_token = user_session.get("_csrf_token")

    if authenticated:
        assert csrf_token, "Authenticated session must have a CSRF token"
        client.environ_base["HTTP_X_CSRF_TOKEN"] = csrf_token

    return response
