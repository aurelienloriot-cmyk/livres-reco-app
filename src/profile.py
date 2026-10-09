"""Construction et gestion du profil lecteur.

- build_profile : réponses au questionnaire -> profil (genres, thèmes, ambiances, filtres,
  bonus, confiance, libellé, famille).
- score_book : score S d'un livre selon le barème : S = 0,84 × P + R + D.
- novelty_for : indice de nouveauté N (0-100) de chaque livre.
- recommend : les n meilleurs livres pour un profil, avec explication.
- diversify : au plus 3 livres de même catégorie principale parmi n.
- recompute_learned : le profil évolue avec les notes (±0,05, plafond ±0,30).
- save_learned : recalcul sur toutes les notes de l'utilisateur et enregistrement.

Usage : python -m src.profile --demo
"""

import copy
import sys
import time
from collections import Counter
from datetime import date

from src import db, engine
from src.db import DB_PATH
from src.engine import book_categories, join_fr, normalize
from src.questions import (AMBIANCE_LABELS, CATEGORY_LABELS, GROUPS, NEUTRAL, QUESTIONS_BY_ID,
                           THEME_LABELS)

P_WEIGHT = 0.84        # S = 0,84 × P + R + D
BONUS_MAX = 8          # R et D valent au plus 8 points
SCORED = ("q1", "q2", "q3", "q5", "q6")  # dimensions de P (q4 non calculée)
TOTAL_WEIGHT = 84      # dénominateur de la confiance : q1..q6 (q4 incluse)

DISCOVERY = {"proche": 0.0, "mixte": 0.5, "surprise": 1.0, "sans_pref": 0.5}

LENGTHS = ("court", "moyen", "long")  # < 250, 250-450, > 450 pages
# (âge maximal pour 100 %, âge maximal pour 50 %) ; au-delà : 0 %
PERIODS = {"nouveautes": (3, 10), "recents": (10, 25)}
CLASSIC_AGE = 25

MAX_PER_CATEGORY = 3  # livres de même main_category parmi les n recommandés

RATING_STEP = 0.05
RATING_CAP = 0.30
NOVELTY_MENTION = 2.0  # points apportés par N au-delà desquels l'explication le mentionne

# --- Familles et libellés ----------------------------------------------------------------

ECLECTIC = "éclectique"
FAMILY_OF = {
    "thriller": "suspense", "policier": "suspense",
    "science-fiction": "imaginaire", "dystopie": "imaginaire",
    "fantastique": "imaginaire", "horreur": "imaginaire",
    "roman historique": "histoire", "aventure": "histoire",
    "biographie": "réel et idées", "essai": "réel et idées",
    "littérature générale": "psychologie", "romance": "psychologie",
}
FAMILIES = ("psychologie", "suspense", "imaginaire", "histoire", "réel et idées", ECLECTIC)
TIE_LIMIT = 3  # 3 familles ou plus à égalité en tête : profil éclectique


def entry(label, description, tags, family):
    return {"label": label, "description": description, "tags": tags, "family": family}


PAIR_LABELS = [
    (("thriller", "policier"), entry(
        "Suspense & tension",
        "Tu aimes les intrigues qui te tiennent en haleine jusqu'à la dernière page.",
        ["Suspense", "Enquêtes", "Rebondissements", "Tension"], "suspense")),
    (("science-fiction", "dystopie"), entry(
        "Futurs possibles",
        "Tu aimes imaginer demain et questionner le monde à travers d'autres futurs.",
        ["Anticipation", "Sociétés", "Technologies", "Réflexion"], "imaginaire")),
    (("fantastique", "horreur"), entry(
        "Mondes de l'ombre",
        "Tu aimes frissonner et basculer dans des univers où l'étrange s'invite.",
        ["Étrange", "Frissons", "Créatures", "Mystère"], "imaginaire")),
    (("romance", "littérature générale"), entry(
        "Émotions & liens",
        "Tu aimes les histoires de cœur et les personnages qui te touchent.",
        ["Émotions", "Relations", "Personnages", "Sensibilité"], "psychologie")),
    (("biographie", "essai"), entry(
        "Esprits curieux",
        "Tu aimes comprendre le monde et découvrir des vies et des idées réelles.",
        ["Idées", "Vies réelles", "Savoir", "Réflexion"], "réel et idées")),
    (("roman historique", "aventure"), entry(
        "Grandes épopées",
        "Tu aimes les grands récits qui t'emmènent loin, dans le temps ou l'espace.",
        ["Épopées", "Histoire", "Voyages", "Héros"], "histoire")),
]

