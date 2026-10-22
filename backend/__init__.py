from flask import Flask
from .db import init_db, close_db
from .routes import api

def register_backend(app: Flask) -> None:
    app.register_blueprint(api, url_prefix="/api/v1")
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()
