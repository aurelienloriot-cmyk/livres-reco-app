"""Données de l'accueil (testables sans Flask).

- current_reading : lecture du moment.
- pour_toi : recommandations du barème hors bibliothèque, avec la popularité de groupe.
- lecteurs_comme_toi / populaires_semaine : sections communautaires.
- family_selection : remplaçante des sections communautaires sous MIN_READERS lecteurs.
- univers : 3 univers tirés des attributs les mieux pondérés du profil.
- renouveler : réordonne les meilleurs en pénalisant les livres déjà proposés.
- reason : phrase d'explication sur la fiche, selon la section d'origine.
- scores_for / affinity / affinity_level : badge « S % d'affinité » de toutes les cartes.
"""

import dataclasses
import json
import math
from collections import Counter
from datetime import date, timedelta

from src import db, engine
from src.db import DB_PATH
from src.engine import book_categories, join_fr
from src.profile import (ECLECTIC, FAMILY_OF, GENRE_LABELS, MAX_PER_CATEGORY, explain,
                         novelty_for, recommend, score_book)
from src.questions import AMBIANCE_LABELS, CATEGORY_LABELS, THEME_LABELS

MIN_READERS = 5     # lecteurs requis pour afficher une section communautaire
WEEK_DAYS = 7       # popularité : start_date entre J-6 et J
RENEW_POOL = 24     # « Renouveler » puise dans les 24 meilleurs
RENEW_PENALTY = 100.0  # points retirés au score S à chaque proposition précédente
UNIVERSES = 3
# Couleur du badge d'affinité : seuils de S arrondi (niveau 1 = le plus fort).
AFFINITY_LEVELS = (80, 60, 40)

FAMILY_CATEGORIES = {}
for _cat, _family in FAMILY_OF.items():
    FAMILY_CATEGORIES.setdefault(_family, []).append(_cat)

# Familles voisines, pour compléter les univers (de la plus proche à la moins proche).
NEIGHBORS = {
    "psychologie": ["histoire", "réel et idées", "suspense"],
    "suspense": ["imaginaire", "psychologie", "histoire"],
    "imaginaire": ["suspense", "histoire", "psychologie"],
    "histoire": ["imaginaire", "réel et idées", "psychologie"],
    "réel et idées": ["histoire", "psychologie", "suspense"],
    ECLECTIC: ["psychologie", "suspense", "imaginaire", "histoire", "réel et idées"],
}

THEME_UNIVERSES = {
    "famille": ("Secrets de famille", "Des liens, des héritages et des non-dits qui se transmettent."),
    "amour": ("Cœurs battants", "Des rencontres, des passions et des histoires d'amour."),
    "amitie": ("À la vie, à la mort", "Des amitiés fortes qui changent le cours d'une vie."),
    "guerre": ("Sous le feu", "Des destins pris dans la tourmente des conflits."),
    "crime": ("Scènes de crime", "Des enquêtes, des indices et des coupables à démasquer."),
    "voyage": ("Grands départs", "Des routes, des ailleurs et des voyages qui transforment."),
    "societe": ("Miroirs du monde", "Des récits qui interrogent notre société et ses règles."),
    "science": ("Esprits scientifiques", "La science et la technologie au cœur de l'histoire."),
    "nature": ("Nature sauvage", "Des paysages, des bêtes et une nature qui a son mot à dire."),
    "memoire": ("Traces du passé", "Des destins historiques et une mémoire qui ne s'efface pas."),
    "deuil": ("Après la perte", "Des personnages qui apprennent à vivre avec l'absence."),
    "secret": ("Ce qu'on cache", "Des secrets bien gardés qui finissent par remonter."),
    "initiation": ("Grandir", "Des passages à l'âge adulte et des premières fois."),
    "art": ("Âmes d'artistes", "Des créateurs, des œuvres et la beauté qui obsède."),
    "survie": ("Rester en vie", "Des héros poussés à bout, qui luttent pour s'en sortir."),
}