GENRE_LABELS = {
    "littérature générale": entry(
        "Âme littéraire", "Tu aimes les belles plumes et les histoires qui font réfléchir.",
        ["Style", "Personnages", "Société", "Émotions"], FAMILY_OF["littérature générale"]),
    "thriller": entry(
        "Adrénaline", "Tu aimes quand le rythme s'emballe et que tout peut basculer.",
        ["Suspense", "Rythme", "Rebondissements", "Tension"], FAMILY_OF["thriller"]),
    "policier": entry(
        "Fin limier", "Tu aimes mener l'enquête et démasquer le coupable avant la fin.",
        ["Enquêtes", "Indices", "Crimes", "Déduction"], FAMILY_OF["policier"]),
    "science-fiction": entry(
        "Explorateur·rice du futur", "Tu aimes les sciences, l'espace et les mondes de demain.",
        ["Espace", "Sciences", "Futur", "Technologies"], FAMILY_OF["science-fiction"]),
    "dystopie": entry(
        "Veilleur·se lucide", "Tu aimes les sociétés imaginaires qui en disent long sur la nôtre.",
        ["Sociétés", "Résistance", "Anticipation", "Réflexion"], FAMILY_OF["dystopie"]),
    "fantastique": entry(
        "Rêveur·se d'ailleurs", "Tu aimes la magie et les mondes qui n'existent nulle part ailleurs.",
        ["Magie", "Mondes imaginaires", "Quêtes", "Merveilleux"], FAMILY_OF["fantastique"]),
    "horreur": entry(
        "Amateur·rice de frissons", "Tu aimes avoir peur, bien installé·e dans ton fauteuil.",
        ["Frissons", "Peur", "Surnaturel", "Ténèbres"], FAMILY_OF["horreur"]),
    "roman historique": entry(
        "Voyageur·se du temps", "Tu aimes revivre le passé à travers des destins marquants.",
        ["Histoire", "Époques", "Destins", "Mémoire"], FAMILY_OF["roman historique"]),
    "romance": entry(
        "Cœur tendre", "Tu aimes les histoires d'amour qui font battre le cœur.",
        ["Amour", "Émotions", "Relations", "Feel good"], FAMILY_OF["romance"]),
    "aventure": entry(
        "Esprit d'aventure", "Tu aimes partir à l'aventure et vivre des péripéties.",
        ["Voyages", "Péripéties", "Exploration", "Héros"], FAMILY_OF["aventure"]),
    "biographie": entry(
        "Passeur·se de vies", "Tu aimes les vraies histoires et les parcours inspirants.",
        ["Vies réelles", "Témoignages", "Parcours", "Inspiration"], FAMILY_OF["biographie"]),
    "essai": entry(
        "Esprit critique", "Tu aimes les idées, les débats et apprendre en lisant.",
        ["Idées", "Société", "Savoir", "Débats"], FAMILY_OF["essai"]),
}

