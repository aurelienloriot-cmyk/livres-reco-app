"""Nettoyage et normalisation des données de livres.

Lit data/raw/*.json (produits par src.collect), filtre, dédoublonne et charge
le résultat dans la table books.
"""

import html
import json
import re
import statistics
import unicodedata
from collections import Counter
from pathlib import Path

from src import tagging
from src.stopwords_fr import STOPWORDS_FR
from src.collect import QUERIES, RAW_DIR
from src.db import DB_PATH, get_connection, init_db

MIN_DESCRIPTION_CHARS = 200
MIN_PAGES = 60
MAX_PAGES = 1500
# Comparés au titre normalisé (sans accents), en mots entiers, pluriel accepté.
EXCLUDED_TITLE_WORDS = ["coffret", "pack", "integrale", "guide", "manuel", "methode", "dictionnaire"]
EXCLUDED_TITLE_RE = re.compile(r"\b(" + "|".join(EXCLUDED_TITLE_WORDS) + r")s?\b")

# Non-fiction collectée sous une catégorie fiction (hors biographie et essai).
NONFICTION_MAIN_CATEGORIES = {"biographie", "essai"}
NONFICTION_GOOGLE_TERMS = [
    "literary criticism", "literary collections", "language arts", "education", "study aids",
    "reference", "history", "social science", "philosophy", "religion", "juvenile nonfiction",
]
# Comparés au titre normalisé ; "1837 1900" = plage d'années "1837-1900".
# Comparés à la catégorie Google entière (sans casse) : "Science" mais pas "Science fiction".
NONFICTION_GOOGLE_CATEGORIES = {
    "music", "art", "performing arts", "biography & autobiography", "science",
    "political science", "business", "psychology", "self-help", "law", "medical",
    "technology", "travel", "cooking", "poetry", "drama", "comics",
    "literary criticism & collections", "antiques & collectibles", "architecture",
    "photography", "foreign language study", "games", "crafts & hobbies", "nature",
    "pets", "sports & recreation", "transportation",
}
NONFICTION_TITLE_PATTERNS = [
    "dans le roman", "le roman de", "le roman au", "roman et", "litterature", "anthologies?",
    "etudes?", "histoire du", "histoire de la", "siecles?", r"\d{4} \d{4}",
    "revue", "bulletin", "regards", "critiques?", "catalogue", "exposition", "actes",
    "colloque", "cahiers", "special", "numero", "au cinema", "au theatre",
    "fiction et",
]
NONFICTION_TITLE_RE = re.compile(r"\b(" + "|".join(NONFICTION_TITLE_PATTERNS) + r")\b")
# Mentions entre crochets ou parenthèses (éventuellement non fermées) : "[Nouv. éd. revue".
TITLE_BRACKETS_RE = re.compile(r"\[[^\]]*(\]|$)|\([^)]*(\)|$)")
# Vocabulaire d'étude dans la description (pluriel accepté) : 2 expressions distinctes
# suffisent pour écarter un livre de catégorie fiction.
STUDY_TERMS = [
    "analyse", "etude", "ouvrage collectif", "actes du", "cet ouvrage", "ce volume",
    "chapitre", "bibliographie", "approche", "perspective", "corpus", "contribution",
    "universitaire", "chercheur", "historiographie", "critique litteraire",
]
STUDY_TERM_RES = [re.compile(rf"\b{term}s?\b") for term in STUDY_TERMS]
MIN_STUDY_TERMS = 2

# Contrôle de langue : part minimale de mots vides français dans la description.
MIN_FRENCH_STOPWORD_RATIO = 0.15

# Dédoublonnage secondaire : mots d'édition retirés du titre normalisé.
EDITION_WORDS_RE = re.compile(
    r"\b(texte integral|illustree?|annotee?|edition|nouvelle|version|complete|integrale|bilingue)\b"
)
LONG_TITLE_CHARS = 30  # au-delà, ce qui suit " : " ou " - " est un sous-titre, ignoré
# Mentions d'éditeur glissées parmi les auteurs (comparées en mots entiers, sans accents).
PUBLISHER_AUTHOR_RE = re.compile(r"\b(ligaran|editions?|collectif)\b")