AMBIANCE_UNIVERSES = {
    "sombre": ("Côté obscur", "Des récits noirs qui explorent la part d'ombre."),
    "tendue": ("Haletant", "Des lectures qui te gardent sous tension jusqu'au bout."),
    "legere": ("Bonne humeur", "Des livres drôles et réconfortants, pour sourire."),
    "intimiste": ("Au plus près", "Des récits intimes, au cœur de la psychologie des personnages."),
    "epique": ("Souffle épique", "De grandes fresques qui t'emmènent loin."),
    "poetique": ("Rêverie", "Des récits contemplatifs, où les mots prennent leur temps."),
}

MONTHS = ("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.",
          "nov.", "déc.")


def format_day(value):
    """'2026-10-05' -> '5 oct. 2026'."""
    day = date.fromisoformat(value)
    return f"{day.day} {MONTHS[day.month - 1]} {day.year}"


def profile_of(user):
    return json.loads(user["profile_vector"])


def plural(n, word):
    return f"{n} {word}{'s' if n > 1 else ''}"


# --- Bibliothèque ------------------------------------------------------------------------

def library_ids(user_id, db_path=DB_PATH):
    """Ids de tous les livres suivis (à lire, en cours, terminés)."""
    return {r["book_id"] for r in db.list_readings(user_id, db_path=db_path)}


def current_reading(user_id, db_path=DB_PATH):
    """{"reading": lecture en cours la plus récente ou None, "others": nombre des autres,
    "next": premier livre de la pile (pour l'invitation quand rien n'est en cours)}."""
    reading = db.list_readings(user_id, db.READING, db_path)
    pile = db.list_readings(user_id, db.TO_READ, db_path)
    return {"reading": reading[0] if reading else None,
            "others": max(len(reading) - 1, 0),
            "next": pile[0] if pile else None}


# --- Filtres d'univers -------------------------------------------------------------------

@dataclasses.dataclass
class AttributeFilters(engine.Filters):
    """Filtres du compte + un attribut imposé (thème, ambiance ou catégories)."""
    theme: str | None = None
    ambiance: str | None = None
    any_categories: set = dataclasses.field(default_factory=set)

    def accepts(self, book):
        if self.theme and self.theme not in book["themes"]:
            return False
        if self.ambiance and book["ambiance"] != self.ambiance:
            return False
        if self.any_categories and not book_categories(book) & set(self.any_categories):
            return False
        return super().accepts(book)


def with_attribute(filters, exclude=(), **attribute):
    """Copie des filtres, avec des ids exclus en plus et un attribut éventuel."""
    filters = filters or engine.Filters()
    fields = {f.name: getattr(filters, f.name) for f in dataclasses.fields(engine.Filters)}
    fields["exclude_ids"] = set(fields["exclude_ids"]) | set(exclude)
    return AttributeFilters(**fields, **attribute)


# --- Sections ----------------------------------------------------------------------------

def finished_ids(user_id, db_path=DB_PATH):
    return [r["book_id"] for r in db.list_readings(user_id, db.FINISHED, db_path)]


def lecteurs_comme_toi(user, db_path=DB_PATH):
    """Livres terminés par les autres lecteurs de même famille de profil :
    {"books": [{"book", "readers", "avg_rating"}], "readers": lecteurs contributeurs}.
    Classés par nombre de lecteurs distincts, puis note moyenne."""
    with db.get_connection(db_path) as conn:
        args = (user["profile_family"], user["id"])
        where = ("FROM readings r JOIN users u ON u.id = r.user_id"
                 " WHERE u.profile_family = ? AND u.id != ? AND r.end_date IS NOT NULL")
        rows = conn.execute(
            f"SELECT r.book_id, COUNT(DISTINCT r.user_id) AS readers, AVG(r.rating) AS avg"
            f" {where} GROUP BY r.book_id"
            " ORDER BY readers DESC, COALESCE(avg, 0) DESC, r.book_id", args).fetchall()
        contributors = conn.execute(f"SELECT COUNT(DISTINCT r.user_id) {where}", args).fetchone()[0]
    index = engine.get_index(db_path)
    books = [{"book": index.books[index.row_of[r["book_id"]]], "readers": r["readers"],
              "avg_rating": r["avg"]} for r in rows if r["book_id"] in index.row_of]
    return {"books": books, "readers": contributors}