AMBIANCE_PROFILE_LABELS = {
    "sombre": entry(
        "Âme nocturne", "Tu aimes les récits sombres qui explorent la part d'ombre.",
        ["Noirceur", "Intensité", "Mystère", "Ombres"], "suspense"),
    "tendue": entry(
        "Cœur battant", "Tu aimes les lectures qui te gardent sous tension.",
        ["Tension", "Rythme", "Suspense", "Adrénaline"], "suspense"),
    "legere": entry(
        "Bonne humeur", "Tu aimes les lectures légères qui donnent le sourire.",
        ["Humour", "Légèreté", "Feel good", "Détente"], "psychologie"),
    "intimiste": entry(
        "Lecteur·rice sensible", "Tu aimes les récits intimes, au plus près des personnages.",
        ["Intime", "Émotions", "Introspection", "Sensibilité"], "psychologie"),
    "epique": entry(
        "Souffle épique", "Tu aimes les grandes fresques et les destins héroïques.",
        ["Fresques", "Héros", "Grandeur", "Aventure"], "histoire"),
    "poetique": entry(
        "Âme poétique", "Tu aimes les mots qui chantent et les récits qui font rêver.",
        ["Poésie", "Rêverie", "Style", "Onirisme"], "imaginaire"),
}

ECLECTIC_LABEL = entry(
    "Éclectique",
    "Tu es ouvert·e à tout : on va découvrir ensemble ce que tu aimes.",
    ["Découverte", "Curiosité", "Ouverture", "Surprises"], ECLECTIC)


def dominant_family(q1_codes):
    """Famille ayant le plus de voix dans q1 (chaque groupe ou catégorie cochée = une voix).

    ECLECTIC si TIE_LIMIT familles ou plus sont à égalité en tête ; à égalité entre deux
    familles, celle cochée en premier. None si aucun genre n'est coché.
    """
    votes = Counter(FAMILY_OF[GROUPS[c][1][0] if c in GROUPS else c] for c in q1_codes)
    if not votes:
        return None
    top = max(votes.values())
    leaders = [f for f, v in votes.items() if v == top]  # dans l'ordre des choix
    return ECLECTIC if len(leaders) >= TIE_LIMIT else leaders[0]


def choose_label(genres, ambiances, q1_codes):
    """Le libellé suit la famille dominante : première paire complète de cette famille,
    sinon premier genre coché de la famille. Sans genre : ambiance dominante, sinon
    éclectique."""
    family = dominant_family(q1_codes)
    if family == ECLECTIC:
        return ECLECTIC_LABEL
    if family:
        for pair, label in PAIR_LABELS:
            if label["family"] == family and all(g in genres for g in pair):
                return label
        return next(GENRE_LABELS[g] for g in genres if FAMILY_OF[g] == family)
    if ambiances:
        return AMBIANCE_PROFILE_LABELS[max(ambiances, key=ambiances.get)]
    return ECLECTIC_LABEL


# --- Construction du profil --------------------------------------------------------------

def as_list(answer):
    """Réponse -> liste de codes, sans le code neutre."""
    if answer is None:
        return []
    codes = [answer] if isinstance(answer, str) else list(answer)
    return [c for c in codes if c != NEUTRAL]


def as_code(answer):
    """Réponse unique -> code, ou None si neutre / absente."""
    codes = as_list(answer)
    return codes[0] if codes else None


def expand_groups(codes):
    """Groupes affichés (q1, q8) -> catégories du catalogue, sans doublon.
    Un code de catégorie est accepté tel quel ; les autres codes sont ignorés."""
    categories = []
    for code in codes:
        for cat in GROUPS[code][1] if code in GROUPS else [code]:
            if cat in CATEGORY_LABELS and cat not in categories:
                categories.append(cat)
    return categories


