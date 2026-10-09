"""Bibliothèque, avis et questionnaire refait : pile ordonnée, retrait, notes, brouillon."""

from datetime import date

import pytest

from conftest import ANSWERS, login, make_user
from src import db
from src.questions import QUESTIONS


@pytest.fixture
def path(app):
    return app.config["DB_PATH"]


def pile(user, path):
    return [r["book_id"] for r in db.list_readings(user, db.TO_READ, path)]


def reading_id(user, book_id, path):
    return db.get_reading(user, book_id, path)["id"]


def finish(user, book_id, path):
    """Livre commencé puis terminé aujourd'hui ; renvoie l'id de la lecture."""
    today = date.today().isoformat()
    db.start_reading(user, book_id, today, db_path=path)
    db.finish_reading(user, book_id, today, db_path=path)
    return reading_id(user, book_id, path)


def test_ordre_monter_descendre_conserve_apres_reconnexion(app, client, path):
    user = make_user(app)
    for book in (1, 2, 3):
        db.add_to_pile(user, book, path)
    login(client, user)
    client.post(f"/lecture/{reading_id(user, 3, path)}/monter")
    client.post(f"/lecture/{reading_id(user, 1, path)}/descendre")
    assert pile(user, path) == [3, 1, 2]
    # Bouts de pile : rien ne bouge.
    assert not db.move_in_pile(user, reading_id(user, 3, path), -1, path)
    assert not db.move_in_pile(user, reading_id(user, 2, path), +1, path)

    client.get("/deconnexion")
    login(client, user)
    page = client.get("/bibliotheque?onglet=a-lire").get_data(as_text=True)
    titles = [page.index(t) for t in ("Étoiles lointaines", "Le Mystère du lac",
                                      "Ombres sur le village")]
    assert titles == sorted(titles)
    db.add_to_pile(user, 4, path)  # nouvel ajout en fin de pile
    assert pile(user, path) == [3, 1, 2, 4]


def test_onglets_compteurs_et_etats_vides(app, client, path):
    user = make_user(app)
    login(client, user)
    assert "Ta pile est vide" in client.get("/bibliotheque").get_data(as_text=True)
    db.add_to_pile(user, 1, path)
    finish(user, 2, path)
    assert db.count_readings(user, path) == {db.TO_READ: 1, db.READING: 0, db.FINISHED: 1}
    page = client.get("/bibliotheque?onglet=termines").get_data(as_text=True)
    assert "Ombres sur le village" in page and "Mon avis" in page
    assert "Rien en cours" in client.get("/bibliotheque?onglet=en-cours").get_data(as_text=True)


def test_avis_5_puis_1_remplace_l_effet(app, client, path):
    user = make_user(app)
    initial = db.load_profile(user, path)["genres"]["thriller"]
    rid = finish(user, 1, path)
    login(client, user)

    client.post(f"/lecture/{rid}/avis", data={"rating": "5", "comment": "Génial"})
    assert db.load_profile(user, path)["genres"]["thriller"] == pytest.approx(initial + 0.05)
    client.post(f"/lecture/{rid}/avis", data={"rating": "1", "comment": "Finalement non"})
    profile = db.load_profile(user, path)
    assert profile["genres"]["thriller"] == pytest.approx(initial - 0.05)  # pas de cumul
    assert db.get_reading(user, 1, path)["comment"] == "Finalement non"
    assert "Thriller -0,05" in client.get("/profil").get_data(as_text=True)


def test_note_absente_stockee_comme_absente(app, client, path):
    user = make_user(app)
    rid = finish(user, 1, path)
    login(client, user)
    client.post(f"/lecture/{rid}/avis", data={"rating": "4"})
    client.post(f"/lecture/{rid}/avis", data={"rating": "", "comment": "  "})
    reading = db.get_reading(user, 1, path)
    assert reading["rating"] is None and reading["comment"] is None
    assert db.list_ratings(user, path) == []
    assert db.load_profile(user, path)["genres"] == db.load_profile(user, path)["initial"]["genres"]

    page = client.post(f"/lecture/{rid}/avis", data={"rating": "6"}).get_data(as_text=True)
    assert "entre 1 et 5" in page
    page = client.post(f"/lecture/{rid}/avis", data={"comment": "x" * 2001}).get_data(as_text=True)
    assert "2000" in page and db.get_reading(user, 1, path)["comment"] is None


def test_retrait_termine_avec_confirmation_et_recalcul(app, client, path):
    user = make_user(app)
    rid = finish(user, 1, path)
    login(client, user)
    client.post(f"/lecture/{rid}/avis", data={"rating": "5"})
    assert db.load_profile(user, path)["genres"]["thriller"] > 1.0

    # Sans confirmation : page de confirmation, rien n'est supprimé.
    page = client.post(f"/lecture/{rid}/retirer").get_data(as_text=True)
    assert "Oui, retirer" in page and db.get_reading(user, 1, path) is not None

    client.post(f"/lecture/{rid}/retirer", data={"confirme": "1"})
    assert db.get_reading(user, 1, path) is None
    profile = db.load_profile(user, path)
    assert profile["genres"] == profile["initial"]["genres"]