def populaires_semaine(today=None, db_path=DB_PATH):
    """Livres commencés entre J-6 et J, par lecteurs distincts, tous profils :
    {"books": [{"book", "readers"}], "readers": lecteurs distincts de la semaine}."""
    today = today or date.today()
    span = ((today - timedelta(days=WEEK_DAYS - 1)).isoformat(), today.isoformat())
    where = "FROM readings WHERE start_date BETWEEN ? AND ?"
    with db.get_connection(db_path) as conn:
        rows = conn.execute(f"SELECT book_id, COUNT(DISTINCT user_id) AS readers {where}"
                            " GROUP BY book_id ORDER BY readers DESC, book_id", span).fetchall()
        total = conn.execute(f"SELECT COUNT(DISTINCT user_id) {where}", span).fetchone()[0]
    index = engine.get_index(db_path)
    books = [{"book": index.books[index.row_of[r["book_id"]]], "readers": r["readers"]}
             for r in rows if r["book_id"] in index.row_of]
    return {"books": books, "readers": total}


def group_popularity(lecteurs):
    """{id: 0-100} : lecteurs du livre ÷ lecteurs du livre le plus lu du groupe."""
    top = max((b["readers"] for b in lecteurs["books"]), default=0)
    return {b["book"]["id"]: 100 * b["readers"] / top for b in lecteurs["books"]} if top else {}


def pour_toi(user, n=5, filters=None, exclude=(), db_path=DB_PATH, group_pop=None,
             max_per_category=MAX_PER_CATEGORY):
    """profile.recommend hors bibliothèque (et hors exclude)."""
    if group_pop is None:
        group_pop = group_popularity(lecteurs_comme_toi(user, db_path))
    exclude = library_ids(user["id"], db_path) | set(exclude)
    return recommend(profile_of(user), n, with_attribute(filters, exclude),
                     finished_ids(user["id"], db_path), group_pop, db_path, max_per_category)


def family_selection(user, filters=None, exclude=(), db_path=DB_PATH):
    """Livres des catégories de la famille du profil, classés par S puis ratings_count."""
    profile = profile_of(user)
    family = user["profile_family"]
    cats = FAMILY_CATEGORIES.get(family) or list(CATEGORY_LABELS)  # éclectique : tout
    flt = with_attribute(filters, library_ids(user["id"], db_path) | set(exclude),
                         any_categories=set(cats))
    excluded = set(profile["exclusions"])
    candidates = [b for b in engine.get_index(db_path).books
                  if flt.accepts(b) and not book_categories(b) & excluded]
    novelties = novelty_for(profile, candidates, finished_ids(user["id"], db_path),
                            db_path=db_path)
    year = date.today().year
    scored = [(score_book(profile, b, novelties[b["id"]], None, year)[0], b) for b in candidates]
    scored.sort(key=lambda item: (-round(item[0], 6), -(item[1]["ratings_count"] or 0),
                                  item[1]["id"]))
    return [b for _, b in scored]


def renouveler(results, seen):
    """Réordonne results (sortie de recommend) : S − RENEW_PENALTY × nombre de fois où le
    livre a déjà été proposé. Le tri est stable : sans pénalité, l'ordre ne change pas."""
    counts = Counter(seen)
    return sorted(results, key=lambda r: r["score"] - RENEW_PENALTY * counts[r["book"]["id"]],
                  reverse=True)


def section(kind, eyebrow, title, subtitle, items, empty, notice=None):
    return {"kind": kind, "eyebrow": eyebrow, "title": title, "subtitle": subtitle,
            "items": items, "empty": empty, "notice": notice}