def build_profile(answers):
    """answers = {qid: liste de codes ou code} -> profil JSON-sérialisable."""
    q1_codes = [c for c in as_list(answers.get("q1")) if c in GROUPS or c in CATEGORY_LABELS]
    genres = {c: 1.0 for c in expand_groups(q1_codes)}
    themes = {c: 1.0 for c in as_list(answers.get("q2")) if c in THEME_LABELS}
    ambiances = {c: 1.0 for c in as_list(answers.get("q3")) if c in AMBIANCE_LABELS}
    length = as_code(answers.get("q5"))
    period = as_code(answers.get("q6"))
    discovery = as_code(answers.get("q10"))

    answered = {
        "q1": bool(genres), "q2": bool(themes), "q3": bool(ambiances),
        "q5": length in LENGTHS, "q6": period in (*PERIODS, "classiques"),
    }
    confidence = sum(QUESTIONS_BY_ID[q]["weight"] for q in SCORED if answered[q]) / TOTAL_WEIGHT
    label = choose_label(genres, ambiances, q1_codes)

    return {
        "genres": genres,
        "themes": themes,
        "ambiances": ambiances,
        "formats": as_list(answers.get("q4")),
        "length": length,
        "period": period,
        "languages": as_list(answers.get("q7")),
        "exclusions": expand_groups(as_list(answers.get("q8"))),
        "priority": as_code(answers.get("q9")),
        "discovery": DISCOVERY.get(discovery, 0.0),
        "answered": answered,  # dimension renseignée au questionnaire (sinon exclue de P)
        "confidence": round(confidence, 4),
        "initial": copy.deepcopy({"genres": genres, "themes": themes, "ambiances": ambiances}),
        "label": label["label"],
        "label_description": label["description"],
        "label_tags": label["tags"],
        "family": label["family"],
    }


# --- Score d'un livre ---------------------------------------------------------------------

def length_class(pages):
    if pages is None:
        return None
    if pages < 250:
        return "court"
    return "moyen" if pages <= 450 else "long"


def match_genres(profile, book):
    """q1 : part des catégories du livre couvertes, pondérée par la préférence."""
    if not profile["answered"]["q1"]:
        return None
    cats = book_categories(book)
    common = [c for c in cats if profile["genres"].get(c, 0) > 0]
    value = 100 * sum(profile["genres"].get(c, 0) for c in cats) / len(cats)
    return {"match": min(100.0, value), "common": common}


def match_themes(profile, book):
    """q2 : thèmes communs ÷ thèmes du livre ; ignoré si le livre n'a pas de thème."""
    if not profile["answered"]["q2"] or not book["themes"]:
        return None
    common = [t for t in book["themes"] if profile["themes"].get(t, 0) > 0]
    value = 100 * sum(profile["themes"].get(t, 0) for t in book["themes"]) / len(book["themes"])
    return {"match": min(100.0, value), "common": common}


def match_ambiance(profile, book):
    """q3 : 100 si l'ambiance du livre est choisie, 0 sinon ; ignoré si inconnue."""
    if not profile["answered"]["q3"] or not book["ambiance"]:
        return None
    pref = profile["ambiances"].get(book["ambiance"], 0)
    return {"match": min(100.0, 100 * pref), "common": [book["ambiance"]] if pref > 0 else []}


def match_length(profile, book):
    """q5 : 100 dans la plage visée, 50 dans une plage voisine, 0 à l'opposé."""
    book_class = length_class(book["page_count"])
    if profile["length"] not in LENGTHS or book_class is None:
        return None
    gap = abs(LENGTHS.index(profile["length"]) - LENGTHS.index(book_class))
    return {"match": (100.0, 50.0, 0.0)[gap]}


def match_period(profile, book, year):
    """q6 : selon l'âge du livre (année courante − année de publication)."""
    period = profile["period"]
    if book["published_year"] is None or period not in (*PERIODS, "classiques"):
        return None
    age = year - book["published_year"]
    if period == "classiques":
        return {"match": 100.0 if age > CLASSIC_AGE else 50.0}
    full, half = PERIODS[period]
    return {"match": 100.0 if age <= full else 50.0 if age <= half else 0.0}


