import copy
import json

import pytest

from src import engine, profile as prof
from src.db import (get_connection, init_db, load_answers, load_profile, save_answer,
                    save_profile)
from src.questions import GROUPS, QUESTIONS, QUESTIONS_BY_ID

YEAR = 2026
NEUTRAL_ANSWERS = {q["id"]: "neutre" for q in QUESTIONS}


def answers(**kwargs):
    return {**NEUTRAL_ANSWERS, **kwargs}


def book(id_=1, main="thriller", cats=("thriller",), themes=(), ambiance=None, year=2020,
         pages=300):
    return {"id": id_, "title": f"Livre {id_}", "authors": [f"Auteur {id_}"], "main_category": main,
            "categories": list(cats), "themes": list(themes), "ambiance": ambiance,
            "published_year": year, "page_count": pages, "avg_rating": None,
            "ratings_count": 0, "description": ""}


# --- Questionnaire ---------------------------------------------------------------------

def test_questions_have_neutral_option_and_weights():
    assert [q["id"] for q in QUESTIONS] == [f"q{i}" for i in range(1, 11)]
    for q in QUESTIONS:
        assert q["options"][-1]["code"] == "neutre"
    weights = {q["id"]: q["weight"] for q in QUESTIONS}
    assert sum(weights[q] for q in ("q1", "q2", "q3", "q4", "q5", "q6")) == 84


def test_screen_options():
    codes = {qid: [o["code"] for o in QUESTIONS_BY_ID[qid]["options"]] for qid in ("q1", "q2", "q8")}
    assert codes["q1"] == [*GROUPS, "autre", "neutre"]
    assert codes["q8"] == [*GROUPS, "aucun", "neutre"]
    assert codes["q2"] == ["famille", "secret", "survie", "societe", "amour", "crime", "science",
                           "memoire", "neutre"]
    covered = [c for _, cats in GROUPS.values() for c in cats]
    assert sorted(covered) == sorted(prof.CATEGORY_LABELS)  # 8 groupes = 12 catégories


def test_groups_are_expanded():
    p = prof.build_profile(answers(q1=["thriller_polar", "romance", "autre"],
                                   q8=["fantasy", "essais"]))
    assert p["genres"] == {"thriller": 1.0, "policier": 1.0, "romance": 1.0}
    assert p["exclusions"] == ["fantastique", "horreur", "essai"]
    assert prof.build_profile(answers(q8=["aucun"]))["exclusions"] == []


# --- Exemple A du barème -----------------------------------------------------------------

def test_example_a():
    """q1 et q2 renseignés : livre entièrement dans les genres (100), 1 thème sur 2 (50).
    P = (24 × 100 + 22 × 50) / 46 = 76,1 ; confiance 46 / 84 = 54,8 %."""
    p = prof.build_profile(answers(q1=["thriller", "policier"], q2=["crime", "amour"],
                                   q5="toutes", q6="toutes", q3=["varie"]))
    assert round(p["confidence"] * 100, 1) == 54.8
    b = book(cats=["thriller", "policier"], themes=["crime", "famille"], ambiance="tendue")
    S, detail = prof.score_book(p, b, N=0, year=YEAR)
    assert detail["q1"]["match"] == 100 and detail["q2"]["match"] == 50
    assert "q3" not in detail and "q5" not in detail and "q6" not in detail
    assert round(detail["P"], 1) == 76.1
    assert S == pytest.approx(0.84 * detail["P"])


def test_all_neutral():
    p = prof.build_profile(NEUTRAL_ANSWERS)
    assert p["confidence"] == 0
    assert p["label"] == "Éclectique" and p["family"] == "éclectique"
    S, detail = prof.score_book(p, book(themes=["crime"], ambiance="sombre"), N=50, year=YEAR)
    assert detail["P"] is None
    assert not {"q1", "q2", "q3", "q5", "q6"} & detail.keys()
    assert S == 0  # q9 et q10 neutres : aucun bonus


def test_bonus_r_and_d():
    p = prof.build_profile(answers(q2=["crime"], q9="themes", q10="surprise"))
    S, d = prof.score_book(p, book(themes=["crime", "secret"]), N=50, year=YEAR)
    assert d["R"] == pytest.approx(4.0)   # correspondance q2 50 % × 8
    assert d["D"] == pytest.approx(4.0)   # 1,0 × 50 × 8 / 100
    assert S == pytest.approx(0.84 * 50 + 8)

    p = prof.build_profile(answers(q9="profil", q10="proche"))
    _, d = prof.score_book(p, book(), N=80, group_pop=None, year=YEAR)
    assert d["R"] == 0 and d["D"] == 0


