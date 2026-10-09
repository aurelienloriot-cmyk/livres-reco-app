"""Application Flask « Et maintenant, je lis quoi ? »."""

import os

from dotenv import load_dotenv
from flask import Flask

from src import db


def create_app(test_config=None):
    """Crée l'application : configuration, base, blueprints.

    test_config permet aux tests d'imposer une base temporaire (DB_PATH) et une clé.
    """
    load_dotenv()
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        DB_PATH=db.DB_PATH,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if test_config:
        app.config.update(test_config)
    if not app.config["SECRET_KEY"]:
        raise RuntimeError("SECRET_KEY manquante : ajoute-la dans le fichier .env.")

    db.init_db(app.config["DB_PATH"])

    from app import auth, books, filters, library, main, survey
    app.register_blueprint(auth.bp)
    app.register_blueprint(survey.bp)
    app.register_blueprint(main.bp)
    app.register_blueprint(books.bp)
    app.register_blueprint(filters.bp)
    app.register_blueprint(library.bp)
    return app