def score_book(profile, book, N, group_pop=None, year=None):
    """(S, détail) avec S = 0,84 × P + R + D.

    P : moyenne pondérée des dimensions renseignées et calculables pour ce livre
    (None si aucune). R : bonus de priorité (q9). D : bonus de découverte (q10).
    """
    year = year or date.today().year
    detail = {}
    for qid, result in (("q1", match_genres(profile, book)), ("q2", match_themes(profile, book)),
                        ("q3", match_ambiance(profile, book)), ("q5", match_length(profile, book)),
                        ("q6", match_period(profile, book, year))):
        if result is not None:
            detail[qid] = result

    weights = {q: QUESTIONS_BY_ID[q]["weight"] for q in detail}
    P = (sum(detail[q]["match"] * w for q, w in weights.items()) / sum(weights.values())
         if detail else None)

    priority = profile["priority"]
    if priority == "themes":
        r_base = detail["q2"]["match"] if "q2" in detail else 0.0
    elif priority in ("nouveau", "varier"):
        r_base = N
    elif priority == "profil":
        r_base = group_pop or 0.0
    elif priority == "temps":
        r_base = detail["q5"]["match"] if "q5" in detail else 0.0
    else:
        r_base = 0.0
    R = r_base * BONUS_MAX / 100
    D = profile["discovery"] * N * BONUS_MAX / 100

    S = P_WEIGHT * (P or 0.0) + R + D
    detail.update(P=P, R=R, D=D, N=N)
    return S, detail


# --- Nouveauté ------------------------------------------------------------------------------

def novelty_for(profile, books, read_ids=(), db_path=DB_PATH):
    """{id: N}. Avec des lectures : 100 × (1 − cosinus avec leur centroïde TF-IDF).
    Sans lecture : 100 si ni catégorie ni thème commun avec le profil, 50 si l'un des
    deux, 0 si les deux ; 50 partout si q1 et q2 sont neutres."""
    ids = [b["id"] for b in books]
    if read_ids:
        values = engine.novelty(engine.centroid(list(read_ids), db_path=db_path), ids,
                                db_path=db_path)
        if values is not None:
            return {i: values.get(i, 50.0) for i in ids}

    answered = profile["answered"]
    genres = {g for g, v in profile["genres"].items() if v > 0} if answered["q1"] else set()
    themes = {t for t, v in profile["themes"].items() if v > 0} if answered["q2"] else set()
    if not genres and not themes:
        return {i: 50.0 for i in ids}
    result = {}
    for book in books:
        shared = bool(book_categories(book) & genres) + bool(set(book["themes"]) & themes)
        result[book["id"]] = (100.0, 50.0, 0.0)[shared]
    return result


# --- Recommandation -------------------------------------------------------------------------

def explain(profile, book, detail):
    """Phrase « Recommandé pour … » : genres, thèmes, ambiance communs, puis découverte."""
    parts = []
    genres = [CATEGORY_LABELS[c] for c in detail.get("q1", {}).get("common", [])]
    if genres:
        parts.append(("le genre " if len(genres) == 1 else "les genres ") + join_fr(genres))
    themes = [THEME_LABELS[t] for t in detail.get("q2", {}).get("common", [])]
    if themes:
        parts.append(("le thème " if len(themes) == 1 else "les thèmes ") + join_fr(themes))
    ambiance = detail.get("q3", {}).get("common", [])
    if ambiance:
        parts.append(f"son ambiance {AMBIANCE_LABELS[ambiance[0]]}")

    n_points = detail["D"] + (detail["R"] if profile["priority"] in ("nouveau", "varier") else 0)
    discovery = ""
    if n_points >= NOVELTY_MENTION:
        main = book["main_category"]
        if profile["genres"].get(main, 0) > 0:
            discovery = "te faire découvrir un univers un peu différent"
        else:
            discovery = f"te faire découvrir le genre {CATEGORY_LABELS[main]}"

    if parts and discovery:
        return f"Recommandé pour {join_fr(parts)}, et pour {discovery}."
    if parts:
        return f"Recommandé pour {join_fr(parts)}."
    if discovery:
        return f"Recommandé pour {discovery}."
    return "Recommandé pour élargir tes horizons de lecture."