# --- q5 / q6 -----------------------------------------------------------------------------

@pytest.mark.parametrize("target, pages, expected", [
    ("moyen", 300, 100), ("moyen", 200, 50), ("moyen", 500, 50),
    ("court", 200, 100), ("court", 300, 50), ("court", 600, 0),
    ("long", 451, 100), ("long", 249, 0),
])
def test_length(target, pages, expected):
    p = prof.build_profile(answers(q5=target))
    _, d = prof.score_book(p, book(pages=pages), N=0, year=YEAR)
    assert d["q5"]["match"] == expected


def test_length_ignored():
    for q5, pages in (("toutes", 300), ("moyen", None)):
        _, d = prof.score_book(prof.build_profile(answers(q5=q5)), book(pages=pages), 0, year=YEAR)
        assert "q5" not in d


@pytest.mark.parametrize("period, age, expected", [
    ("nouveautes", 3, 100), ("nouveautes", 4, 50), ("nouveautes", 10, 50), ("nouveautes", 11, 0),
    ("recents", 10, 100), ("recents", 25, 50), ("recents", 26, 0),
    ("classiques", 26, 100), ("classiques", 25, 50), ("classiques", 1, 50),
])
def test_period(period, age, expected):
    p = prof.build_profile(answers(q6=period))
    _, d = prof.score_book(p, book(year=YEAR - age), N=0, year=YEAR)
    assert d["q6"]["match"] == expected


def test_ambiance_ignored_if_unknown():
    p = prof.build_profile(answers(q3=["tendue"]))
    assert prof.score_book(p, book(ambiance="tendue"), 0, year=YEAR)[1]["q3"]["match"] == 100
    assert prof.score_book(p, book(ambiance="legere"), 0, year=YEAR)[1]["q3"]["match"] == 0
    assert "q3" not in prof.score_book(p, book(ambiance=None), 0, year=YEAR)[1]


# --- Nouveauté sans lecture ----------------------------------------------------------------

def test_novelty_from_profile():
    p = prof.build_profile(answers(q1=["thriller"], q2=["crime"]))
    books = [book(1, themes=["crime"]), book(2, themes=["amour"]),
             book(3, main="romance", cats=["romance"], themes=["amour"])]
    assert prof.novelty_for(p, books) == {1: 0, 2: 50, 3: 100}
    neutral = prof.build_profile(NEUTRAL_ANSWERS)
    assert prof.novelty_for(neutral, books) == {1: 50, 2: 50, 3: 50}


# --- Recommandation sur un petit catalogue --------------------------------------------------

CATALOGUE = [
    book(1, "thriller", ["thriller"], ["crime", "secret"], "tendue", 2020, 300),
    book(2, "horreur", ["horreur", "thriller"], ["crime"], "sombre", 2020, 300),
    book(3, "romance", ["romance"], ["amour"], "legere", 2021, 220),
    book(4, "policier", ["policier"], ["crime"], None, 2010, 400),
]


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "books.db"
    init_db(path)
    with get_connection(path) as conn:
        for b in CATALOGUE:
            conn.execute(
                "INSERT INTO books (id, title, authors, description, main_category, categories,"
                " themes, ambiance, published_year, page_count) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (b["id"], b["title"], json.dumps(b["authors"]),
                 "Une histoire de livre test avec enquête et secret.", b["main_category"],
                 json.dumps(b["categories"]), json.dumps(b["themes"]),
                 json.dumps(b["ambiance"]) if b["ambiance"] else None,
                 b["published_year"], b["page_count"]))
    engine.reset_cache()
    yield path
    engine.reset_cache()


def test_exclusion_wins_over_q1(db):
    p = prof.build_profile(answers(q1=["thriller", "horreur"], q8=["horreur"]))
    ids = [r["book"]["id"] for r in prof.recommend(p, n=10, db_path=db)]
    assert 2 not in ids  # horreur exclue même si choisie en q1
    assert ids[0] == 1


