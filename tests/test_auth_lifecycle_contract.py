from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_auth_lifecycle_routes_and_tables_are_present():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    for required in (
        'CREATE TABLE IF NOT EXISTS auth_challenges',
        '@app.route("/verify-otp"',
        '@app.route("/forgot-password"',
        '@app.route("/reset-password/<token>"',
        '@app.route("/verify-email"',
        '@app.route("/account/security"',
        'session_version=session_version+1',
    ):
        assert required in source


def test_auth_help_pages_exist_and_are_linked():
    for template in (
        "verify_otp.html", "forgot_password.html", "reset_password.html",
        "account_security.html", "help.html",
    ):
        assert (ROOT / "templates" / template).is_file()
    base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    assert "help_page" in base
    login = (ROOT / "templates" / "login.html").read_text(encoding="utf-8")
    assert "forgot_password" in login


def test_auth_configuration_example_has_no_real_secret():
    example = (ROOT / ".env.auth.example").read_text(encoding="utf-8")
    assert "SMTP_HOST=" in example
    assert "SECRET_KEY=replace-with" in example
    assert "SMTP_PASSWORD=your-smtp-password" in example
