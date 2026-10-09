"""Parcours web : inscription, gating, questionnaire, profil."""

import pytest

from app import create_app
from src import db
from src.questions import NEUTRAL, QUESTIONS

ANSWERS = {
    "q1": ["thriller_polar"], "q2": ["crime", "secret"], "q3": ["tendue"],
    "q4": [NEUTRAL], "q5": "moyen", "q6": "recents", "q7": ["fr"], "q8": ["fantasy"],
    "q9": "themes", "q10": "mixte",
}


@pytest.fixture
def app(tmp_path):
    return create_app({"TESTING": True, "SECRET_KEY": "test", "DB_PATH": tmp_path / "books.db"})


@pytest.fixture
def client(app):
    return app.test_client()


def register(client, username="aline", email="aline@example.com", password="motdepasse"):
    return client.post("/inscription", data={
        "username": username, "email": email, "password": password, "confirm": password,
    })


def answer(client, n):
    value = ANSWERS[QUESTIONS[n - 1]["id"]]
    return client.post(f"/questionnaire/{n}", data={"answer": value})


def location(response):
    return response.headers["Location"]


def test_inscription_redirige_vers_questionnaire(client):
    response = register(client)
    assert response.status_code == 302
    assert location(response) == "/questionnaire"
    assert location(client.get("/questionnaire")) == "/questionnaire/1"


def test_inscription_erreurs(client):
    response = client.post("/inscription", data={
        "username": "al", "email": "pas-un-mail", "password": "court", "confirm": "court"})
    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "pseudo" in page and "e-mail" in page and "8 caractères" in page

    register(client)
    client.get("/deconnexion")
    page = register(client, email="autre@example.com").get_data(as_text=True)
    assert "déjà pris" in page


def test_connexion_par_pseudo_ou_email(client):
    register(client)
    client.get("/deconnexion")
    bad = client.post("/connexion", data={"login": "aline", "password": "mauvaismdp"})
    assert "incorrect" in bad.get_data(as_text=True)
    ok = client.post("/connexion", data={"login": "ALINE@example.com", "password": "motdepasse"})
    assert location(ok) == "/accueil"
    assert location(client.get("/accueil")) == "/questionnaire"


def test_accueil_sans_connexion_ni_profil(client):
    assert location(client.get("/accueil")) == "/connexion"
    register(client)
    assert location(client.get("/accueil")) == "/questionnaire"
    assert location(client.get("/profil-cree")) == "/questionnaire"


def test_reprise_a_la_bonne_question(client):
    register(client)
    for n in (1, 2, 3):
        assert location(answer(client, n)) == f"/questionnaire/{n + 1}"
    assert location(client.get("/questionnaire")) == "/questionnaire/4"
    # Pas de saut en avant, mais retour autorisé (réponse pré-cochée).
    assert location(client.get("/questionnaire/7")) == "/questionnaire/4"
    page = client.get("/questionnaire/2").get_data(as_text=True)
    assert 'value="crime" checked' in page


def test_reponse_vide_ou_neutre_exclusive(app, client):
    register(client)
    page = client.post("/questionnaire/1", data={}).get_data(as_text=True)
    assert "Choisis au moins une réponse" in page
    client.post("/questionnaire/1", data={"answer": ["thriller_polar", NEUTRAL]})
    assert db.load_answers(1, app.config["DB_PATH"])["q1"] == [NEUTRAL]


def test_validation_complete_cree_le_profil(app, client):
    register(client)
    for n in range(1, 10):
        answer(client, n)
    assert location(client.get("/accueil")) == "/questionnaire"
    assert location(answer(client, 10)) == "/profil-cree"

    page = client.get("/profil-cree").get_data(as_text=True)
    assert "PROFIL CRÉÉ" in page and "Suspense &amp; tension" in page
    assert db.load_profile(1, app.config["DB_PATH"])["label"] == "Suspense & tension"

    home = client.get("/accueil")
    assert home.status_code == 200
    assert "On lit quoi, maintenant ?" in home.get_data(as_text=True)
    assert location(client.get("/questionnaire")) == "/accueil"
    assert location(client.get("/questionnaire/3")) == "/accueil"