# Texte d'éditeur : phrase de plus de 80 car. présente à l'identique dans au moins
# 3 livres distincts (plusieurs éditions d'un même livre ne comptent qu'une fois).
BOILERPLATE_MIN_CHARS = 80
BOILERPLATE_MIN_BOOKS = 3
# Coupe après . ! ? … éventuellement suivis d'un guillemet fermant.
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+|(?<=[.!?…][\"»”])\s+")

CATEGORY_ORDER = list(QUERIES)  # départage ultime, pour un résultat déterministe


# --- Normalisation -----------------------------------------------------------

def clean_description(text):
    """Supprime les balises HTML, décode les entités et normalise les espaces."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_text(text):
    """'L'Étranger, Sœur !' -> 'l etranger soeur' : minuscules, sans accents ni ponctuation."""
    text = (text or "").lower().replace("œ", "oe").replace("æ", "ae")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


FRENCH_STOPWORDS = {normalize_text(w) for w in STOPWORDS_FR}


def french_stopword_ratio(text):
    """Part des mots du texte qui sont des mots vides français (0 si texte vide)."""
    words = normalize_text(text).split()
    return sum(w in FRENCH_STOPWORDS for w in words) / len(words) if words else 0.0


def parse_year(published_date):
    """'2019-03-01' -> 2019 ; None si les 4 premiers caractères ne sont pas une année."""
    match = re.match(r"\d{4}", published_date or "")
    return int(match.group()) if match else None


def get_isbn(info, kind):
    """kind = 'ISBN_13' ou 'ISBN_10'."""
    for ident in info.get("industryIdentifiers", []):
        if ident.get("type") == kind:
            return ident.get("identifier")
    return None


def clean_authors(authors):
    """Retire les mentions d'éditeur (Ligaran, Éditions…, Collectif) et les entrées vides."""
    return [a.strip() for a in authors or []
            if normalize_text(a) and not PUBLISHER_AUTHOR_RE.search(normalize_text(a))]


# --- Étape 1 : chargement et regroupement par _google_id ---------------------

def load_raw(raw_dir=RAW_DIR):
    """Renvoie tous les items bruts, enrichis de leur requête et de leur rang."""
    items = []
    for path in sorted(Path(raw_dir).glob("*.json")):
        for rank, item in enumerate(json.loads(path.read_text(encoding="utf-8"))):
            items.append({**item, "_query": path.stem, "_rank": rank})
    return items


def merge_into(book, other):
    """Fusionne other dans book : catégories cibles et rangs ; garde la plus longue description."""
    for cat, queries in other["queries"].items():
        book["queries"].setdefault(cat, set()).update(queries)
    for cat, rank in other["ranks"].items():
        book["ranks"][cat] = min(rank, book["ranks"].get(cat, rank))
    if len(other["description"]) > len(book["description"]):
        book["info"] = other["info"]
        book["google_id"] = other["google_id"]
        book["description"] = other["description"]


def group_by_id(items):
    """Regroupe les items par _google_id.

    queries : {catégorie: requêtes ayant renvoyé le livre}
    ranks   : {catégorie: meilleure position du livre dans une de ces requêtes}
    """
    books = {}
    for item in items:
        cat = item["_target_category"]
        info = {k: v for k, v in item.items() if not k.startswith("_")}
        info["authors"] = clean_authors(info.get("authors"))
        entry = {
            "google_id": item["_google_id"],
            "info": info,
            "description": clean_description(info.get("description")),
            "queries": {cat: {item["_query"]}},
            "ranks": {cat: item["_rank"]},
        }
        if entry["google_id"] in books:
            merge_into(books[entry["google_id"]], entry)
        else:
            books[entry["google_id"]] = entry
    return list(books.values())


# --- Étape 2 : texte d'éditeur -----------------------------------------------

def strip_boilerplate(books):
    """Retire des descriptions les phrases répétées dans plusieurs livres
    (présentation de l'éditeur, de la collection…).

    Renvoie (nb de phrases distinctes retirées, nb de descriptions modifiées).
    """
    owners = {}  # phrase -> clés (titre, auteur) des livres qui la contiennent
    for book in books:
        info = book["info"]
        key = (dedupe_title(info.get("title") or ""),
               normalize_text((info.get("authors") or [""])[0]))
        for sentence in SENTENCE_SPLIT_RE.split(book["description"]):
            if len(sentence) > BOILERPLATE_MIN_CHARS:
                owners.setdefault(sentence, set()).add(key)
    boilerplate = {s for s, keys in owners.items() if len(keys) >= BOILERPLATE_MIN_BOOKS}

    modified = 0
    for book in books:
        sentences = SENTENCE_SPLIT_RE.split(book["description"])
        kept = [s for s in sentences if s not in boilerplate]
        if len(kept) < len(sentences):
            book["description"] = " ".join(kept)
            modified += 1
    return len(boilerplate), modified


# --- Étape 3 : filtres --------------------------------------------------------

def is_nonfiction_in_fiction(book):
    """Livre de catégorie fiction dont les catégories Google ou le titre trahissent
    de la non-fiction (critique, histoire, anthologie…)."""
    if main_category(book) in NONFICTION_MAIN_CATEGORIES:
        return False
    categories = [c.lower() for c in book["info"].get("categories", [])]
    google = " | ".join(categories)
    if any(term in google for term in NONFICTION_GOOGLE_TERMS):
        return True
    if NONFICTION_GOOGLE_CATEGORIES & set(categories):
        return True
    title = TITLE_BRACKETS_RE.sub(" ", book["info"]["title"])
    return bool(NONFICTION_TITLE_RE.search(normalize_text(title)))


def has_study_vocabulary(book):
    """Livre de catégorie fiction dont la description emploie un vocabulaire
    d'étude (au moins 2 expressions distinctes de STUDY_TERMS)."""
    if main_category(book) in NONFICTION_MAIN_CATEGORIES:
        return False
    text = normalize_text(book["description"])
    return sum(bool(r.search(text)) for r in STUDY_TERM_RES) >= MIN_STUDY_TERMS


def _has_valid_pages(info):
    pages = info.get("pageCount")
    return isinstance(pages, int) and MIN_PAGES <= pages <= MAX_PAGES


FILTERS = [
    ("langue != fr", lambda b: b["info"].get("language") == "fr"),
    ("titre ou auteurs manquants", lambda b: bool(b["info"].get("title")) and bool(b["info"].get("authors"))),
    (f"description < {MIN_DESCRIPTION_CHARS} car.", lambda b: len(b["description"]) >= MIN_DESCRIPTION_CHARS),
    ("description non française",
     lambda b: french_stopword_ratio(b["description"]) >= MIN_FRENCH_STOPWORD_RATIO),
    (f"pageCount absent ou hors [{MIN_PAGES}, {MAX_PAGES}]", lambda b: _has_valid_pages(b["info"])),
    ("année non parsable", lambda b: parse_year(b["info"].get("publishedDate")) is not None),
    ("titre exclu (coffret, guide…)", lambda b: not EXCLUDED_TITLE_RE.search(normalize_text(b["info"]["title"]))),
    ("non-fiction en catégorie fiction", lambda b: not is_nonfiction_in_fiction(b)),
    ("vocabulaire d'étude", lambda b: not has_study_vocabulary(b)),
]


def apply_filters(books):
    """Applique FILTERS dans l'ordre. Renvoie (livres gardés, {filtre: nb rejets})."""
    rejects = {}
    for name, keep in FILTERS:
        kept = [b for b in books if keep(b)]
        rejects[name] = len(books) - len(kept)
        books = kept
    return books, rejects


# --- Étape 4 : dédoublonnage secondaire ---------------------------------------

def _dedupe_by(books, key_func):
    """Fusionne les livres partageant la même clé (clé None = jamais fusionné)."""
    by_key = {}
    result = []
    for book in books:
        key = key_func(book)
        if key is None:
            result.append(book)
        elif key in by_key:
            merge_into(by_key[key], book)
        else:
            by_key[key] = book
            result.append(book)
    return result


def dedupe_title(title):
    """Titre réduit pour le dédoublonnage : sans sous-titre (titre long) ni mots d'édition.
    "Le Père Goriot : édition illustrée annotée" -> "le pere goriot"."""
    if len(title) > LONG_TITLE_CHARS:
        title = re.split(r" : | - ", title, maxsplit=1)[0]
    reduced = re.sub(r"\s+", " ", EDITION_WORDS_RE.sub(" ", normalize_text(title))).strip()
    return reduced or normalize_text(title)


def title_author_key(book):
    info = book["info"]
    return dedupe_title(info["title"]), normalize_text(info["authors"][0])


def dedupe(books):
    """Même ISBN-13, puis même (titre normalisé, premier auteur normalisé)."""
    books = _dedupe_by(books, lambda b: get_isbn(b["info"], "ISBN_13"))
    return _dedupe_by(books, title_author_key)


# --- Étape 5 : catégories -----------------------------------------------------

def main_category(book):
    """Catégorie cible la plus fréquente ; à égalité, celle dont la requête
    a renvoyé le livre le plus tôt (puis l'ordre de QUERIES)."""
    def sort_key(cat):
        order = CATEGORY_ORDER.index(cat) if cat in CATEGORY_ORDER else len(CATEGORY_ORDER)
        return (-len(book["queries"][cat]), book["ranks"][cat], order)
    return min(book["queries"], key=sort_key)


def sorted_categories(book):
    return sorted(book["queries"], key=lambda c: (c != main_category(book), c))


# --- Étape 6 : chargement SQLite ----------------------------------------------

def to_row(book):
    info = book["info"]
    return {
        "google_id": book["google_id"],
        "title": info["title"],
        "authors": json.dumps(info["authors"], ensure_ascii=False),
        "description": book["description"],
        "categories_raw": json.dumps(info.get("categories", []), ensure_ascii=False),
        "main_category": main_category(book),
        "categories": json.dumps(sorted_categories(book), ensure_ascii=False),
        "themes": "[]",
        "ambiance": "null",
        "published_year": parse_year(info.get("publishedDate")),
        "page_count": info["pageCount"],
        "language": info.get("language"),
        "isbn": get_isbn(info, "ISBN_13") or get_isbn(info, "ISBN_10"),
        "thumbnail": info.get("imageLinks", {}).get("thumbnail"),
        "info_link": info.get("infoLink"),
        "avg_rating": info.get("averageRating"),
        "ratings_count": info.get("ratingsCount"),
    }


def load_books(rows, db_path=DB_PATH):
    """Vide la table books puis insère les lignes."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM books")
        if rows:
            columns = list(rows[0])
            conn.executemany(
                f"INSERT INTO books ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
                [tuple(r[c] for c in columns) for r in rows],
            )
    return len(rows)


# --- Pipeline et rapport ------------------------------------------------------

def run(raw_dir=RAW_DIR, db_path=DB_PATH):
    items = load_raw(raw_dir)
    books = group_by_id(items)
    report = {"raw": len(items), "distinct": len(books)}
    report["boilerplate"] = strip_boilerplate(books)
    books, report["rejects"] = apply_filters(books)
    before = len(books)
    books = dedupe(books)
    report["duplicates"] = before - len(books)
    rows = [to_row(b) for b in books]
    report["loaded"] = load_books(rows, db_path)
    report["rows"] = rows
    report["tagging"] = tagging.run(db_path)
    return report


def print_report(report):
    rows = report["rows"]
    print(f"Items bruts            : {report['raw']}")
    print(f"Livres distincts (id)  : {report['distinct']}")
    sentences, descriptions = report["boilerplate"]
    print(f"Texte d'éditeur        : {sentences} phrases retirées de {descriptions} descriptions")
    print("Rejets par filtre :")
    for name, count in report["rejects"].items():
        print(f"  - {name:<36} {count:>5}")
    print(f"Doublons secondaires   : {report['duplicates']}")
    print(f"Livres chargés         : {report['loaded']}")
    if not rows:
        return
    print("Répartition par main_category :")
    for cat, count in Counter(r["main_category"] for r in rows).most_common():
        print(f"  - {cat:<22} {count:>5}")
    print(f"Médiane pageCount      : {statistics.median(r['page_count'] for r in rows)}")
    print("Années par décennie :")
    decades = Counter(r["published_year"] // 10 * 10 for r in rows)
    for decade in sorted(decades):
        print(f"  - {decade}s {decades[decade]:>5}")


def main():
    report = run()
    print_report(report)
    print("\n--- Tagging ---")
    tagging.print_report(report["tagging"])


if __name__ == "__main__":
    main()