def test_recommend_excludes_read_and_explains(db):
    p = prof.build_profile(answers(q1=["thriller"], q2=["crime"], q3=["tendue"]))
    results = prof.recommend(p, n=10, read_ids=[4], db_path=db)
    assert 4 not in [r["book"]["id"] for r in results]
    top = results[0]
    assert top["book"]["id"] == 1
    assert top["explanation"].startswith("Recommandé pour")
    assert "le genre Thriller" in top["explanation"] and "crime" in top["explanation"]
    assert "tendue" in top["explanation"]


def test_recommend_mentions_discovery(db):
    p = prof.build_profile(answers(q1=["thriller"], q10="surprise", q9="nouveau"))
    results = prof.recommend(p, n=10, db_path=db)
    romance = next(r for r in results if r["book"]["id"] == 3)
    assert "te faire découvrir" in romance["explanation"]


def test_tie_break(db):
    """À S égal : plus de dimensions calculées, puis note moyenne (≥ 5 avis), puis id."""
    with get_connection(db) as conn:
        conn.execute("UPDATE books SET ambiance = NULL, themes = '[]' WHERE id = 1")
        conn.execute("INSERT INTO books (id, title, authors, description, main_category,"
                     " categories, themes, ambiance, published_year, page_count, avg_rating,"
                     " ratings_count) VALUES (5, 'Livre 5', '[]', 'test', 'thriller',"
                     " '[\"thriller\"]', '[\"crime\"]', '\"tendue\"', 2020, 300, 4.5, 3)")
        conn.execute("INSERT INTO books (id, title, authors, description, main_category,"
                     " categories, themes, ambiance, published_year, page_count, avg_rating,"
                     " ratings_count) VALUES (6, 'Livre 6', '[]', 'test', 'thriller',"
                     " '[\"thriller\"]', '[]', NULL, 2020, 300, 4.0, 12)")
    engine.reset_cache()
    p = prof.build_profile(answers(q1=["thriller"], q2=["crime"], q3=["tendue"]))
    results = prof.recommend(p, n=3, db_path=db)
    assert [r["score"] for r in results] == [84.0] * 3
    # 5 : 3 dimensions ; 6 et 1 : 1 dimension, 6 a une note fiable (12 avis)
    assert [r["book"]["id"] for r in results] == [5, 6, 1]


def test_one_book_per_author(db):
    with get_connection(db) as conn:
        conn.execute("""UPDATE books SET authors = '["Émile Zola"]' WHERE id = 1""")
        conn.execute("""UPDATE books SET authors = '["emile zola", "Autre"]' WHERE id = 4""")
    engine.reset_cache()
    p = prof.build_profile(answers(q1=["thriller", "policier"], q2=["crime"]))
    results = prof.recommend(p, n=3, db_path=db)
    ids = [r["book"]["id"] for r in results]
    assert ids[0] == 4 and 1 not in ids   # même premier auteur une fois normalisé
    assert len(ids) == 3                  # les livres suivants complètent la liste


def test_diversify_trois_par_categorie_si_possible():
    items = [{"book": book(i, main)} for i, main in enumerate(
        ["thriller"] * 5 + ["romance", "policier"], 1)]
    assert [r["book"]["id"] for r in prof.diversify(items, 5)] == [1, 2, 3, 6, 7]
    # vivier insuffisant : complété sans contrainte, dans l'ordre
    assert [r["book"]["id"] for r in prof.diversify(items[:5], 4)] == [1, 2, 3, 4]
    assert [r["book"]["id"] for r in prof.diversify(items, 5, None)] == [1, 2, 3, 4, 5]


def test_recommend_diversifie_les_categories(db):
    with get_connection(db) as conn:
        for id_ in (5, 6, 7):
            conn.execute("INSERT INTO books (id, title, authors, description, main_category,"
                         " categories, themes, ambiance, published_year, page_count) VALUES"
                         f" ({id_}, 'Livre {id_}', '[\"Auteur {id_}\"]', 'test', 'thriller',"
                         " '[\"thriller\"]', '[\"crime\"]', '\"tendue\"', 2020, 300)")
    engine.reset_cache()
    p = prof.build_profile(answers(q1=["thriller"], q2=["crime"], q3=["tendue"]))
    free = prof.recommend(p, n=5, db_path=db, max_per_category=None)
    assert sum(r["book"]["main_category"] == "thriller" for r in free) == 4
    results = prof.recommend(p, n=5, db_path=db)
    cats = [r["book"]["main_category"] for r in results]
    assert cats.count("thriller") == 3 and len(results) == 5
    assert [r["score"] for r in results] == sorted([r["score"] for r in results], reverse=True)


