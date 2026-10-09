"""Moteur de recommandation TF-IDF + similarité cosinus.

Chaque livre est représenté par un vecteur TF-IDF de son texte : description,
puis catégorie principale, catégories et thèmes répétés 2 fois pour peser plus.
Les vecteurs sont normalisés (L2) : le produit scalaire de deux vecteurs est
directement leur cosinus.

- similar_books : livres proches d'un livre, avec score et explication.
- centroid / novelty : indice de nouveauté N d'un livre par rapport à des lectures.

L'index est construit au premier appel, gardé en mémoire et sauvegardé dans
data/tfidf.pkl ; il est reconstruit si le catalogue a changé.

Usage : python -m src.engine "titre partiel"
"""

import hashlib
import json
import pickle
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer, strip_accents_unicode

from src.db import DB_PATH, get_connection
from src.stopwords_fr import STOPWORDS_FR

TAG_REPEAT = 2          # répétitions de catégories et thèmes dans le texte indexé
COSINE_WEIGHT = 0.8     # score = 0,8 × cosinus + 0,2 × Jaccard
JACCARD_WEIGHT = 0.2
MIN_RATINGS = 5         # nombre d'avis requis pour départager par la note moyenne
SHARED_TERMS = 3        # termes TF-IDF cités dans l'explication
MIN_TERM_LENGTH = 4     # termes plus courts jamais cités dans l'explication

THEME_LABELS = {"amitie": "amitié", "societe": "société", "memoire": "mémoire"}

TOKEN_RE = re.compile(r"(?u)\b\w\w+\b")  # découpage par défaut de TfidfVectorizer


def normalize(text):
    """Minuscules et sans accents, comme le texte indexé."""
    return strip_accents_unicode(text.lower())


STOPWORDS = sorted({normalize(word) for word in STOPWORDS_FR})


@dataclass
class Filters:
    """Contraintes appliquées aux candidats avant le classement.

    Un critère vide (None ou ensemble vide) n'est pas appliqué. Un livre sans
    année (ou sans nombre de pages) est écarté dès qu'un critère d'année (ou de
    pages) est donné. L'exclusion de catégories prime sur l'inclusion.
    """
    categories_in: set = field(default_factory=set)   # au moins une de ces catégories
    categories_out: set = field(default_factory=set)  # aucune de ces catégories
    languages: set = field(default_factory=set)       # codes langue acceptés (books.language)
    year_min: int | None = None
    year_max: int | None = None
    max_pages: int | None = None
    exclude_ids: set = field(default_factory=set)

    def accepts(self, book):
        cats = book_categories(book)
        if self.categories_in and not cats & set(self.categories_in):
            return False
        if self.categories_out and cats & set(self.categories_out):
            return False
        if book["id"] in self.exclude_ids:
            return False
        if self.languages and book["language"] not in self.languages:
            return False
        year, pages = book["published_year"], book["page_count"]
        if self.year_min is not None and (year is None or year < self.year_min):
            return False
        if self.year_max is not None and (year is None or year > self.year_max):
            return False
        if self.max_pages is not None and (pages is None or pages > self.max_pages):
            return False
        return True


# --- Index ----------------------------------------------------------------------

@dataclass
class Index:
    books: list            # dicts livres, dans l'ordre des lignes de la matrice
    row_of: dict           # id livre -> numéro de ligne
    matrix: object         # matrice creuse TF-IDF (n livres × n termes), lignes normalisées L2
    terms: np.ndarray      # terme de chaque colonne
    display: dict          # terme normalisé -> forme accentuée la plus fréquente


_CACHE = {}  # chemin de la base -> Index


def book_categories(book):
    return set(book["categories"]) | {book["main_category"]}


def book_tags(book):
    return book_categories(book) | set(book["themes"])


def load_books(db_path):
    """Livres du catalogue, hors livres masqués (src.hide) : absents de l'index, ils ne
    sont ni recommandés, ni trouvés par la recherche, ni proposés à l'accueil."""
    with get_connection(db_path) as conn:
        rows = conn.execute("SELECT * FROM books WHERE hidden = 0 ORDER BY id").fetchall()
    return [decode_book(row) for row in rows]


