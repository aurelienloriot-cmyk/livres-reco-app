"""Accueil : seuil des lecteurs, popularité de la semaine, exclusion de la bibliothèque,
renouvellement, pages."""

from datetime import date, timedelta

import pytest

from app import filters as user_filters
from conftest import login, make_user
from src import db, home

TODAY = date(2026, 10, 7)


@pytest.fixture
def path(app):
    return app.config["DB_PATH"]


def user_row(user_id, path):
    return db.get_user(user_id, path)


def add_reading(path, user_id, book_id, start, end=None, rating=None):
    with db.get_connection(path) as conn:
        conn.execute("INSERT INTO readings (user_id, book_id, start_date, end_date, rating)"
                     " VALUES (?, ?, ?, ?, ?)", (user_id, book_id, start, end, rating))


def readers(app, path, count, book_id=1, start="2026-09-01", end="2026-09-10", prefix="r"):
    """count autres lecteurs (même famille) ayant commencé et terminé book_id."""
    ids = [make_user(app, f"{prefix}{i}") for i in range(count)]
    for user_id in ids:
        add_reading(path, user_id, book_id, start, end, 4)
    return ids


def kinds(sections):
    return [s["kind"] for s in sections]


def test_seuil_des_cinq_lecteurs(app, path):
    me = user_row(make_user(app), path)
    readers(app, path, home.MIN_READERS - 1)
    sections = home.community_sections(me, today=TODAY, db_path=path)
    # Les deux sections sous le seuil : une seule sélection de famille les remplace.
    assert kinds(sections) == ["famille"]
    assert sections[0]["title"] == "Sélection suspense"
    assert "au moins 5 lecteurs" in sections[0]["notice"]
    assert "4 lecteurs de ton profil" in sections[0]["notice"]

    readers(app, path, 1, prefix="last")  # 5e lecteur de la famille
    sections = home.community_sections(me, today=TODAY, db_path=path)
    assert kinds(sections) == ["lecteurs", "famille"]  # « populaires » encore sous le seuil
    assert sections[0]["items"][0]["book"]["id"] == 1
    assert sections[0]["items"][0]["note"] == "5 lecteurs"


def test_lecteurs_comme_toi_hors_utilisateur_et_classement(app, path):
    me = make_user(app)
    add_reading(path, me, 2, "2026-09-01", "2026-09-05", 5)  # ses propres lectures ne comptent pas
    a, b = readers(app, path, 2, book_id=3)
    add_reading(path, a, 4, "2026-09-01", "2026-09-02", 2)
    add_reading(path, b, 5, "2026-09-01", "2026-09-02", 5)
    add_reading(path, b, 6, "2026-09-01")                    # en cours : ignoré
    result = home.lecteurs_comme_toi(user_row(me, path), path)
    assert result["readers"] == 2
    # 3 : deux lecteurs ; puis 5 (note 5) avant 4 (note 2).
    assert [e["book"]["id"] for e in result["books"]] == [3, 5, 4]


def test_popularite_sur_sept_jours_un_lecteur_par_livre(app, path):
    users = [make_user(app, f"u{i}") for i in range(4)]
    day = lambda n: (TODAY - timedelta(days=n)).isoformat()
    add_reading(path, users[0], 1, day(0))
    add_reading(path, users[1], 1, day(6), day(2))  # J-6 : compté, même terminé
    add_reading(path, users[2], 1, day(3))
    add_reading(path, users[0], 2, day(1))          # même lecteur, autre livre
    add_reading(path, users[3], 3, day(7))          # J-7 : hors fenêtre
    result = home.populaires_semaine(TODAY, path)
    assert [(e["book"]["id"], e["readers"]) for e in result["books"]] == [(1, 3), (2, 1)]
    assert result["readers"] == 3  # lecteurs distincts de la semaine


def test_populaires_au_dessus_du_seuil(app, path):
    me = user_row(make_user(app), path)
    readers(app, path, 5, book_id=2, start=TODAY.isoformat(), end=None)
    sections = home.community_sections(me, today=TODAY, db_path=path)
    assert kinds(sections) == ["famille", "populaires"]  # « lecteurs » : rien de terminé
    assert sections[1]["items"][0]["note"] == "5 lecteurs cette semaine"


def test_exclusion_des_livres_de_la_bibliotheque(app, path):
    me = make_user(app)
    db.add_to_pile(me, 1, path)
    add_reading(path, me, 2, "2026-09-01")
    add_reading(path, me, 3, "2026-09-01", "2026-09-03")
    user = user_row(me, path)
    ids = {r["book"]["id"] for r in home.pour_toi(user, 10, db_path=path)}
    assert ids and not ids & {1, 2, 3}
    assert not {b["id"] for b in home.family_selection(user, db_path=path)} & {1, 2, 3}


def test_renouveler_reordonne_sans_pénalité_ni_doublon():
    results = [{"book": {"id": i}, "score": s} for i, s in ((1, 90), (2, 80), (3, 70))]
    assert [r["book"]["id"] for r in home.renouveler(results, [])] == [1, 2, 3]
    assert [r["book"]["id"] for r in home.renouveler(results, [1, 2])] == [3, 1, 2]