# --- Mise à jour après une note --------------------------------------------------------------

def test_recompute_learned_and_cap():
    p = prof.build_profile(answers(q1=["thriller"], q2=["crime"]))
    b = book(main="thriller", cats=["thriller", "policier"], themes=["crime"], ambiance="sombre")
    prof.recompute_learned(p, [(b, 5)])
    assert p["genres"] == {"thriller": 1.05, "policier": 0.05}
    assert p["themes"]["crime"] == 1.05 and p["ambiances"]["sombre"] == 0.05
    prof.recompute_learned(p, [(b, 5)] * 21)
    assert p["genres"]["thriller"] == 1.30 and p["genres"]["policier"] == 0.30

    prof.recompute_learned(p, [(b, 1)] * 30 + [(b, 3)])
    assert p["genres"]["thriller"] == 0.70   # plafond −0,30 sous la valeur initiale
    assert "policier" not in p["genres"]     # une note négative ne crée rien


def test_recompute_is_idempotent_and_note_change_does_not_stack():
    p = prof.build_profile(answers(q1=["thriller"], q2=["crime"]))
    b = book(main="thriller", cats=["thriller"], themes=["crime"])
    first = copy.deepcopy(prof.recompute_learned(p, [(b, 5)]))
    assert prof.recompute_learned(p, [(b, 5)]) == first          # relancer ne cumule pas
    prof.recompute_learned(p, [(b, 2)])                          # 5 -> 2 : on repart de initial
    assert p["genres"]["thriller"] == 0.95 and p["themes"]["crime"] == 0.95
    prof.recompute_learned(p, [])                                # note retirée
    assert p["genres"] == p["initial"]["genres"] == {"thriller": 1.0}


def test_neutral_dimension_stays_out_of_p_after_learning():
    p = prof.build_profile(answers(q2=["crime"]))
    assert p["answered"] == {"q1": False, "q2": True, "q3": False, "q5": False, "q6": False}
    b = book(main="thriller", cats=["thriller"], themes=["crime"], ambiance="sombre")
    prof.recompute_learned(p, [(b, 5)])
    assert p["genres"] == {"thriller": 0.05} and p["ambiances"] == {"sombre": 0.05}  # conservées
    _, d = prof.score_book(p, b, N=0, year=YEAR)
    assert "q1" not in d and "q3" not in d
    assert d["P"] == 100
    assert prof.novelty_for(p, [book(2, themes=["amour"])]) == {2: 100}  # genres appris ignorés


def test_recompute_does_not_depend_on_order():
    p = prof.build_profile(answers(q1=["thriller"]))
    b = book(main="aventure", cats=["aventure"], themes=["voyage"])
    # Une note basse puis une haute : écarts additionnés (0), pas de plancher intermédiaire.
    notes = [(b, 1), (b, 5)]
    first = copy.deepcopy(prof.recompute_learned(p, notes))
    assert prof.recompute_learned(p, notes[::-1]) == first
    assert "aventure" not in p["genres"] and p["themes"] == {}
    # Le plafond s'applique une seule fois, sur la somme : 8 hautes, 2 basses -> +0,30.
    mixed = [(b, 5)] * 8 + [(b, 1)] * 2
    assert prof.recompute_learned(p, mixed)["genres"]["aventure"] == 0.30
    assert prof.recompute_learned(p, mixed[::-1])["genres"]["aventure"] == 0.30


def test_negative_rating_does_not_create():
    p = prof.build_profile(answers(q1=["thriller"]))
    prof.recompute_learned(p, [(book(main="romance", cats=["romance"], themes=["amour"]), 1)])
    assert p["genres"] == {"thriller": 1.0} and p["themes"] == {}


# --- Libellés ----------------------------------------------------------------------------------