def community_sections(user, n=5, filters=None, today=None, db_path=DB_PATH):
    """« Les lecteurs comme toi » et « Populaires cette semaine » ; une section sous
    MIN_READERS lecteurs est remplacée par la « Sélection {famille} » (une seule fois)."""
    family = user["profile_family"]
    library = library_ids(user["id"], db_path)
    flt = with_attribute(filters, library)
    lecteurs = lecteurs_comme_toi(user, db_path)
    populaires = populaires_semaine(today, db_path)

    def keep(entries):
        return [e for e in entries if flt.accepts(e["book"])]

    sections, missing = [], []
    if lecteurs["readers"] >= MIN_READERS:
        items = [{"book": e["book"], "note": plural(e["readers"], "lecteur")}
                 for e in keep(lecteurs["books"])]
        sections.append(section(
            "lecteurs", "TA TRIBU DE LECTURE", "Les lecteurs comme toi",
            f"Les livres terminés par {lecteurs['readers']} lecteurs au profil {family}.", items,
            "Tes voisins de lecture n'ont rien terminé que tu n'aies déjà ou qui passe tes "
            "filtres. Reviens bientôt !"))
    else:
        missing.append(("lecteurs", lecteurs["readers"]))
    if populaires["readers"] >= MIN_READERS:
        items = [{"book": e["book"], "note": plural(e["readers"], "lecteur") + " cette semaine"}
                 for e in keep(populaires["books"])]
        sections.append(section(
            "populaires", "ÇA BUZZE DANS LA BIBLIOTHÈQUE", "Populaires cette semaine",
            "Les livres les plus commencés ces sept derniers jours, tous profils confondus.",
            items, "Les livres commencés cette semaine sont déjà dans ta bibliothèque "
            "ou hors de tes filtres."))
    else:
        missing.append(("populaires", populaires["readers"]))

    if missing:
        detail = " et ".join(
            f"{plural(count, 'lecteur')} {'de ton profil' if kind == 'lecteurs' else 'cette semaine'}"
            for kind, count in missing)
        notice = (f"Il faut au moins {MIN_READERS} lecteurs pour des tendances fiables "
                  f"(pour l'instant : {detail}). En attendant, voici une sélection {family}.")
        items = [{"book": b, "note": None} for b in family_selection(user, filters, (), db_path)]
        replacement = section(
            "famille", "EN ATTENDANT TA TRIBU", f"Sélection {family}",
            f"Les livres de la famille {family} qui collent le mieux à ton profil.", items,
            "Aucun livre de cette famille ne passe tes filtres actuels.", notice)
        position = 0 if missing[0][0] == "lecteurs" else len(sections)
        sections.insert(position, replacement)
    for s in sections:
        s["total"] = len(s["items"])
        s["items"] = s["items"][:n]
    return sections


# --- Univers -----------------------------------------------------------------------------

def top_attributes(profile):
    """Attributs du profil, les mieux pondérés d'abord : (dimension, code, poids). À poids égal :
    thèmes, puis ambiances, puis genres, chacun dans l'ordre du profil."""
    ranked = []
    for rank, (dim, question) in enumerate((("themes", "q2"), ("ambiances", "q3"),
                                            ("genres", "q1"))):
        if not profile["answered"][question]:
            continue
        for pos, (code, weight) in enumerate(profile[dim].items()):
            if weight > 0:
                ranked.append((-weight, rank, pos, dim, code))
    ranked.sort()
    return [(dim, code, -w) for w, _, _, dim, code in ranked]


def universe_for(dim, code):
    """(clé, titre, explication, filtre) d'un attribut du profil."""
    if dim == "themes":
        title, text = THEME_UNIVERSES[code]
        return (f"theme-{code}", title,
                f"{text} Parce que le thème {THEME_LABELS[code]} compte parmi tes préférés.",
                {"theme": code})
    if dim == "ambiances":
        title, text = AMBIANCE_UNIVERSES[code]
        return (f"ambiance-{code}", title,
                f"{text} Parce que tu aimes les ambiances {AMBIANCE_LABELS[code]}s.",
                {"ambiance": code})
    return (f"genre-{code}", CATEGORY_LABELS[code],
            f"{GENRE_LABELS[code]['description']} Parce que ce genre fait partie de tes goûts.",
            {"any_categories": {code}})


