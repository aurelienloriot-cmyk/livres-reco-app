import sys
from pathlib import Path

# Permet `import src...` quel que soit le répertoire de lancement de pytest.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json

import pytest

from app import create_app
from src import db, engine
from src.profile import build_profile

# Petit catalogue de test : id, titre, auteur, main_category, catégories, thèmes, année, pages
CATALOG = [
    (1, "Le Mystère du lac", "Émile Gaboriau", "thriller", ["thriller", "policier"],
     ["crime", "secret"], 2015, 320),
    (2, "Ombres sur le village", "Anne Martin", "policier", ["policier"], ["crime", "famille"],
     2008, 280),
    (3, "Étoiles lointaines", "Hélène Durand", "science-fiction", ["science-fiction"],
     ["science", "voyage"], 2020, 500),
    (4, "Le Vaisseau oublié", "Paul Leroy", "science-fiction", ["science-fiction", "aventure"],
     ["voyage", "science"], 2012, 600),
    (5, "Cœurs d'été", "Julie Petit", "romance", ["romance"], ["amour"], 2021, 220),
    (6, "Le Lac sans fond", "Marc Noir", "thriller", ["thriller"], ["crime"], 2019, None),
]
DESCRIPTION = ("Une histoire de lac, d'étoiles, de vaisseau, de village et de secret : "
               "enquête, voyage, amour et science se croisent au fil des pages.")
ANSWERS = {
    "q1": ["thriller_polar"], "q2": ["crime", "secret"], "q3": ["tendue"], "q4": ["neutre"],
    "q5": "moyen", "q6": "recents", "q7": ["fr"], "q8": ["fantasy"], "q9": "themes",
    "q10": "mixte",
}


@pytest.fixture
def app(tmp_path):
    path = tmp_path / "books.db"
    application = create_app({"TESTING": True, "SECRET_KEY": "test", "DB_PATH": path})
    with db.get_connection(path) as conn:
        for id_, title, author, main, cats, themes, year, pages in CATALOG:
            conn.execute(
                "INSERT INTO books (id, title, authors, description, main_category, categories,"
                " themes, published_year, page_count, language, isbn)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'fr', ?)",
                (id_, title, json.dumps([author]), DESCRIPTION, main,
                 json.dumps(cats, ensure_ascii=False), json.dumps(themes), year, pages,
                 f"978000000000{id_}"))
    engine.reset_cache()
    yield application
    engine.reset_cache()


@pytest.fixture
def client(app):
    return app.test_client()


def make_user(app, username="aline"):
    """Compte avec questionnaire rempli et profil calculé ; renvoie son id."""
    path = app.config["DB_PATH"]
    user_id = db.create_user(username, f"{username}@example.com", "x", path)
    for qid, answer in ANSWERS.items():
        db.save_answer(user_id, qid, answer, path)
    db.save_profile(user_id, build_profile(ANSWERS), path)
    return user_id


def login(client, user_id):
    with client.session_transaction() as session:
        session["user_id"] = user_id