def test_retrait_de_la_pile_resserre_les_rangs(app, client, path):
    user = make_user(app)
    for book in (1, 2, 3):
        db.add_to_pile(user, book, path)
    login(client, user)
    client.post(f"/lecture/{reading_id(user, 1, path)}/retirer")
    assert [r["rank"] for r in db.list_readings(user, db.TO_READ, path)] == [1, 2]


def test_dates_modifiables_memes_regles(app, client, path):
    user = make_user(app)
    rid = finish(user, 1, path)
    login(client, user)
    today = date.today().isoformat()
    client.post(f"/lecture/{rid}/dates", data={"start_date": "2026-01-01", "end_date": today})
    assert db.get_reading(user, 1, path)["start_date"] == "2026-01-01"
    with pytest.raises(ValueError, match="précéder"):
        db.update_dates(user, rid, "2026-02-01", "2026-01-15", db_path=path)
    with pytest.raises(ValueError, match="futur"):
        db.update_dates(user, rid, "2099-01-01", "2099-01-02", db_path=path)


def test_lecture_d_un_autre_introuvable(app, client, path):
    aline, bruno = make_user(app, "aline"), make_user(app, "bruno")
    rid = finish(aline, 1, path)
    login(client, bruno)
    assert client.get(f"/lecture/{rid}/avis").status_code == 404
    assert client.post(f"/lecture/{rid}/retirer", data={"confirme": "1"}).status_code == 404


def test_brouillon_n_altere_pas_le_profil_actif(app, client, path):
    user = make_user(app)
    rid = finish(user, 1, path)
    login(client, user)
    client.post(f"/lecture/{rid}/avis", data={"rating": "5"})
    before = db.load_profile(user, path)

    assert client.get("/questionnaire/refaire").headers["Location"] == "/questionnaire/refaire/1"
    client.post("/questionnaire/refaire/1", data={"answer": ["romance"]})
    client.post("/questionnaire/refaire/2", data={"answer": ["amour"]})
    assert db.load_draft(user, path) == {"q1": ["romance"], "q1_autre": "", "q2": ["amour"]}
    assert db.load_profile(user, path) == before
    assert db.load_answers(user, path) == ANSWERS
    assert "Reprendre" in client.get("/profil").get_data(as_text=True)

    # Abandon : brouillon effacé, profil intact.
    client.post("/questionnaire/refaire/abandonner")
    assert db.load_draft(user, path) is None and db.load_profile(user, path) == before


def test_validation_du_brouillon_remplace_le_profil(app, client, path):
    user = make_user(app)
    rid = finish(user, 5, path)  # romance
    login(client, user)
    client.post(f"/lecture/{rid}/avis", data={"rating": "5"})
    new = dict(ANSWERS, q1=["romance"], q8=["essais"], q6="classiques")
    client.get("/questionnaire/refaire")
    for n, q in enumerate(QUESTIONS, 1):
        answer = new[q["id"]]
        client.post(f"/questionnaire/refaire/{n}",
                    data={"answer": [answer] if isinstance(answer, str) else answer})

    profile = db.load_profile(user, path)
    assert profile["initial"]["genres"] == {"romance": 1.0}
    assert profile["genres"]["romance"] == pytest.approx(1.05)  # note conservée
    assert db.load_answers(user, path)["q1"] == ["romance"]
    filters = db.get_filters(user, path)
    assert filters["exclusions"] == ["essais"] and filters["period"] == "classiques"
    assert db.load_draft(user, path) is None


def test_page_profil(app, client, path):
    user = make_user(app)
    login(client, user)
    page = client.get("/profil").get_data(as_text=True)
    assert "TA BOUSSOLE LITTÉRAIRE" in page and "Mon profil" in page
    assert "Suspense &amp; tension" in page and "Revoir mes réponses" in page
    assert "/questionnaire/refaire" in page
    assert "CONFIANCE DU PROFIL" in page and "<svg" in page
    assert "Tendances observées" not in page          # aucune note encore
    assert "/bibliotheque?onglet=en-cours" in page and "/bibliotheque?onglet=termines" in page
    # Raccourcis : univers, pile à lire, renouvellement (POST).
    assert "/explorer" in page and "/bibliotheque?onglet=a-lire" in page
    assert 'action="/accueil/renouveler"' in page
    # Statistiques fusionnées, plus d'entrée dédiée dans le menu.
    assert 'id="statistiques"' in page and "▥ Statistiques" not in page
