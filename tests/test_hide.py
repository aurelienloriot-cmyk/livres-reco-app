"""Livres masqués : hors moteur, recherche et accueil, mais gardés dans la bibliothèque."""

import pytest

from conftest import login, make_user
from src import db, engine, hide, suspects

HIDDEN = 6  # « Le Lac sans fond »


@pytest.fixture
def path(app):
    path = app.config["DB_PATH"]
    with db.get_connection(path) as conn:
        conn.execute("UPDATE books SET google_id = 'g' || id")
    return path


def test_moteur_ignore_le_livre_masque(app, path, tmp_path):
    assert HIDDEN in [r["book"]["id"] for r in engine.similar_books(1, 5, db_path=path)]
    engine.get_index(path)  # index en cache avant le masquage
    hide.hide_books([HIDDEN], path, tmp_path / "hidden.txt")
    index = engine.get_index(path)
    assert HIDDEN not in index.row_of
    assert HIDDEN not in [r["book"]["id"] for r in engine.similar_books(1, 5, db_path=path)]
    assert [b["id"] for b in engine.find_book(index, "lac")] == [1]


def test_recherche_ignore_le_livre_masque(app, client, path, tmp_path):
    login(client, make_user(app))
    assert "Le Lac sans fond" in client.get("/recherche?q=lac").get_data(as_text=True)
    hide.hide_books([HIDDEN], path, tmp_path / "hidden.txt")
    assert "Le Lac sans fond" not in client.get("/recherche?q=lac").get_data(as_text=True)
    assert client.get(f"/livre/{HIDDEN}").status_code == 404  # non suivi : introuvable


def test_bibliotheque_garde_le_livre_masque(app, client, path, tmp_path):
    user = make_user(app)
    db.add_to_pile(user, HIDDEN, path)
    login(client, user)
    hide.hide_books([HIDDEN], path, tmp_path / "hidden.txt")
    assert [r["book_id"] for r in db.list_readings(user, db.TO_READ, path)] == [HIDDEN]
    assert "Le Lac sans fond" in client.get("/bibliotheque").get_data(as_text=True)
    assert client.get(f"/livre/{HIDDEN}").status_code == 200  # fiche, sans similaires
    client.post(f"/livre/{HIDDEN}/commencer", data={"date": "2026-01-01"})
    assert db.get_reading(user, HIDDEN, path)["status"] == db.READING


def test_fichier_et_apply(app, path, tmp_path):
    file = tmp_path / "hidden.txt"
    hide.hide_books([HIDDEN, HIDDEN], path, file)  # pas de doublon dans le fichier
    assert file.read_text(encoding="utf-8") == "g6  # Le Lac sans fond — Marc Noir\n"
    with db.get_connection(path) as conn:  # base reconstruite : hidden remis à 0
        conn.execute("UPDATE books SET hidden = 0")
    assert hide.apply_hidden_file(path, file) == (1, [])
    assert [m["id"] for m in hide.find_matches("g6", path)] == [HIDDEN]
    assert hide.find_matches("g6", path)[0]["hidden"] == 1
    assert [m["id"] for m in hide.find_matches("LAC", path)] == [1, HIDDEN]


def test_migration_sans_perte(tmp_path):
    path = tmp_path / "old.db"
    with db.get_connection(path) as conn:
        conn.executescript(db.SCHEMA.replace(
            ",\n    hidden INTEGER NOT NULL DEFAULT 0  -- 1 = livre mal classé, écarté du catalogue"
            " (src.hide)", ""))
        assert "hidden" not in {r["name"] for r in conn.execute("PRAGMA table_info(books)")}
        conn.execute("INSERT INTO books (id, title, categories, themes, ambiance)"
                     " VALUES (42, 'Ancien', '[]', '[]', NULL)")
    db.init_db(path)
    with db.get_connection(path) as conn:
        row = conn.execute("SELECT id, hidden FROM books").fetchone()
    assert (row["id"], row["hidden"]) == (42, 0)


def test_suspects():
    book = {"title": "Le polar : de Poe à Vargas", "description": "Cet ouvrage étudie l’œuvre de"
            " Simenon, analysée par l’auteur."}
    assert suspects.reasons(book) == ["« cet ouvrage »", "« l'auteur »", "« etudi »",
                                      "« analys »", "« oeuvre de »", "titre « de X à Y »"]
    assert suspects.reasons({"title": "Le Lac", "description": "Une enquête."}) == []
