import json

from src import clean

LONG_DESC = "Une histoire captivante. " * 10  # > 200 caractères


def raw_item(gid, category, query="q", rank=0, **info):
    base = {
        "title": "Le Livre",
        "authors": ["Jean Dupont"],
        "description": LONG_DESC,
        "pageCount": 300,
        "publishedDate": "2015-04-01",
        "language": "fr",
    }
    base.update(info)
    return {**base, "_google_id": gid, "_target_category": category, "_query": query, "_rank": rank}


def book(**info):
    return clean.group_by_id([raw_item("x", "thriller", **info)])[0]


# --- Nettoyage HTML ------------------------------------------------------------

def test_clean_description_removes_html_and_entities():
    text = "<p>Un <b>roman</b>&nbsp;noir</p><br/>\n\n  d&#39;exception &amp; culte"
    assert clean.clean_description(text) == "Un roman noir d'exception & culte"


def test_clean_description_handles_none():
    assert clean.clean_description(None) == ""


# --- Normalisation -------------------------------------------------------------

def test_normalize_text_removes_accents_and_punctuation():
    assert clean.normalize_text("L'Étranger : roman !") == "l etranger roman"
    assert clean.normalize_text("Les Misérables") == clean.normalize_text("LES MISERABLES")


def test_parse_year():
    assert clean.parse_year("2019-03-01") == 2019
    assert clean.parse_year("1998") == 1998
    assert clean.parse_year("19??") is None
    assert clean.parse_year(None) is None


# --- Filtres -------------------------------------------------------------------

def test_valid_book_passes_all_filters():
    kept, rejects = clean.apply_filters([book()])
    assert len(kept) == 1
    assert sum(rejects.values()) == 0


def test_each_filter_rejects():
    cases = {
        "langue != fr": book(language="en"),
        "titre ou auteurs manquants": book(authors=[]),
        "description < 200 car.": book(description="<p>" + "a" * 150 + "</p>" + " " * 100),
        "pageCount absent ou hors [60, 1500]": book(pageCount=40),
        "année non parsable": book(publishedDate=""),
        "titre exclu (coffret, guide…)": book(title="Coffret Harry Potter"),
    }
    for name, b in cases.items():
        kept, rejects = clean.apply_filters([b])
        assert kept == [], name
        assert rejects[name] == 1, name


def test_filters_are_counted_in_order():
    # Rejeté par la langue : ne doit pas être compté aussi pour la description.
    kept, rejects = clean.apply_filters([book(language="en", description="court")])
    assert rejects["langue != fr"] == 1
    assert rejects["description < 200 car."] == 0


def test_excluded_title_words():
    assert clean.EXCLUDED_TITLE_RE.search(clean.normalize_text("L'Intégrale des Rougon"))
    assert clean.EXCLUDED_TITLE_RE.search(clean.normalize_text("Le guide du routard"))
    assert clean.EXCLUDED_TITLE_RE.search(clean.normalize_text("Méthodes de lecture"))
    assert not clean.EXCLUDED_TITLE_RE.search(clean.normalize_text("Le Guidon"))
    assert not clean.EXCLUDED_TITLE_RE.search(clean.normalize_text("Package"))


# --- Regroupement et dédoublonnage --------------------------------------------

def test_group_by_id_merges_target_categories():
    items = [
        raw_item("a", "thriller", query="t1", rank=5),
        raw_item("a", "policier", query="p1", rank=2),
        raw_item("a", "thriller", query="t2", rank=9),
        raw_item("b", "romance"),
    ]
    books = {b["google_id"]: b for b in clean.group_by_id(items)}
    assert len(books) == 2
    assert books["a"]["queries"] == {"thriller": {"t1", "t2"}, "policier": {"p1"}}
    assert books["a"]["ranks"] == {"thriller": 5, "policier": 2}


