import json

from src import tagging
from src.db import get_connection, init_db

THEMES = tagging.compile_lexicon(tagging.THEMES)
AMBIANCES = tagging.compile_lexicon(tagging.ambiance_lexicon())


def tag(description):
    return tagging.tag(description, THEMES, AMBIANCES)


# --- Normalisation et correspondance ------------------------------------------

def test_normalize_removes_accents_case_and_ligatures():
    assert tagging.normalize("Sœur, l'Enquête À Paris !") == "soeur l enquete a paris"


def test_prefix_matches_only_at_word_start():
    pattern = tagging.keyword_pattern("enquet")
    assert pattern.search("une enquete") and pattern.search("l enqueteur")
    assert not tagging.keyword_pattern("art").search("le depart")


def test_whole_word_keyword_accepts_plural_only():
    pattern = tagging.keyword_pattern("reve$")
    assert pattern.search("un reve") and pattern.search("ses reves")
    assert not pattern.search("revenir") and not pattern.search("reveler")


def test_multiword_keyword():
    assert tagging.keyword_pattern("compte a rebours").search("un compte a rebours infernal")


def test_longest_keyword_wins_at_same_position():
    hits = tagging.count_hits("leur amitie", THEMES["amitie"])
    assert hits == {"amitie": 1}


# --- Thèmes -------------------------------------------------------------------

def test_theme_needs_two_distinct_keywords():
    themes, _ = tag("Une enquête, encore une enquête, toujours une enquête.")
    assert "crime" not in themes
    themes, _ = tag("Une enquête sur le meurtre d'un notable.")
    assert themes == ["crime"]


def test_themes_ranked_by_occurrences_and_capped():
    description = (
        "Un inspecteur enquête sur un meurtre ; le tueur cible chaque victime. "
        "La famille du père et de la mère est déchirée. "
        "La guerre et ses soldats. Le secret et le mensonge. "
        "Un voyage en navire vers une île."
    )
    themes, _ = tag(description)
    assert len(themes) == tagging.MAX_THEMES
    assert themes[0] == "crime" and themes[1] == "famille"


def test_no_theme_on_neutral_text():
    assert tag("Un livre de deux cents pages publié chez un éditeur.") == ([], None)


# --- Ambiance -----------------------------------------------------------------

def test_single_ambiance_best_represented():
    _, ambiance = tag("Un suspense haletant, une menace constante et une tension sombre.")
    assert ambiance == "tendue"


def test_ambiance_null_below_threshold():
    _, ambiance = tag("Un roman sombre sur la vie de bureau.")
    assert ambiance is None


def test_single_strong_keyword_is_enough():
    _, ambiance = tag("Un roman drôle sur la vie de bureau.")
    assert ambiance == "legere"
    _, ambiance = tag("Un récit glaçant.")
    assert ambiance == "sombre"


def test_strong_keyword_enters_ambiance_lexicon():
    lexicon = tagging.ambiance_lexicon({"sombre": ["sombre"]}, {"sombre": ["macabre", "sombre"]})
    assert lexicon == {"sombre": ["sombre", "macabre"]}


def test_ambiance_null_on_perfect_tie():
    _, ambiance = tag("Un récit drôle et cocasse, mais aussi sombre et noir.")
    assert ambiance is None


def test_ambiance_best_among_qualified():
    _, ambiance = tag("Une comédie drôle, pleine d'humour, au détour d'un cauchemar.")
    assert ambiance == "legere"


# --- Garde-fou et pipeline ----------------------------------------------------

def test_too_frequent_keywords_are_excluded():
    lexicon = {"crime": ["enquet", "meurtre", "police"]}
    texts = ["une enquete", "l enqueteur", "la police", "un meurtre"]
    assert tagging.too_frequent(texts, [lexicon]) == {"enquet": 0.5}


def test_tag_books_drops_generic_keyword():
    themes = {"crime": ["enquet", "meurtre", "police"]}
    books = [(1, "Une enquête de police."), (2, "Une enquête."), (3, "Une enquête."),
             (4, "Une enquête."), (5, "Un meurtre, la police.")]
    books += [(i, "Un roman.") for i in range(6, 11)]
    tags, excluded = tagging.tag_books(books, themes=themes, ambiances={}, strong={})
    assert list(excluded) == ["enquet"]
    assert tags[1] == ([], None) and tags[5] == (["crime"], None)


def test_run_writes_json_columns(tmp_path):
    db_path = tmp_path / "books.db"
    init_db(db_path)
    with get_connection(db_path) as conn:
        conn.executemany(
            "INSERT INTO books (id, title, description) VALUES (?, ?, ?)",
            [(1, "A", "Un commissaire traque un assassin ; suspense haletant et danger."),
             (2, "B", "Un conte onirique où la magie et le rêve se mêlent."),
             (3, "C", "Recueil de recettes."),
             (4, "D", "Un ouvrage."), (5, "E", "Un autre ouvrage.")],
        )
    tagging.run(db_path)
    with get_connection(db_path) as conn:
        rows = {r["id"]: r for r in conn.execute("SELECT id, themes, ambiance FROM books")}
    assert json.loads(rows[1]["themes"]) == ["crime"] and json.loads(rows[1]["ambiance"]) == "tendue"
    assert json.loads(rows[2]["ambiance"]) == "poetique"
    assert json.loads(rows[3]["themes"]) == [] and json.loads(rows[3]["ambiance"]) is None