def first_author(book):
    """Premier auteur normalisé (minuscules, sans accents), ou None."""
    return normalize(book["authors"][0]).strip() if book["authors"] else None


def diversify(items, n, max_per_category=MAX_PER_CATEGORY):
    """Les n premiers items (dicts {"book", ...} déjà triés) avec au plus max_per_category
    livres de même main_category ; si la liste ne le permet pas, complétés par les
    suivants sans contrainte. L'ordre d'origine est conservé. None : pas de contrainte."""
    if max_per_category is None:
        return items[:n]
    kept, counts = [], Counter()
    for i, item in enumerate(items):
        if len(kept) == n:
            break
        category = item["book"]["main_category"]
        if counts[category] < max_per_category:
            counts[category] += 1
            kept.append(i)
    chosen = set(kept)
    kept += [i for i in range(len(items)) if i not in chosen][:n - len(kept)]
    return [items[i] for i in sorted(kept)]


def recommend(profile, n=5, filters=None, read_ids=(), group_pop=None, db_path=DB_PATH,
              max_per_category=MAX_PER_CATEGORY):
    """Les n livres de meilleur score S : [{book, score, P, R, D, N, detail, explanation}].

    Écarte les genres à éviter (q8, prioritaires sur q1) et les livres déjà lus.
    Un seul livre par premier auteur, au plus max_per_category par catégorie principale
    (diversify ; None pour lever la contrainte).
    group_pop : {id livre: popularité 0-100 chez les lecteurs du même profil} ou None.
    """
    index = engine.get_index(db_path)
    excluded = set(profile["exclusions"])
    read = set(read_ids)
    filters = filters or engine.Filters()
    candidates = [b for b in index.books
                  if not book_categories(b) & excluded and b["id"] not in read
                  and filters.accepts(b)]

    novelties = novelty_for(profile, candidates, read_ids, db_path=db_path)
    year = date.today().year
    scored = []
    for book in candidates:
        pop = (group_pop or {}).get(book["id"])
        S, detail = score_book(profile, book, novelties[book["id"]], pop, year)
        n_dims = sum(q in detail for q in SCORED)
        scored.append((round(S, 6), n_dims, engine.rating_key(book), -book["id"], book, detail))
    # Départage : S, nombre de dimensions calculées, note moyenne (≥ 5 avis), id croissant.
    scored.sort(key=lambda item: item[:4], reverse=True)

    # Un livre par auteur : les suivants du même premier auteur passent leur tour.
    ranked, seen_authors = [], set()
    for S, _, _, _, book, d in scored:
        author = first_author(book)
        if author in seen_authors:
            continue
        if author:
            seen_authors.add(author)
        ranked.append({"book": book, "score": S, "detail": d})
    return [dict(r, P=r["detail"]["P"], R=r["detail"]["R"], D=r["detail"]["D"],
                 N=r["detail"]["N"], explanation=explain(profile, r["book"], r["detail"]))
            for r in diversify(ranked, n, max_per_category)]


# --- Évolution après une note ---------------------------------------------------------------

def learned(initial, deltas):
    """Valeurs initiales + somme des écarts, bornées une seule fois à
    [initial − 0,30 ; initial + 0,30] et ≥ 0. Une clé absente au départ n'est créée que
    si son total est positif."""
    prefs = dict(initial)
    for key, total in deltas.items():
        start = initial.get(key, 0.0)
        value = round(min(start + RATING_CAP, max(start - RATING_CAP, 0.0, start + total)), 4)
        if key in initial or value > 0:
            prefs[key] = value
    return prefs