def univers(user, n=8, filters=None, db_path=DB_PATH):
    """3 univers : {key, title, explanation, neighbor, items}. Complétés par les familles
    voisines quand le profil a moins de 3 attributs (ou des univers vides)."""
    profile = profile_of(user)
    library = library_ids(user["id"], db_path)
    read = finished_ids(user["id"], db_path)
    group_pop = group_popularity(lecteurs_comme_toi(user, db_path))

    def books_for(attribute):
        return recommend(profile, n, with_attribute(filters, library, **attribute), read,
                         group_pop, db_path)

    result = []
    for dim, code, _ in top_attributes(profile):
        if len(result) == UNIVERSES:
            break
        key, title, text, attribute = universe_for(dim, code)
        items = books_for(attribute)
        if items:
            result.append({"key": key, "title": title, "explanation": text, "neighbor": False,
                           "items": items})

    family = user["profile_family"]
    for neighbor in NEIGHBORS.get(family, []):
        if len(result) == UNIVERSES:
            break
        items = books_for({"any_categories": set(FAMILY_CATEGORIES[neighbor])})
        if items:
            genres = join_fr([CATEGORY_LABELS[c] for c in FAMILY_CATEGORIES[neighbor]])
            result.append({
                "key": f"voisin-{neighbor}", "title": f"Famille voisine : {neighbor}",
                "explanation": (f"Ton profil n'a pas encore assez de goûts marqués pour trois "
                                f"univers : on complète avec {genres}, une famille voisine de "
                                f"la tienne ({family})."),
                "neighbor": True, "items": items})
    return result


# --- Explication sur la fiche ------------------------------------------------------------

SOURCES = ("pour-toi", "lecteurs", "populaires", "famille", "univers")


def scores_for(user, books, db_path=DB_PATH):
    """{id: S} de livres quelconques contre le profil de user, en une passe : nouveauté
    et popularité de groupe calculées une fois, comme dans recommend."""
    books = list({b["id"]: b for b in books}.values())
    if not books:
        return {}
    profile = profile_of(user)
    novelties = novelty_for(profile, books, finished_ids(user["id"], db_path), db_path=db_path)
    group_pop = group_popularity(lecteurs_comme_toi(user, db_path))
    year = date.today().year
    return {b["id"]: score_book(profile, b, novelties[b["id"]], group_pop.get(b["id"]), year)[0]
            for b in books}


def rounded(S):
    return math.floor(S + 0.5)


def affinity(S):
    """Texte du badge : « S % d'affinité », S arrondi (None si pas de score)."""
    return None if S is None else f"{rounded(S)} % d'affinité"


def affinity_level(S):
    """Niveau de couleur du badge : 1 (S ≥ 80), 2 (≥ 60), 3 (≥ 40), sinon 4."""
    return next((i for i, t in enumerate(AFFINITY_LEVELS, 1) if rounded(S) >= t),
                len(AFFINITY_LEVELS) + 1)


def reason(user, book, source, today=None, db_path=DB_PATH):
    """Phrase « Pourquoi ce livre ? » selon la section d'où vient le lien, ou None."""
    if source == "lecteurs":
        entry = next((e for e in lecteurs_comme_toi(user, db_path)["books"]
                      if e["book"]["id"] == book["id"]), None)
        if entry:
            note = (f", note moyenne {entry['avg_rating']:.1f}/5".replace(".", ",")
                    if entry["avg_rating"] is not None else "")
            return (f"Terminé par {plural(entry['readers'], 'lecteur')} au profil "
                    f"{user['profile_family']}{note}.")
    elif source == "populaires":
        entry = next((e for e in populaires_semaine(today, db_path)["books"]
                      if e["book"]["id"] == book["id"]), None)
        if entry:
            return f"Commencé par {plural(entry['readers'], 'lecteur')} ces sept derniers jours."
    if source not in SOURCES:
        return None
    profile = profile_of(user)
    N = novelty_for(profile, [book], finished_ids(user["id"], db_path), db_path=db_path)[book["id"]]
    _, detail = score_book(profile, book, N)
    sentence = explain(profile, book, detail)
    if source == "famille":
        return f"Sélection {user['profile_family']}. {sentence}"
    return sentence
