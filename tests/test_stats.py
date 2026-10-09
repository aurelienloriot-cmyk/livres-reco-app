"""Statistiques personnelles : R11, R12, bornes de mois, aucune lecture, section statistiques de /profil."""

from datetime import date

from conftest import login, make_user
from src import db, stats

TODAY = date(2026, 10, 7)


def reading(book_id, end, pages=None, rating=None, start=None, categories=(), title=None):
    return {"id": book_id, "book_id": book_id, "title": title or f"Livre {book_id}",
            "start_date": start or end, "end_date": end, "rating": rating,
            "page_count": pages, "categories": list(categories)}


def test_r11_deux_livres_notes():
    readings = [reading(1, "2026-09-20", pages=300, rating=5, start="2026-09-09"),
                reading(2, "2026-10-02", pages=200, rating=3, start="2026-09-21")]
    result = stats.compute(readings, TODAY)
    assert result["pages"] == 500
    assert result["average"] == 4.0
    assert result["rated"] == 2 and result["finished"] == 2
    assert result["favorite"]["book_id"] == 1
    assert result["biggest"]["book_id"] == 1
    # 28 jours depuis le premier début = 4 semaines → 125 pages par semaine.
    assert result["pace"] == 125
    # Pages rattachées à la date de fin : seul le livre fini en octobre compte ce mois-ci.
    assert result["month"] == 1


def test_r12_lecture_sans_pages_ni_note():
    result = stats.compute([reading(1, "2026-10-01")], TODAY)
    assert result["finished"] == 1
    for key in ("pages", "average", "favorite", "biggest", "pace"):
        assert result[key] is None, key
    assert result["unknown_pages"] == 1 and result["rated"] == 0


def test_r12_pages_partiellement_connues():
    readings = [reading(1, "2026-10-01", pages=300), reading(2, "2026-10-02"),
                reading(3, "2026-10-03", pages=0)]
    result = stats.compute(readings, TODAY)
    assert result["pages"] == 300 and result["unknown_pages"] == 2
    assert result["biggest"]["book_id"] == 1


def test_bornes_de_mois():
    readings = [reading(1, "2026-09-30"), reading(2, "2026-10-01"), reading(3, "2026-10-31")]
    # Le 31 octobre : le 30 septembre est exclu, le 1er et le 31 octobre inclus.
    assert stats.compute(readings, date(2026, 10, 31))["month"] == 2
    # Le 1er octobre : le livre du 31 octobre n'est pas encore pris (après aujourd'hui).
    assert [r["book_id"] for r in stats.finished_this_month(readings, date(2026, 10, 1))] == [2]
    # Changement d'année : le 31 décembre n'appartient pas à janvier.
    year = [reading(1, "2025-12-31"), reading(2, "2026-01-01")]
    assert stats.compute(year, date(2026, 1, 15))["month"] == 1


def test_aucune_lecture():
    result = stats.compute([], TODAY)
    assert result["finished"] == 0 and result["month"] == 0 and result["genres"] == []
    for key in ("pages", "average", "favorite", "biggest", "pace"):
        assert result[key] is None, key


def test_prefere_egalite_le_plus_recent():
    readings = [reading(1, "2026-10-05", rating=5), reading(2, "2026-10-06", rating=5),
                reading(3, "2026-10-07", rating=4)]
    assert stats.favorite(readings)["book_id"] == 2


def test_rythme_moins_d_une_semaine():
    # 3 jours d'historique : on divise par une semaine, pas par 3/7.
    assert stats.pace([reading(1, "2026-10-07", pages=210, start="2026-10-04")], TODAY) == 210


def test_genres_une_fois_par_livre():
    readings = [reading(1, "2026-10-01", rating=4, categories=["thriller", "policier", "thriller"]),
                reading(2, "2026-10-02", rating=2, categories=["thriller"]),
                reading(3, "2026-10-03", categories=["romance"])]
    rows = {row["category"]: row for row in stats.genres(readings)}
    assert rows["thriller"] == {"category": "thriller", "count": 2, "rated": 2, "average": 3.0}
    assert rows["policier"]["count"] == 1
    assert rows["romance"]["average"] is None
    assert stats.genres(readings)[0]["category"] == "thriller"


def test_themes_et_ambiances_une_fois_par_livre():
    readings = [dict(reading(1, "2026-10-01"), themes=["crime", "secret", "crime"], ambiance="sombre"),
                dict(reading(2, "2026-10-02"), themes=["crime"], ambiance="sombre"),
                dict(reading(3, "2026-10-03"), themes=["amour"]),
                reading(4, "2026-10-04")]  # ni thèmes ni ambiance
    rows = stats.moods(readings)
    assert rows[:2] == [{"kind": "ambiance", "key": "sombre", "count": 2},
                        {"kind": "theme", "key": "crime", "count": 2}]
    assert {(r["key"], r["count"]) for r in rows[2:]} == {("amour", 1), ("secret", 1)}
    assert stats.compute([], TODAY)["moods"] == []
    assert stats.compute([], TODAY)["month_name"] == "octobre"


def test_statistiques_redirige_vers_profil(app, client):
    login(client, make_user(app))
    response = client.get("/statistiques")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/profil#statistiques")


def test_section_statistiques_du_profil(app, client):
    path = app.config["DB_PATH"]
    user = make_user(app)
    login(client, user)
    html = client.get("/profil").get_data(as_text=True)
    assert 'id="statistiques"' in html and "Mes statistiques de lecture" in html
    assert "Pas encore de données" in html
    assert "Termine un premier livre" in html

    for book_id, rating in ((3, 5), (6, None)):  # 500 pages ; pages inconnues
        db.start_reading(user, book_id, "2026-09-01", today=TODAY, db_path=path)
        db.finish_reading(user, book_id, "2026-09-15", today=TODAY, db_path=path)
        reading_id = db.get_reading(user, book_id, path)["id"]
        db.save_review(user, reading_id, rating, "", path)
    html = client.get("/profil").get_data(as_text=True)
    assert "Étoiles lointaines" in html and "/livre/3" in html
    assert "TON LIVRE PRÉFÉRÉ" in html and "Hélène Durand · 5/5" in html
    assert "Science <span>1</span>" in html and "Crime <span>1</span>" in html  # thèmes
    assert "1 lecture sans nombre de pages" in html
    assert "1 livre noté sur 2" in html
    assert "5,0/5" in html
    assert "comptées à la date de fin" in html
    assert "Termine un premier livre" not in html