def decode_book(row):
    """Ligne de la table books -> dict, champs JSON décodés."""
    book = dict(row)
    for key in ("authors", "categories", "themes"):
        book[key] = json.loads(book[key]) if book[key] else []
    book["ambiance"] = json.loads(book["ambiance"]) if book["ambiance"] else None
    return book


def load_book(book_id, db_path=DB_PATH):
    """Un livre, masqué ou non (hors index), ou None."""
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    return decode_book(row) if row else None


def book_text(book):
    tags = [book["main_category"], *book["categories"], *book["themes"]]
    return " ".join([book["description"] or ""] + [t for t in tags if t] * TAG_REPEAT)


def fingerprint(books, texts):
    """Empreinte des ids et des textes indexés : change si un livre est ajouté,
    retiré, ou si sa description / ses thèmes changent."""
    digest = hashlib.sha1()
    for book, text in zip(books, texts):
        digest.update(f"{book['id']}\x00{text}\x01".encode())
    return digest.hexdigest()


def display_forms(texts):
    """Associe chaque mot normalisé à sa forme accentuée la plus fréquente
    ("ile" -> "île"), pour des explications lisibles."""
    forms = defaultdict(Counter)
    for text in texts:
        for token in TOKEN_RE.findall(text.lower()):
            forms[normalize(token)][token] += 1
    return {term: counter.most_common(1)[0][0] for term, counter in forms.items()}


def build_index(texts):
    vectorizer = TfidfVectorizer(
        stop_words=STOPWORDS, min_df=2, max_df=0.8, sublinear_tf=True,
        strip_accents="unicode", norm="l2",
    )
    matrix = vectorizer.fit_transform(texts).tocsr()
    terms = vectorizer.get_feature_names_out()
    forms = display_forms(texts)
    display = {term: forms.get(term, term) for term in terms}
    return matrix, terms, display


def get_index(db_path=DB_PATH):
    """Index du catalogue : mémoire, sinon data/tfidf.pkl s'il est à jour, sinon construit."""
    key = str(db_path)
    if key in _CACHE:
        return _CACHE[key]

    books = load_books(db_path)
    texts = [book_text(b) for b in books]
    current = fingerprint(books, texts)
    pkl_path = Path(db_path).parent / "tfidf.pkl"

    saved = None
    if pkl_path.exists():
        with open(pkl_path, "rb") as f:
            saved = pickle.load(f)
        if saved.get("n_books") != len(books) or saved.get("fingerprint") != current:
            saved = None
    if saved is None:
        matrix, terms, display = build_index(texts)
        saved = {"n_books": len(books), "fingerprint": current,
                 "matrix": matrix, "terms": terms, "display": display}
        with open(pkl_path, "wb") as f:
            pickle.dump(saved, f)

    index = Index(books, {b["id"]: i for i, b in enumerate(books)},
                  saved["matrix"], saved["terms"], saved["display"])
    _CACHE[key] = index
    return index


def reset_cache():
    """Vide le cache mémoire (tests, ou après une mise à jour du catalogue)."""
    _CACHE.clear()


# --- Livres similaires -------------------------------------------------------------

def jaccard(a, b):
    return len(a & b) / len(a | b) if a | b else 0.0


def rating_key(book):
    """Note moyenne pour départager, seulement si assez d'avis."""
    if (book["ratings_count"] or 0) >= MIN_RATINGS and book["avg_rating"] is not None:
        return book["avg_rating"]
    return -1.0


