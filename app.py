"""Bazaar: entry point. Run with `python app.py`."""
import os
from pathlib import Path

from flask import Flask, request, send_from_directory

import api
import db
from helpers import error

BASE_DIR = Path(__file__).resolve().parent


def create_app(config=None):
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.config.update(
        DATABASE=os.environ.get("DATABASE", str(BASE_DIR / "bazaar.db")),
        # Set a long random SECRET_KEY in the environment for anything beyond local use.
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-secret-change-me-please-32b"),
        TOKEN_HOURS=12,
    )
    if config:
        app.config.update(config)

    app.teardown_appcontext(db.close_db)
    app.register_blueprint(api.bp)
    db.init_db(app)

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    # Make unknown /api/... URLs answer in JSON like the rest of the API.
    @app.errorhandler(404)
    @app.errorhandler(405)
    def api_error(exc):
        if request.path.startswith("/api/"):
            return error("Not found" if exc.code == 404 else "Method not allowed", exc.code)
        return exc

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=True)