def test_renouveler_change_l_ordre_sans_changer_les_filtres(app, client, path):
    me = make_user(app)
    db.save_filters(me, dict(user_filters.DEFAULTS), path)  # 6 livres candidats
    login(client, me)
    client.get("/accueil")
    with client.session_transaction() as session:
        first = session["pour_toi_shown"]
    filters_before = db.get_filters(me, path)

    response = client.post("/accueil/renouveler")
    assert response.headers["Location"].endswith("/accueil#pour-toi")
    client.get("/accueil")
    with client.session_transaction() as session:
        second = session["pour_toi_shown"]
    assert len(first) == len(second) == 5
    assert second != first
    assert second[0] not in first  # le livre jamais proposé passe en tête
    assert db.get_filters(me, path) == filters_before


def test_univers(app, path):
    user = user_row(make_user(app), path)
    universes = home.univers(user, db_path=path)
    # Profil : thèmes crime et secret, ambiance tendue -> 3 univers, dans cet ordre,
    # sauf ceux qu'aucun livre ne remplit (le catalogue de test n'a pas d'ambiance).
    keys = [u["key"] for u in universes]
    assert keys[:2] == ["theme-crime", "theme-secret"]
    assert len(universes) == 3
    for u in universes:
        assert u["items"] and u["title"] and u["explanation"]
    assert universes[2]["key"] == "genre-thriller"


def test_pages_accueil_selection_explorer(app, client, path):
    me = make_user(app)
    db.save_filters(me, dict(user_filters.DEFAULTS), path)
    login(client, me)
    page = client.get("/accueil").get_data(as_text=True)
    for text in ("Lecture du moment".upper(), "Choisis pour toi", "Renouveler",
                 "Voir toute la sélection", "Sélection suspense", "3</strong> univers",
                 "pile est vide", "Explorer", 'class="nav-badge">0<', "?from=pour-toi"):
        assert text in page, text

    db.add_to_pile(me, 5, path)
    add_reading(path, me, 2, "2026-10-01")
    add_reading(path, me, 6, "2026-09-20")
    page = client.get("/accueil").get_data(as_text=True)
    assert "Ombres sur le village" in page and "Commencé le 1 oct. 2026" in page
    assert "+ 1 autre en cours" in page and 'class="nav-badge">3<' in page

    page = client.get("/selection/pour-toi").get_data(as_text=True)
    assert "Choisis pour toi" in page and "book-card" in page
    assert client.get("/selection/famille").status_code == 200
    assert client.get("/selection/lecteurs").status_code == 404  # remplacée : sous le seuil
    assert client.get("/selection/inconnue").status_code == 404

    page = client.get("/explorer").get_data(as_text=True)
    assert "Scènes de crime" in page and "?from=univers" in page

    page = client.get("/livre/1?from=famille").get_data(as_text=True)
    assert "Sélection suspense" in page


def test_explication_lecteurs_sur_la_fiche(app, client, path):
    me = make_user(app)
    readers(app, path, 5, book_id=4)
    login(client, me)
    page = client.get("/livre/4?from=lecteurs").get_data(as_text=True)
    assert "Terminé par 5 lecteurs au profil suspense, note moyenne 4,0/5." in page


def test_pages_protegees(client):
    for url in ("/accueil", "/explorer", "/selection/pour-toi"):
        assert client.get(url).headers["Location"] == "/connexion"
    assert client.post("/accueil/renouveler").headers["Location"] == "/connexion"


def test_affinity_pourcentage_et_couleur():
    assert home.affinity(91.6) == "92 % d'affinité"
    assert home.affinity(None) is None
    assert [home.affinity_level(S) for S in (92, 79.5, 79.4, 60, 40, 39.4, 0)] == [
        1, 1, 2, 2, 3, 4, 4]


def test_scores_for_comme_recommend(app, path):
    me = user_row(make_user(app), path)
    results = home.pour_toi(me, 6, db_path=path)
    scores = home.scores_for(me, [r["book"] for r in results], path)
    assert scores == pytest.approx({r["book"]["id"]: r["score"] for r in results})
    assert home.scores_for(me, [], path) == {}


def test_affinite_sur_toutes_les_cartes(app, client, path):
    me = make_user(app)
    db.save_filters(me, dict(user_filters.DEFAULTS), path)
    db.add_to_pile(me, 5, path)
    login(client, me)
    badge = "% d&#39;affinité</span>"
    for url in ("/accueil", "/explorer", "/selection/pour-toi", "/selection/famille",
                "/recherche?q=lac", "/livre/3", "/livre/1?from=pour-toi",
                "/bibliotheque?onglet=a-lire"):
        page = client.get(url).get_data(as_text=True)
        assert badge in page, url
        assert "Très forte affinité" not in page and "À découvrir" not in page
    # fiche : badge du livre + un par livre proche
    page = client.get("/livre/3").get_data(as_text=True)
    assert page.count(badge) == 1 + page.count('class="book-card"')