def recompute_learned(profile, rated_books):
    """Recalcule genres, thèmes et ambiances depuis les valeurs initiales et toutes les
    notes : rated_books = [(livre, note)]. Note 4-5 : +0,05 sur les genres, thèmes et
    ambiance du livre ; 1-2 : −0,05 ; 3 : rien. Les écarts sont d'abord additionnés, puis
    bornés : le résultat ne dépend pas de l'ordre des notes, et modifier une note ne
    cumule jamais.

    Les valeurs apprises sont conservées, mais une dimension neutre au questionnaire
    reste exclue de P (profile["answered"]).
    """
    deltas = {"genres": Counter(), "themes": Counter(), "ambiances": Counter()}
    for book, rating in rated_books:
        if 2 < rating < 4:
            continue
        delta = RATING_STEP if rating >= 4 else -RATING_STEP
        for key in book_categories(book):
            deltas["genres"][key] += delta
        for key in book["themes"]:
            deltas["themes"][key] += delta
        if book["ambiance"]:
            deltas["ambiances"][book["ambiance"]] += delta
    for dim, totals in deltas.items():
        profile[dim] = learned(profile["initial"][dim], totals)
    return profile


def save_learned(user_id, profile, db_path=DB_PATH):
    """recompute_learned sur toutes les lectures notées de l'utilisateur, puis
    enregistrement : à appeler après chaque note ajoutée, modifiée ou retirée."""
    index = engine.get_index(db_path)
    rated = [(index.books[index.row_of[book_id]], rating)
             for book_id, rating in db.list_ratings(user_id, db_path) if book_id in index.row_of]
    profile = recompute_learned(profile, rated)
    db.save_profile(user_id, profile, db_path)
    return profile


# --- CLI --------------------------------------------------------------------------------------

DEMO_PROFILES = [
    ("Profil 1", {
        "q1": ["thriller_polar"], "q2": ["crime", "secret"], "q3": ["tendue"],
        "q4": [NEUTRAL], "q5": "moyen", "q6": "recents", "q7": [NEUTRAL], "q8": ["fantasy"],
        "q9": "themes", "q10": "mixte",
    }),
    ("Profil 2", {
        "q1": [NEUTRAL], "q2": ["famille", "deuil"], "q3": ["intimiste"], "q4": [NEUTRAL],
        "q5": NEUTRAL, "q6": NEUTRAL, "q7": [NEUTRAL], "q8": [NEUTRAL], "q9": NEUTRAL,
        "q10": NEUTRAL,
    }),
]


def fmt(value):
    return "-" if value is None else f"{value:.1f}"


def demo():
    engine.get_index()  # chargement de l'index hors chronométrage
    for name, answers in DEMO_PROFILES:
        start = time.perf_counter()
        profile = build_profile(answers)
        results = recommend(profile)
        elapsed = (time.perf_counter() - start) * 1000

        print(f"=== {name} ===")
        print(f"Libellé : {profile['label']} (famille {profile['family']})")
        print(f"Description : {profile['label_description']}")
        print(f"Tags : {', '.join(profile['label_tags'])}")
        print(f"Confiance : {profile['confidence'] * 100:.1f} %\n")
        for rank, r in enumerate(results, 1):
            b = r["book"]
            print(f"{rank}. {b['title']} — {', '.join(b['authors'])} "
                  f"[{b['main_category']}, {b['published_year']}, {b['page_count']} p., "
                  f"ambiance {b['ambiance'] or '-'}, thèmes {', '.join(b['themes']) or '-'}]")
            print(f"   S {r['score']:.1f} | P {fmt(r['P'])} | R {r['R']:.1f} | D {r['D']:.1f} "
                  f"| N {r['N']:.0f}")
            print(f"   {r['explanation']}")
        print(f"\nTemps (profil + recommandations) : {elapsed:.0f} ms\n")


def main(argv):
    if argv != ["--demo"]:
        print("Usage : python -m src.profile --demo")
        return 1
    demo()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
