import json

import pytest

from src import engine
from src.db import get_connection, init_db

# id, titre, main_category, categories, thèmes, année, pages, note, nb avis, description
BOOKS = [
    (1, "Le Mystère du lac", "thriller", ["thriller", "policier"], ["crime", "secret"], 2015, 320,
     None, 0, "Une enquête sur la disparition d'une jeune femme près du lac. Le commissaire "
     "découvre un secret enfoui dans le village et un meurtre ancien."),
    (2, "Ombres sur le village", "policier", ["policier", "thriller"], ["crime", "famille"], 2008,
     280, None, 0, "Dans un village isolé, un meurtre bouleverse une famille. L'enquête du "
     "commissaire révèle un secret de famille et une disparition."),
    (3, "La Nuit du commissaire", "policier", ["policier"], ["crime"], 1990, 450, 4.2, 10,
     "Le commissaire mène l'enquête sur un meurtre à Paris, entre suspects, alibis et victime."),
    (4, "Étoiles lointaines", "science-fiction", ["science-fiction"], ["science", "voyage"], 2020,
     500, None, 0, "Un vaisseau spatial quitte la Terre pour un voyage vers des étoiles "
     "lointaines. L'équipage découvre une planète inconnue."),
    (5, "Le Vaisseau oublié", "science-fiction", ["science-fiction", "aventure"],
     ["voyage", "science"], 2012, 600, None, 0, "Le vaisseau dérive entre les étoiles. "
     "L'équipage explore une planète et affronte l'inconnu au cours d'un long voyage."),
    (6, "Cœurs d'été", "romance", ["romance"], ["amour", "amitie"], 2021, 220, None, 0,
     "Un été au bord de la mer, deux amis tombent amoureux. Un amour léger, une amitié "
     "fidèle et des promesses."),
    (7, "Lettres à Clara", "romance", ["romance", "littérature générale"], ["amour", "famille"],
     1975, 180, None, 0, "Des lettres d'amour retrouvées dans une famille. Clara découvre "
     "le passé de sa mère et un amour interdit."),
    (8, "L'Île au trésor perdu", "aventure", ["aventure"], ["voyage", "secret"], 2001, 350, None,
     0, "Un voyage en mer vers une île perdue où un trésor attend. Pirates, carte secrète "
     "et aventure."),
]


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "books.db"
    init_db(path)
    with get_connection(path) as conn:
        for (id_, title, main, cats, themes, year, pages, rating, count, desc) in BOOKS:
            conn.execute(
                "INSERT INTO books (id, title, authors, description, main_category, categories,"
                " themes, published_year, page_count, avg_rating, ratings_count)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (id_, title, json.dumps(["Auteur Test"]), desc, main,
                 json.dumps(cats, ensure_ascii=False), json.dumps(themes), year, pages,
                 rating, count),
            )
    engine.reset_cache()
    yield path
    engine.reset_cache()


def ids(results):
    return [r["book"]["id"] for r in results]


# --- Résultats --------------------------------------------------------------------

def test_returns_n_results(db):
    assert len(engine.similar_books(1, n=3, db_path=db)) == 3
    assert len(engine.similar_books(1, n=5, db_path=db)) == 5


def test_source_excluded(db):
    results = engine.similar_books(1, n=10, db_path=db)
    assert len(results) == 7 and 1 not in ids(results)


def test_scores_sorted_and_closest_first(db):
    results = engine.similar_books(1, n=7, db_path=db)
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)
    assert ids(results)[0] in {2, 3}  # les deux autres polars


def test_unknown_book_raises(db):
    with pytest.raises(KeyError):
        engine.similar_books(999, db_path=db)


# --- Filtres -----------------------------------------------------------------------

def run(db, **kwargs):
    return [r["book"] for r in engine.similar_books(1, n=10, filters=engine.Filters(**kwargs),
                                                    db_path=db)]


def test_filter_categories_in(db):
    books = run(db, categories_in={"policier"})
    assert {b["id"] for b in books} == {2, 3}


def test_filter_categories_out(db):
    books = run(db, categories_out={"policier", "romance"})
    assert {b["id"] for b in books} == {4, 5, 8}


def test_filter_years(db):
    assert all(b["published_year"] >= 2010 for b in run(db, year_min=2010))
    assert {b["id"] for b in run(db, year_max=2000)} == {3, 7}


def test_filter_max_pages(db):
    books = run(db, max_pages=300)
    assert books and all(b["page_count"] <= 300 for b in books)


def test_filter_exclude_ids(db):
    assert not {2, 3} & {b["id"] for b in run(db, exclude_ids={2, 3})}


def test_filter_with_no_candidate(db):
    assert run(db, categories_in={"horreur"}) == []


# --- Explication ------------------------------------------------------------------

def test_explanation_starts_with_recommande_pour(db):
    for r in engine.similar_books(1, n=7, db_path=db):
        assert r["explanation"].startswith("Recommandé pour ") and len(r["explanation"]) > 20


def test_explanation_lists_common_tags_and_words(db):
    result = engine.similar_books(1, n=1, filters=engine.Filters(categories_in={"policier"},
                                                                 exclude_ids={3}), db_path=db)[0]
    text = result["explanation"]
    assert "le thème crime" in text and "thriller et policier" in text
    assert "« " in text and "« crime »" not in text  # termes déjà cités non répétés


# --- Nouveauté --------------------------------------------------------------------

def test_novelty_bounded(db):
    vec = engine.centroid([1, 2], weights=[2, 1], db_path=db)
    scores = engine.novelty(vec, [b[0] for b in BOOKS], db_path=db)
    assert len(scores) == 8 and all(0 <= n <= 100 for n in scores.values())
    assert scores[1] < scores[6]  # un polar est moins nouveau qu'une romance


def test_novelty_of_book_itself_is_zero(db):
    scores = engine.novelty(engine.centroid([4], db_path=db), [4], db_path=db)
    assert scores[4] == pytest.approx(0, abs=1e-6)


def test_novelty_without_centroid(db):
    assert engine.centroid([], db_path=db) is None
    assert engine.centroid([999], db_path=db) is None
    assert engine.novelty(None, [1, 2]) is None


# --- Cache -------------------------------------------------------------------------

def test_pickle_rebuilt_when_catalogue_changes(db):
    engine.similar_books(1, db_path=db)
    pkl = db.parent / "tfidf.pkl"
    assert pkl.exists()
    with get_connection(db) as conn:
        conn.execute("DELETE FROM books WHERE id = 8")
    engine.reset_cache()
    assert 8 not in ids(engine.similar_books(1, n=10, db_path=db))