def similar_books(book_id, n=5, filters=None, db_path=DB_PATH):
    """Les n livres les plus proches de book_id : [{book, score, explanation}].

    score = 0,8 × cosinus TF-IDF + 0,2 × Jaccard(catégories ∪ thèmes).
    """
    index = get_index(db_path)
    if book_id not in index.row_of:
        raise KeyError(f"livre inconnu : {book_id}")
    source = index.books[index.row_of[book_id]]
    filters = filters or Filters()

    rows = [i for i, b in enumerate(index.books)
            if b["id"] != book_id and filters.accepts(b)]
    if not rows:
        return []

    source_vec = index.matrix[index.row_of[book_id]]
    cosines = (index.matrix[rows] @ source_vec.T).toarray().ravel()
    source_tags = book_tags(source)

    scored = []
    for row, cosine in zip(rows, cosines):
        book = index.books[row]
        score = COSINE_WEIGHT * cosine + JACCARD_WEIGHT * jaccard(source_tags, book_tags(book))
        scored.append((round(score, 6), rating_key(book), -book["id"], row))
    scored.sort(reverse=True)

    return [{"book": index.books[row], "score": score,
             "explanation": explain(index, source, index.books[row])}
            for score, _, _, row in scored[:n]]


# --- Explication ---------------------------------------------------------------------

def join_fr(items):
    """["a", "b", "c"] -> "a, b et c"."""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " et " + items[-1]


def labelled(prefix_one, prefix_many, labels):
    return f"{prefix_one if len(labels) == 1 else prefix_many} {join_fr(labels)}"


def explain(index, source, candidate):
    """Phrase expliquant la recommandation : thèmes et catégories communs, puis
    les termes TF-IDF qui pèsent le plus dans les deux livres."""
    themes = [t for t in source["themes"] if t in candidate["themes"]]
    cand_cats = book_categories(candidate)
    categories = [c for c in dict.fromkeys([source["main_category"], *source["categories"]])
                  if c in cand_cats]

    parts = []
    if themes:
        parts.append(labelled("le thème", "les thèmes", [THEME_LABELS.get(t, t) for t in themes]))
    if categories:
        parts.append(labelled("la catégorie", "les catégories", categories))

    cited = {word for label in themes + categories for word in TOKEN_RE.findall(normalize(label))}
    shared = index.matrix[index.row_of[source["id"]]].multiply(
        index.matrix[index.row_of[candidate["id"]]]).tocoo()
    top = sorted(zip(shared.data, shared.col), reverse=True)
    words = [index.display[index.terms[col]] for _, col in top
             if index.terms[col] not in cited
             and len(index.terms[col]) >= MIN_TERM_LENGTH][:SHARED_TERMS]
    if words:
        parts.append(labelled("le mot", "les mots", [f"« {w} »" for w in words]))

    if not parts:
        return f"Recommandé pour sa proximité de vocabulaire avec « {source['title']} »."
    return f"Recommandé pour {join_fr(parts)}."


# --- Nouveauté -------------------------------------------------------------------------

def centroid(book_ids, weights=None, db_path=DB_PATH):
    """Vecteur moyen (pondéré) des livres donnés ; None si aucun livre connu."""
    index = get_index(db_path)
    weights = [1.0] * len(book_ids) if weights is None else list(weights)
    pairs = [(index.row_of[b], w) for b, w in zip(book_ids, weights) if b in index.row_of]
    total = sum(w for _, w in pairs)
    if not pairs or total <= 0:
        return None
    rows, w = zip(*pairs)
    vec = np.asarray(index.matrix[list(rows)].T @ np.array(w)).ravel() / total
    return vec


def novelty(centroid_vec, candidate_ids, db_path=DB_PATH):
    """{id: N} avec N = 100 × (1 − cosinus(centroïde, livre)), dans [0, 100].

    None si le centroïde est absent ou nul : le profil gère alors le repli.
    """
    if centroid_vec is None:
        return None
    norm = np.linalg.norm(centroid_vec)
    if norm == 0:
        return None
    index = get_index(db_path)
    ids = [b for b in candidate_ids if b in index.row_of]
    if not ids:
        return {}
    cosines = index.matrix[[index.row_of[b] for b in ids]] @ (centroid_vec / norm)
    return {b: float(np.clip(100 * (1 - c), 0, 100)) for b, c in zip(ids, np.ravel(cosines))}


# --- Recherche -------------------------------------------------------------------------