def test_dedupe_by_isbn_keeps_longest_description():
    isbn = [{"type": "ISBN_13", "identifier": "9782070360024"}]
    items = [
        raw_item("a", "thriller", title="Titre A", industryIdentifiers=isbn),
        raw_item("b", "policier", title="Titre B", industryIdentifiers=isbn, description=LONG_DESC * 2),
    ]
    books = clean.dedupe(clean.group_by_id(items))
    assert len(books) == 1
    assert books[0]["google_id"] == "b"
    assert set(books[0]["queries"]) == {"thriller", "policier"}


def test_dedupe_by_normalized_title_and_first_author():
    items = [
        raw_item("a", "thriller", title="L'Étranger", authors=["Albert Camus"]),
        raw_item("b", "thriller", title="L ETRANGER !", authors=["albert camus", "Autre"]),
        raw_item("c", "thriller", title="L'Étranger", authors=["Quelqu'un d'autre"]),
    ]
    books = clean.dedupe(clean.group_by_id(items))
    assert sorted(b["google_id"] for b in books) == ["a", "c"]


# --- main_category -------------------------------------------------------------

def test_main_category_most_frequent():
    items = [
        raw_item("a", "policier", query="p1", rank=0),
        raw_item("a", "thriller", query="t1", rank=10),
        raw_item("a", "thriller", query="t2", rank=12),
    ]
    assert clean.main_category(clean.group_by_id(items)[0]) == "thriller"


def test_main_category_tie_uses_best_rank():
    items = [
        raw_item("a", "thriller", query="t1", rank=7),
        raw_item("a", "policier", query="p1", rank=3),
    ]
    b = clean.group_by_id(items)[0]
    assert clean.main_category(b) == "policier"
    assert json.loads(clean.to_row(b)["categories"]) == ["policier", "thriller"]


# --- Pipeline complet ----------------------------------------------------------

def test_run_loads_into_sqlite(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    items = [
        {k: v for k, v in raw_item("a", "thriller", industryIdentifiers=[
            {"type": "ISBN_10", "identifier": "2070360024"}]).items() if k not in ("_query", "_rank")},
        {k: v for k, v in raw_item("b", "thriller", language="en").items() if k not in ("_query", "_rank")},
    ]
    (raw_dir / "thriller__q.json").write_text(json.dumps(items), encoding="utf-8")
    db_path = tmp_path / "books.db"

    report = clean.run(raw_dir, db_path)

    assert report["raw"] == 2 and report["loaded"] == 1
    with clean.get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM books").fetchone()
    assert row["isbn"] == "2070360024"
    assert row["main_category"] == "thriller"
    assert json.loads(row["categories"]) == ["thriller"]
    assert row["themes"] == "[]" and row["published_year"] == 2015


# --- Non-fiction en catégorie fiction -----------------------------------------

def nf_book(title, main="thriller", google=()):
    return {"info": {"title": title, "categories": list(google)},
            "queries": {main: {"q"}}, "ranks": {main: 0}}


def test_nonfiction_by_google_category():
    assert clean.is_nonfiction_in_fiction(nf_book("X", google=["Literary Criticism / European"]))
    assert not clean.is_nonfiction_in_fiction(nf_book("X", google=["Fiction / Thrillers"]))


def test_nonfiction_by_title():
    assert clean.is_nonfiction_in_fiction(nf_book("Le roman d'aventures au Québec, 1837-1900"))
    assert clean.is_nonfiction_in_fiction(nf_book("Le roman policier au XIXe siècle"))
    assert clean.is_nonfiction_in_fiction(nf_book("Présences du passé dans le roman français"))
    assert not clean.is_nonfiction_in_fiction(nf_book("La Vérité sur l'affaire Harry Quebert"))


def test_nonfiction_allowed_for_biography_and_essay():
    assert not clean.is_nonfiction_in_fiction(nf_book("Une étude", main="essai", google=["History"]))


def test_normalize_text_handles_ligatures():
    assert clean.normalize_text("Sœur Ælis") == "soeur aelis"
