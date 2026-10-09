"""Suivi de lecture : pile, commencer, terminer, doublons, propriété, migration."""

from datetime import date, timedelta

import pytest

from conftest import login, make_user
from src import db

TODAY = date(2026, 10, 7)


@pytest.fixture
def path(app):
    return app.config["DB_PATH"]


def statuses(user_id, path):
    return {r["book_id"]: r["status"] for r in db.list_readings(user_id, db_path=path)}


def test_transitions_pile_commencer_terminer(app, path):
    user = make_user(app)
    assert db.add_to_pile(user, 1, path)
    assert db.add_to_pile(user, 2, path)
    assert db.get_reading(user, 1, path)["status"] == db.TO_READ
    assert [r["rank"] for r in db.list_readings(user, db.TO_READ, path)] == [1, 2]

    assert db.start_reading(user, 1, "2026-10-01", today=TODAY, db_path=path)
    reading = db.get_reading(user, 1, path)
    assert reading["status"] == db.READING and reading["rank"] is None
    # La pile se resserre : le livre 2 passe en tête.
    assert db.get_reading(user, 2, path)["rank"] == 1

    assert db.finish_reading(user, 1, "2026-10-05", today=TODAY, db_path=path)
    assert db.get_reading(user, 1, path)["status"] == db.FINISHED
    assert [r["book_id"] for r in db.list_readings(user, db.FINISHED, path)] == [1]

    # Commencer directement un livre absent de la pile.
    assert db.start_reading(user, 3, "2026-10-07", today=TODAY, db_path=path)
    assert statuses(user, path) == {1: db.FINISHED, 2: db.TO_READ, 3: db.READING}


def test_transitions_impossibles(app, path):
    user = make_user(app)
    assert not db.finish_reading(user, 1, "2026-10-05", today=TODAY, db_path=path)  # absent
    db.add_to_pile(user, 1, path)
    assert not db.finish_reading(user, 1, "2026-10-05", today=TODAY, db_path=path)  # à lire
    db.start_reading(user, 1, "2026-10-01", today=TODAY, db_path=path)
    assert not db.start_reading(user, 1, "2026-10-02", today=TODAY, db_path=path)  # en cours
    assert db.get_reading(user, 1, path)["start_date"] == "2026-10-01"


@pytest.mark.parametrize("end, message", [
    ("2026-09-30", "précéder"),       # avant le début
    ("2026-10-08", "futur"),          # après aujourd'hui
    ("pas-une-date", "pas valide"),
])
def test_date_de_fin_invalide_refusee(app, path, end, message):
    user = make_user(app)
    db.start_reading(user, 1, "2026-10-01", today=TODAY, db_path=path)
    with pytest.raises(ValueError, match=message):
        db.finish_reading(user, 1, end, today=TODAY, db_path=path)
    assert db.get_reading(user, 1, path)["status"] == db.READING


def test_date_de_debut_future_refusee(app, path):
    user = make_user(app)
    with pytest.raises(ValueError, match="futur"):
        db.start_reading(user, 1, "2026-10-08", today=TODAY, db_path=path)
    assert db.get_reading(user, 1, path) is None


def test_doublon_refuse(app, client, path):
    user = make_user(app)
    login(client, user)
    client.post("/livre/1/pile")
    client.post("/livre/1/pile")  # double soumission
    assert not db.add_to_pile(user, 1, path)
    today = date.today().isoformat()
    client.post("/livre/2/commencer", data={"date": today})
    client.post("/livre/2/commencer", data={"date": today})
    with db.get_connection(path) as conn:
        counts = conn.execute("SELECT book_id, COUNT(*) FROM readings GROUP BY book_id").fetchall()
    assert {row[0]: row[1] for row in counts} == {1: 1, 2: 1}


def test_parcours_web_et_fin_invalide(app, client, path):
    user = make_user(app)
    login(client, user)
    page = client.get("/livre/1").get_data(as_text=True)
    assert "Ajouter à ma pile" in page and "Commencer" in page

    today = date.today()
    client.post("/livre/1/commencer", data={"date": today.isoformat()})
    page = client.get("/livre/1").get_data(as_text=True)
    assert "Terminer" in page and "Ajouter à ma pile" not in page

    yesterday = (today - timedelta(days=1)).isoformat()
    page = client.post("/livre/1/terminer", data={"date": yesterday},
                       follow_redirects=True).get_data(as_text=True)
    assert "ne peut pas précéder" in page
    assert db.get_reading(user, 1, path)["status"] == db.READING

    page = client.post("/livre/1/terminer", data={"date": today.isoformat()},
                       follow_redirects=True).get_data(as_text=True)
    assert "TON AVIS" in page  # Terminer mène à la page d'avis
    assert "Voir mon avis" in client.get("/livre/1").get_data(as_text=True)


def test_propriete_des_lectures(app, client, path):
    aline = make_user(app, "aline")
    bruno = make_user(app, "bruno")
    db.start_reading(aline, 1, "2026-10-01", today=TODAY, db_path=path)

    assert db.get_reading(bruno, 1, path) is None
    assert db.list_readings(bruno, db_path=path) == []
    login(client, bruno)
    assert "Ajouter à ma pile" in client.get("/livre/1").get_data(as_text=True)
    # Bruno ne peut pas terminer la lecture d'Aline.
    client.post("/livre/1/terminer", data={"date": date.today().isoformat()})
    assert db.get_reading(aline, 1, path)["end_date"] is None


def test_fiche_protegee_et_livre_inconnu(app, client):
    assert client.get("/livre/1").headers["Location"] == "/connexion"
    login(client, make_user(app))
    assert client.get("/livre/999").status_code == 404


def test_fiche_infos_et_explications(app, client):
    login(client, make_user(app))
    page = client.get("/livre/6?from=pour-toi").get_data(as_text=True)
    assert "information indisponible" in page          # pas de nombre de pages
    assert "Recommandé pour" in page
    assert "covers.openlibrary.org/b/isbn/9780000000006-M.jpg?default=false" in page
    assert "Livres proches" in page
    page = client.get("/livre/3?q=etoiles").get_data(as_text=True)
    assert "Correspond à ta recherche" in page


def test_migration_sans_perte(tmp_path):
    path = tmp_path / "old.db"
    with db.get_connection(path) as conn:
        conn.executescript("""
            CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, password_hash TEXT);
            CREATE TABLE books (id INTEGER PRIMARY KEY, categories TEXT, themes TEXT, ambiance TEXT);
            CREATE TABLE readings (id INTEGER PRIMARY KEY, user_id INTEGER, book_id INTEGER,
                start_date TEXT, end_date TEXT, rating INTEGER, comment TEXT);
            INSERT INTO users VALUES (1, 'aline', 'x');
            INSERT INTO books (id) VALUES (1), (2), (3);
            INSERT INTO readings VALUES (1, 1, 1, '2026-01-01', '2026-01-10', 5, 'Super');
            INSERT INTO readings VALUES (2, 1, 2, NULL, NULL, NULL, NULL);
            INSERT INTO readings VALUES (3, 1, 3, NULL, NULL, NULL, NULL);
        """)
    db.init_db(path)
    with db.get_connection(path) as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM readings ORDER BY id")]
    assert [(r["book_id"], r["rank"], r["rating"], r["comment"]) for r in rows] == [
        (1, None, 5, "Super"), (2, 1, None, None), (3, 2, None, None)]
    assert not db.add_to_pile(1, 1, path)  # contrainte UNIQUE en place
    db.init_db(path)  # relancer ne change rien
    assert db.get_filters(1, path) is None