@pytest.mark.parametrize("given, expected", [
    ({"q1": ["thriller", "policier"]}, "Suspense & tension"),
    ({"q1": ["dystopie", "science-fiction"]}, "Futurs possibles"),
    ({"q1": ["horreur", "fantastique", "romance"]}, "Mondes de l'ombre"),
    ({"q1": ["essai", "biographie"]}, "Esprits curieux"),
    ({"q1": ["aventure", "roman historique"]}, "Grandes épopées"),
    ({"q1": ["littérature générale", "romance"]}, "Émotions & liens"),
    ({"q1": ["policier", "romance"]}, "Fin limier"),
    # Le libellé suit la famille dominante, pas l'ordre des paires.
    ({"q1": ["romance", "litterature", "thriller_polar"]}, "Émotions & liens"),
    ({"q1": ["thriller_polar", "litterature", "romance"]}, "Émotions & liens"),
    ({"q1": ["essais", "thriller_polar", "romance", "biographies"]}, "Esprits curieux"),
    ({"q1": ["romance", "science_fiction", "fantasy"]}, "Futurs possibles"),
    ({"q1": ["dystopie", "horreur", "thriller"]}, "Veilleur·se lucide"),  # 1er genre de la famille
    ({"q1": ["neutre"], "q3": ["intimiste"]}, "Lecteur·rice sensible"),
    ({"q1": ["autre"], "q3": ["varie"]}, "Éclectique"),
    ({"q1": ["thriller_polar"]}, "Suspense & tension"),
    ({"q1": ["science_fiction"]}, "Futurs possibles"),
    ({"q1": ["biographies", "essais"]}, "Esprits curieux"),
    ({"q1": ["romance"]}, "Cœur tendre"),
])
def test_labels(given, expected):
    p = prof.build_profile(answers(**given))
    assert p["label"] == expected
    assert p["label_description"].startswith("Tu ")
    assert len(p["label_tags"]) == 4


def test_all_labels_complete():
    entries = ([e for _, e in prof.PAIR_LABELS] + list(prof.GENRE_LABELS.values())
               + list(prof.AMBIANCE_PROFILE_LABELS.values()) + [prof.ECLECTIC_LABEL])
    assert len(prof.PAIR_LABELS) == 6 and len(prof.GENRE_LABELS) == 12
    for e in entries:
        assert e["description"].startswith("Tu ") and len(e["tags"]) == 4
        assert e["family"] in prof.FAMILIES


@pytest.mark.parametrize("given, family", [
    ({"q1": ["thriller_polar"]}, "suspense"),
    ({"q1": ["science_fiction", "fantasy"]}, "imaginaire"),
    ({"q1": ["histoire_aventure"]}, "histoire"),
    ({"q1": ["biographies"]}, "réel et idées"),
    ({"q1": ["litterature", "romance"]}, "psychologie"),
    ({"q3": ["intimiste"]}, "psychologie"),
    ({"q1": ["romance", "thriller_polar", "histoire_aventure"]}, "éclectique"),  # 3 à égalité
    ({"q1": ["romance", "litterature", "essais"]}, "psychologie"),        # 2 contre 1
    ({"q1": ["romance", "litterature", "thriller_polar"]}, "psychologie"),
    ({"q1": ["essais", "thriller_polar"]}, "réel et idées"),      # égalité à 2 : premier coché
    ({"q1": ["autre"]}, "éclectique"),
])
def test_family(given, family):
    p = prof.build_profile(answers(**given))
    assert p["family"] == family
    if family == "éclectique":
        assert p["label"] == "Éclectique"


# --- Base ------------------------------------------------------------------------------------

def test_db_profile_and_answers(tmp_path):
    path = tmp_path / "books.db"
    init_db(path)
    with get_connection(path) as conn:
        conn.execute("INSERT INTO users (id, username, email, password_hash)"
                     " VALUES (1, 'lou', 'lou@exemple.fr', 'x')")
    assert load_profile(1, path) is None
    p = prof.build_profile(answers(q1=["thriller", "policier"]))
    save_profile(1, p, path)
    assert load_profile(1, path) == p
    with get_connection(path) as conn:
        row = conn.execute("SELECT profile_label, profile_confidence, profile_family"
                           " FROM users").fetchone()
    assert row["profile_label"] == "Suspense & tension"
    assert row["profile_family"] == "suspense" and load_profile(1, path)["family"] == "suspense"
    assert row["profile_confidence"] == p["confidence"]

    save_answer(1, "q1", ["thriller"], path)
    save_answer(1, "q1", ["thriller", "policier"], path)
    save_answer(1, "q5", "moyen", path)
    assert load_answers(1, path) == {"q1": ["thriller", "policier"], "q5": "moyen"}