APOSTROPHES = str.maketrans("’‘´", "'''")
MIN_EXACT = 5           # en dessous, la recherche complète par des résultats approchés
FUZZY_RATIO = 0.8       # difflib.SequenceMatcher : ressemblance minimale de la chaîne entière
FUZZY_MIN_WORD = 5      # mots plus courts : correspondance exacte exigée (hugo ≠ hugh)


def search_text(text):
    """Texte de recherche : apostrophes typographiques -> ', minuscules, sans accents."""
    return normalize(text.translate(APOSTROPHES))


def one_edit(a, b):
    """Vrai si a et b sont à distance de Levenshtein ≤ 1."""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    if len(a) == len(b):
        return a[i + 1:] == b[i + 1:]
    return a[i:] == b[i + 1:]


def close_words(query_words, text_words):
    """Chaque mot de la requête a un mot proche (≤ 1 faute, exact si court) dans le texte."""
    return bool(query_words) and all(
        any(w == t or (len(w) >= FUZZY_MIN_WORD and one_edit(w, t)) for t in text_words)
        for w in query_words)


def approximate(q, text):
    """Ressemblance de la requête avec un titre ou un auteur normalisé (0 si trop loin)."""
    ratio = SequenceMatcher(None, q, text).ratio()
    if ratio >= FUZZY_RATIO or close_words(TOKEN_RE.findall(q), TOKEN_RE.findall(text)):
        return ratio
    return 0.0


def search_books(index, query, accepts=None):
    """(exacts, approchés). Exacts : le titre, sinon un auteur, contient la requête
    (sans accents, casse ni apostrophes typographiques). Moins de MIN_EXACT exacts :
    complétés par les livres dont le titre ou un auteur approche la requête, du plus
    proche au moins proche. accepts : filtre facultatif appliqué aux deux listes."""
    q = search_text(query).strip()
    books = [b for b in index.books if accepts is None or accepts(b)]
    by_title = [b for b in books if q in search_text(b["title"])]
    by_author = [b for b in books if b not in by_title
                 and any(q in search_text(a) for a in b["authors"])]
    exact = by_title + by_author
    if len(exact) >= MIN_EXACT or not q:
        return exact, []
    found = {b["id"] for b in exact}
    scored = []
    for b in books:
        if b["id"] not in found:
            score = max(approximate(q, search_text(t)) for t in [b["title"], *b["authors"]])
            if score > 0:
                scored.append((-score, b["id"], b))
    scored.sort(key=lambda item: item[:2])
    return exact, [b for _, _, b in scored]


def find_book(index, query):
    """Résultats exacts puis approchés de search_books, en une seule liste."""
    exact, approx = search_books(index, query)
    return exact + approx


# --- CLI -------------------------------------------------------------------------------


def main(argv):
    if len(argv) != 1:
        print('Usage : python -m src.engine "titre partiel"')
        return 1
    start = time.perf_counter()
    index = get_index()
    load_ms = (time.perf_counter() - start) * 1000

    matches = find_book(index, argv[0])
    if not matches:
        print(f"Aucun livre ne correspond à « {argv[0]} ».")
        return 1
    source = matches[0]
    if len(matches) > 1:
        print(f"{len(matches)} livres correspondent, premier retenu. Autres : "
              + " ; ".join(f"{b['title']} ({', '.join(b['authors'])})" for b in matches[1:6]))

    start = time.perf_counter()
    results = similar_books(source["id"])
    calc_ms = (time.perf_counter() - start) * 1000

    authors = ", ".join(source["authors"])
    print(f"\nSource : {source['title']} — {authors} [{source['main_category']}, "
          f"{source['published_year']}] thèmes : {', '.join(source['themes']) or '-'}\n")
    for rank, r in enumerate(results, 1):
        b = r["book"]
        print(f"{rank}. {b['title']} — {', '.join(b['authors'])} "
              f"[{b['main_category']}, {b['published_year']}]  score {r['score']:.3f}")
        print(f"   {r['explanation']}")
    print(f"\nChargement de l'index : {load_ms:.0f} ms ; calcul : {calc_ms:.1f} ms "
          f"({len(index.books)} livres, {len(index.terms)} termes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
