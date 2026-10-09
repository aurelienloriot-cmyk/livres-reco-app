"""Comptes fictifs de démonstration, identifiés comme tels (users.is_demo = 1).

Ils peuplent les sections communautaires de l'accueil (« Les lecteurs comme toi »,
« Populaires cette semaine »). Aucune donnée fictive n'est créée hors de ce script.

Usage :
  python -m src.seed           crée les comptes (refuse si des comptes démo existent déjà)
  python -m src.seed --reset   supprime les comptes démo et leurs données, puis recrée tout
  python -m src.seed --historique <pseudo> [--force]
                               historique de lecture cohérent pour un vrai compte (voir
                               history) ; refuse si le compte a déjà des lectures, sauf --force

Chaque persona (e-mail <pseudo>@exemple.fr, mot de passe commun « demo1234 ») répond au
questionnaire, puis suit des livres tirés de ses recommandations (plus 1 ou 2 hors profil).
Les dates sont relatives à aujourd'hui ; la graine aléatoire est fixe (résultat reproductible).

Les personas arrivent en deux vagues : les FIRST_WAVE premiers (graine SEED, réglages
d'origine) restent identiques ; la seconde vague (graine SEED + 1) complète chaque famille,
rejoint les livres du moment et ajoute ceux des familles histoire et réel et idées.
"""

import json
import random
import sys
import zlib
from collections import Counter
from datetime import date, datetime, time, timedelta

from werkzeug.security import generate_password_hash

from app.filters import DEFAULTS, from_answers, to_engine
from src import db, engine, home
from src.db import DB_PATH
from src.engine import book_categories
from src.profile import (ECLECTIC, FAMILIES, FAMILY_OF, build_profile, recommend,
                         recompute_learned, save_learned, score_book)
from src.questions import NEUTRAL

SEED = 2026
PASSWORD = "demo1234"
EMAIL_DOMAIN = "exemple.fr"
POOL = 40              # recommandations dans lesquelles on puise les lectures
PILE = (2, 3)          # livres à lire par persona
MAX_READING = 2        # livres en cours par persona
FIRST_WAVE = 23        # personas de la première vague, inchangés
MOMENT_FAMILIES = ("suspense", "psychologie", "imaginaire", "histoire", "réel et idées")
MOMENT_READERS = (4, 8)  # un livre « du moment » par famille, commencé cette semaine
FIRST_MOMENTS = (MOMENT_FAMILIES[:3], (4, 6))  # réglages de la première vague
MOMENT_PICKS = {"réel et idées": ("Reflets dans un oeil d'homme", "Nancy Huston")}  # imposés
MOMENT_MIN_DESCRIPTION = 500
MOMENT_BANNED = ("œuvre", "oeuvre", "création", "roman de", "étude")  # études littéraires
MIN_FINISHED = 1       # chaque persona a terminé au moins un livre (lecteur contributeur)
SHARED = {"suspense": 4, "psychologie": 3}  # livres terminés en commun (première vague)
SECOND_SHARED = 3      # seconde vague : livres terminés en commun dans chaque famille
FINISHED_START = (5, 90)  # début d'un livre terminé : entre J-90 et J-5
FINISHED_SPAN = (5, 30)   # fin : 5 à 30 jours après le début, jamais dans le futur
READING_START = (7, 40)   # début d'un livre en cours (hors livres du moment)

N = NEUTRAL
# pseudo, q1, q2, q3, q5, q6, q8, q9, q10, nombre de lectures ; q4 et q7 neutres.
PERSONAS = [
    # Suspense
    ("aline", ["thriller_polar"], ["crime", "secret"], ["tendue", "sombre"], "moyen", "recents",
     ["aucun"], "themes", "mixte", 9),
    ("karim", ["thriller_polar", "litterature"], ["crime"], ["tendue"], "long", "toutes",
     ["fantasy"], "temps", "proche", 7),
    ("sophie", ["thriller_polar"], ["secret", "famille"], ["sombre"], "court", "nouveautes",
     ["romance"], "varier", "surprise", 6),
    ("mehdi", ["thriller_polar", "science_fiction"], ["crime", "survie"], ["tendue"], N,
     "recents", ["aucun"], "nouveau", "mixte", 10),
    ("lucie", ["thriller_polar"], ["crime"], [N], "moyen", N, ["fantasy"], "profil",
     "sans_pref", 4),
    ("yann", ["thriller_polar", "histoire_aventure"], ["memoire", "crime"], ["sombre"], "long",
     "classiques", ["aucun"], "themes", "proche", 8),
    # Psychologie
    ("nour", ["litterature", "romance"], ["famille", "amour"], ["intimiste"], "moyen", "recents",
     ["thriller_polar"], "themes", "mixte", 8),
    ("clement", ["litterature"], ["famille", "secret"], ["intimiste", "sombre"], "court",
     "toutes", ["aucun"], "varier", "surprise", 6),
    ("ines", ["romance"], ["amour"], ["legere"], "moyen", "nouveautes", ["fantasy"], "temps",
     "proche", 9),
    ("marc", ["litterature", "biographies"], ["memoire", "famille"], ["intimiste"], "long",
     "classiques", ["romance"], "themes", "mixte", 5),
    ("nina", ["litterature"], ["famille", "secret"], ["intimiste"], "moyen", "recents",
     ["aucun"], "themes", "mixte", 6),
    ("julien", ["romance", "litterature"], ["amour", "famille"], ["legere"], "court",
     "nouveautes", ["fantasy"], "varier", "surprise", 5),
    # Imaginaire
    ("theo", ["science_fiction"], ["science", "survie"], ["epique"], "long", "recents",
     ["romance"], "nouveau", "surprise", 7),
    ("jade", ["fantasy"], ["secret"], ["epique", "poetique"], "long", "toutes", ["aucun"],
     "themes", "mixte", 8),
    ("hugo", ["science_fiction", "fantasy"], ["societe", "survie"], ["sombre"], "moyen", "toutes",
     ["aucun"], "varier", "surprise", 6),
    ("emma", ["fantasy", "romance"], ["amour", "secret"], ["poetique"], "moyen", "nouveautes",
     ["thriller_polar"], "profil", "mixte", 5),
    ("lina", ["science_fiction", "fantasy"], ["science", "secret"], ["epique"], "long", "toutes",
     ["aucun"], "nouveau", "mixte", 7),
    # Histoire
    ("pierre", ["histoire_aventure"], ["memoire", "societe"], ["epique"], "long", "classiques",
     ["fantasy"], "themes", "proche", 7),
    ("salome", ["histoire_aventure", "litterature"], ["memoire", "famille"], ["intimiste"],
     "moyen", "toutes", ["aucun"], "nouveau", "mixte", 6),
    ("antoine", ["histoire_aventure", "biographies"], ["memoire", "survie"], ["epique"], N,
     "recents", ["romance", "fantasy"], "temps", "proche", 5),
    # Réel et idées
    ("fatou", ["essais", "biographies"], ["societe", "science"], [N], "court", "nouveautes",
     ["aucun"], "themes", "mixte", 6),
    ("louis", ["essais"], ["societe"], [N], "moyen", "recents", ["romance"], "nouveau",
     "surprise", 4),
    # Éclectique
    ("camille", [N], [N], [N], N, N, [N], N, N, 3),
    # --- Seconde vague -----------------------------------------------------------------
    # Suspense
    ("bastien", ["thriller_polar"], ["crime", "secret"], ["sombre"], "moyen", "toutes",
     ["romance"], "themes", "proche", 8),
    ("chloe", ["thriller_polar", "litterature"], ["secret"], ["tendue", "sombre"], "court",
     "recents", ["aucun"], "varier", "mixte", 6),
    ("rachid", ["thriller_polar"], ["crime", "survie"], ["tendue"], "long", "nouveautes",
     ["fantasy"], "nouveau", "surprise", 9),
    ("margaux", ["thriller_polar", "romance"], ["crime", "amour"], ["tendue"], "moyen",
     "recents", ["science_fiction"], "profil", "mixte", 7),
    ("gaspard", ["thriller_polar"], ["crime"], ["sombre"], N, "classiques", ["aucun"], "temps",
     "proche", 6),
    # Psychologie
    ("elise", ["litterature"], ["famille", "memoire"], ["intimiste"], "moyen", "toutes",
     ["thriller_polar"], "themes", "proche", 7),
    ("samir", ["litterature", "romance"], ["amour", "secret"], ["intimiste", "legere"], "court",
     "recents", ["aucun"], "varier", "mixte", 6),
    ("manon", ["romance"], ["amour", "famille"], ["legere"], "court", "nouveautes",
     ["fantasy", "science_fiction"], "temps", "proche", 8),
    ("victor", ["litterature"], ["societe", "famille"], ["intimiste"], "long", "classiques",
     ["romance"], "nouveau", "surprise", 7),
    ("zoe", ["litterature", "romance"], ["famille"], [N], "moyen", N, ["aucun"], "profil",
     "mixte", 6),
    # Imaginaire
    ("adam", ["fantasy", "science_fiction"], ["survie", "secret"], ["epique", "sombre"], "long",
     "recents", ["romance"], "nouveau", "mixte", 8),
    # Histoire
    ("ophelie", ["histoire_aventure"], ["memoire", "famille"], ["epique"], "long", "toutes",
     ["science_fiction"], "themes", "mixte", 7),
    ("baptiste", ["histoire_aventure", "biographies"], ["memoire", "survie"], ["epique"],
     "moyen", "classiques", ["romance"], "temps", "proche", 6),
    ("leila", ["histoire_aventure", "litterature"], ["memoire", "amour"], ["intimiste", "epique"],
     "moyen", "recents", ["aucun"], "varier", "surprise", 8),
    # Réel et idées
    ("gilles", ["essais"], ["societe", "science"], [N], "moyen", "toutes", ["fantasy"], "themes",
     "proche", 7),
    ("aicha", ["biographies", "essais"], ["memoire", "societe"], ["intimiste"], "court",
     "recents", ["aucun"], "nouveau", "mixte", 6),
    ("raphael", ["essais", "science_fiction"], ["science"], [N], "long", "nouveautes",
     ["romance"], "varier", "surprise", 8),
    ("odile", ["biographies"], ["famille", "memoire"], ["intimiste"], "moyen", "classiques",
     ["thriller_polar"], "temps", "proche", 6),
    # Éclectique : q1 et q3 neutres, une ou deux autres réponses
    ("mathis", [N], ["societe"], [N], N, N, [N], N, "surprise", 6),
    ("rose", [N], [N], [N], "court", N, [N], N, N, 6),
    ("kevin", [N], [N], [N], N, "classiques", [N], "temps", N, 7),
    ("anais", [N], ["amour"], [N], N, N, ["fantasy"], N, N, 6),
    ("paul", [N], [N], [N], "long", N, [N], "nouveau", N, 7),
]

# --historique : 10 terminés sur 6 mois, 2 en cours cette semaine, 3 dans la pile.
HISTORY_FINISHED = 10
HISTORY_SHARED = 2        # terminés aussi par d'autres lecteurs de sa famille
HISTORY_OUTSIDE = 1       # livre hors profil parmi les terminés
HISTORY_READING = 2       # dont le livre du moment de sa famille
HISTORY_PILE = 3
HISTORY_MONTHS_DAYS = 182
HISTORY_RATINGS = (0.7, 0.2)  # parts à 4-5 et à 3 ; le reste à 1-2

COMMENTS = {
    "high": [
        "Impossible de le lâcher, je l'ai fini en quelques soirées.",
        "Une très belle découverte, je le recommande sans hésiter.",
        "Des personnages attachants et une fin vraiment réussie.",
        "Exactement le genre de livre que j'aime.",
        "Je vais vite chercher les autres livres de l'auteur.",
        "Il m'a accompagné longtemps après la dernière page.",
    ],
    "mid": [
        "Agréable, mais un peu long au milieu.",
        "Une bonne idée de départ, une fin moins convaincante.",
        "Sympathique, sans plus.",
        "Bien écrit, mais l'histoire ne m'a pas vraiment emporté.",
    ],
    "low": [
        "Je n'ai pas réussi à m'attacher aux personnages.",
        "Trop lent pour moi, j'ai failli abandonner.",
        "Pas du tout mon style, finalement.",
        "L'intrigue m'a laissé de marbre.",
    ],
}


class SeedError(Exception):
    """Création impossible (comptes démo déjà présents, pseudo pris…)."""


def answers_of(row):
    """Ligne de PERSONAS -> réponses au questionnaire, au format enregistré par l'interface."""
    pseudo, q1, q2, q3, q5, q6, q8, q9, q10, _ = row
    return {"q1": q1, "q2": q2, "q3": q3, "q4": [N], "q5": q5, "q6": q6, "q7": [N],
            "q8": q8, "q9": q9, "q10": q10}


def excludes(profile, book):
    return bool(book_categories(book) & set(profile["exclusions"]))


# --- Plan des lectures --------------------------------------------------------------------

def popular_in(personas, skip=(), strict=True):
    """Livres des recommandations de ces personas : les plus fréquents d'abord, puis les
    mieux classés. strict : sans les livres qu'un de ces personas exclut."""
    stats = {}
    for p in personas:
        for rank, book in enumerate(p["pool"]):
            count, ranks, _ = stats.get(book["id"], (0, 0, book))
            stats[book["id"]] = (count + 1, ranks + rank, book)
    ranked = sorted(stats.values(), key=lambda s: (-s[0], s[1], s[2]["id"]))
    return [b for _, _, b in ranked if b["id"] not in skip
            and not (strict and any(excludes(p["profile"], b) for p in personas))]


def required_finished(p):
    return max(len(p["shared"]), MIN_FINISHED)


def moment_candidate(book):
    """Roman à description assez longue et bien encodée, hors études littéraires (titre)."""
    title, description = book["title"].lower(), book["description"] or ""
    return (len(description) >= MOMENT_MIN_DESCRIPTION and "\ufffd" not in description
            and not any(word in title for word in MOMENT_BANNED))


def spare(p):
    """Places libres pour un livre en cours imposé (la pile garde au moins 2 livres)."""
    if len(p["moment"]) >= MAX_READING:
        return 0
    return p["total"] - PILE[0] - required_finished(p) - len(p["moment"])


def plan_readings(personas, books, rng, shared=SHARED, moments=FIRST_MOMENTS, before=()):
    """Remplit p["finished"], p["reading"] (livres), p["moment"], p["pile"] de chaque persona.

    shared : {famille: livres terminés en commun} ; moments : (familles, (min, max) lecteurs).
    before : personas déjà planifiés (vague précédente), que ceux-ci complètent."""
    for p in personas:
        p.update(shared=[], moment=[], used=set(), pool_ids={b["id"] for b in p["pool"]})
    current = {}  # famille -> (livre du moment de la vague précédente, lecteurs)
    for p in before:
        for book in p["moment"]:
            family = FAMILY_OF[book["main_category"]]
            current[family] = (book, current.get(family, (book, 0))[1] + 1)
    families, readers = moments

    # (b) Livres terminés en commun dans une famille, de préférence ceux que la vague
    # précédente a déjà terminés ; un persona avec peu de lectures n'en prend que ce que
    # sa pile lui laisse.
    reserved = {book["id"] for book, _ in current.values()}
    for family, k in shared.items():
        members = [p for p in personas if p["family"] == family]
        if not members:
            continue
        done = Counter(b["id"] for p in before if p["family"] == family for b in p["finished"])
        common = sorted(popular_in(members, reserved), key=lambda b: -done[b["id"]])[:k]
        reserved |= {b["id"] for b in common}
        for p in members:
            p["shared"] = rng.sample(common, min(k, p["total"] - PILE[0]))
            p["used"] |= {b["id"] for b in p["shared"]}

    # (a) Livres du moment : pour chaque famille, le roman le plus recommandé qui trouve
    # assez de lecteurs ; commencé cette semaine. Un livre de la vague précédente est
    # repris (et complété jusqu'à readers[1] lecteurs) ; les nouvelles familles d'abord.
    def candidates_for(book):
        found = [p for p in personas if spare(p) > 0
                 and not excludes(p["profile"], book) and book["id"] not in p["used"]]
        rng.shuffle(found)
        # D'abord ceux sans livre du moment, puis ceux à qui il est recommandé.
        found.sort(key=lambda p: (len(p["moment"]), book["id"] not in p["pool_ids"]))
        return found

    ranked = [b for b in popular_in(personas, reserved, strict=False) if moment_candidate(b)]
    for family in sorted(families, key=lambda f: f in current):
        if family in current:
            book, n = current[family]
            k = rng.randint(max(n, readers[0]), readers[1]) - n
            for p in candidates_for(book)[:k]:
                p["moment"].append(book)
                p["used"].add(book["id"])
            continue
        # Livre imposé (s'il est au catalogue et non masqué), sinon choix automatique.
        picked = [b for b in books if (b["title"], *b["authors"][:1]) == MOMENT_PICKS.get(family)]
        for book in picked + [b for b in ranked if FAMILY_OF[b["main_category"]] == family]:
            candidates = candidates_for(book)
            k = rng.randint(*readers)
            if len(candidates) < k:
                continue
            for p in candidates[:k]:
                p["moment"].append(book)
                p["used"].add(book["id"])
            reserved.add(book["id"])
            break

    for p in personas:
        fixed = len(p["shared"]) + len(p["moment"])
        needed = required_finished(p) + len(p["moment"])
        pile = rng.randint(*PILE) if p["total"] - PILE[1] >= needed else PILE[0]
        reading = min(rng.randint(len(p["moment"]), MAX_READING),
                      p["total"] - pile - required_finished(p))
        finished = p["total"] - pile - reading

        # Reste à choisir : les meilleures recommandations, plus 1 ou 2 livres hors profil.
        free = p["total"] - fixed
        outside = [b for b in books if b["id"] not in p["pool_ids"] and b["id"] not in reserved
                   and not excludes(p["profile"], b)]
        extra = rng.sample(outside, min(1 if p["total"] < 7 else 2, free))
        extra += [b for b in p["pool"] if b["id"] not in reserved | p["used"]][:free - len(extra)]
        rng.shuffle(extra)
        cut = finished - len(p["shared"])
        p["finished"] = p["shared"] + extra[:cut]
        p["reading"] = extra[cut:cut + reading - len(p["moment"])]
        p["pile"] = extra[cut + reading - len(p["moment"]):]


def rating_deck(n, rng):
    """n notes : 20 % sans note ; parmi les notées, 60 % à 4-5, 25 % à 3, 15 % à 1-2."""
    rated = n - round(0.2 * n)
    high, mid = round(0.6 * rated), round(0.25 * rated)
    deck = ([None] * (n - rated) + [rng.choice((4, 5)) for _ in range(high)] + [3] * mid
            + [rng.choice((1, 2)) for _ in range(rated - high - mid)])
    rng.shuffle(deck)
    return deck


def comment_for(rating, rng):
    kind = "high" if rating >= 4 else "mid" if rating == 3 else "low"
    return rng.choice(COMMENTS[kind])


def stamp(day, rng):
    """Date -> horodatage ISO à une heure plausible."""
    return datetime.combine(day, time(rng.randint(8, 22), rng.randint(0, 59))).isoformat()


def days_ago(today, n):
    return today - timedelta(days=n)


# --- Base -----------------------------------------------------------------------------------

def delete_demo(conn):
    demo = "SELECT id FROM users WHERE is_demo = 1"
    conn.execute(f"DELETE FROM readings WHERE user_id IN ({demo})")
    conn.execute(f"DELETE FROM survey_answers WHERE user_id IN ({demo})")
    conn.execute("DELETE FROM users WHERE is_demo = 1")


def write_persona(conn, p, today, rng):
    """Compte, réponses et lectures d'un persona ; renvoie son id."""
    first_day = min([r["start"] for r in p["rows"] if r["start"]] + [today])
    created = stamp(days_ago(first_day, rng.randint(3, 15)), rng)
    user_id = conn.execute(
        "INSERT INTO users (username, email, password_hash, created_at, is_demo)"
        " VALUES (?, ?, ?, ?, 1)",
        (p["pseudo"], f"{p['pseudo']}@{EMAIL_DOMAIN}", generate_password_hash(PASSWORD),
         created)).lastrowid
    for qid, answer in p["answers"].items():
        conn.execute("INSERT INTO survey_answers (user_id, question_id, answer, answered_at)"
                     " VALUES (?, ?, ?, ?)",
                     (user_id, qid, json.dumps(answer, ensure_ascii=False), created))
    for r in p["rows"]:
        last = r["end"] or r["start"] or r["added"]
        conn.execute(
            "INSERT INTO readings (user_id, book_id, rank, start_date, end_date, rating, comment,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, r["book"]["id"], r["rank"], r["start"] and r["start"].isoformat(),
             r["end"] and r["end"].isoformat(), r["rating"], r["comment"],
             stamp(r["added"], rng), stamp(last, rng)))
    return user_id


def date_rows(p, today, rng):
    """Lectures datées : p["rows"] = [{book, rank, start, end, added, rating, comment}]."""
    rows = []
    for book in p["finished"]:
        start = days_ago(today, rng.randint(*FINISHED_START))
        span = rng.randint(FINISHED_SPAN[0], min(FINISHED_SPAN[1], (today - start).days))
        rows.append({"book": book, "rank": None, "start": start,
                     "end": start + timedelta(days=span)})
    for book in p["moment"]:
        rows.append({"book": book, "rank": None, "end": None,
                     "start": days_ago(today, rng.randint(0, home.WEEK_DAYS - 1))})
    for book in p["reading"]:
        rows.append({"book": book, "rank": None, "end": None,
                     "start": days_ago(today, rng.randint(*READING_START))})
    for rank, book in enumerate(p["pile"], 1):
        rows.append({"book": book, "rank": rank, "start": None, "end": None,
                     "added": days_ago(today, rng.randint(1, 60))})
    for r in rows:
        r.setdefault("added", r["start"])
        r.update(rating=None, comment=None)
    p["rows"] = rows


# --- Script ---------------------------------------------------------------------------------

def run(db_path=DB_PATH, reset=False, today=None, out=print):
    """Crée les comptes démo ; renvoie le rapport (voir report)."""
    today = today or date.today()
    db.init_db(db_path)
    pseudos = [row[0] for row in PERSONAS]
    with db.get_connection(db_path) as conn:
        if conn.execute("SELECT 1 FROM users WHERE is_demo = 1").fetchone() and not reset:
            raise SeedError("Des comptes de démonstration existent déjà : relance avec --reset.")
        if reset:
            delete_demo(conn)
        marks = ",".join("?" * len(pseudos))
        taken = conn.execute(
            f"SELECT username FROM users WHERE lower(username) IN ({marks})"
            f" OR lower(email) IN ({marks})",
            pseudos + [f"{s}@{EMAIL_DOMAIN}" for s in pseudos]).fetchall()
        if taken:
            raise SeedError("Pseudo ou e-mail déjà pris par un vrai compte : "
                            + ", ".join(row["username"] for row in taken))

    index = engine.get_index(db_path)
    personas = []
    for row in PERSONAS:
        answers = answers_of(row)
        profile = build_profile(answers)
        pool = [r["book"] for r in recommend(profile, POOL, db_path=db_path,
                                             max_per_category=None)]
        personas.append({"pseudo": row[0], "total": row[-1], "answers": answers,
                         "profile": profile, "family": profile["family"], "pool": pool})
    first, second = personas[:FIRST_WAVE], personas[FIRST_WAVE:]
    rngs = random.Random(SEED), random.Random(SEED + 1)  # une graine par vague
    plan_readings(first, index.books, rngs[0])
    plan_readings(second, index.books, rngs[1], {f: SECOND_SHARED for f in FAMILIES},
                  (MOMENT_FAMILIES, MOMENT_READERS), before=first)

    for wave, rng in zip((first, second), rngs):
        for p in wave:
            date_rows(p, today, rng)
        finished = [r for p in wave for r in p["rows"] if r["end"]]
        for r, rating in zip(finished, rating_deck(len(finished), rng)):
            r["rating"] = rating
        rated = [r for r in finished if r["rating"]]
        for r in rng.sample(rated, round(len(rated) / 2)):
            r["comment"] = comment_for(r["rating"], rng)

    with db.get_connection(db_path) as conn:
        for wave, rng in zip((first, second), rngs):
            for p in wave:
                p["id"] = write_persona(conn, p, today, rng)
    for p in personas:
        db.save_profile(p["id"], p["profile"], db_path)
        notes = [(r["book"], r["rating"]) for r in p["rows"] if r["rating"]]
        db.save_profile(p["id"], recompute_learned(p["profile"], notes), db_path)
        db.save_filters(p["id"], from_answers(p["answers"]), db_path)

    result = report(db_path, today)
    print_report(result, out)
    return result


def report(db_path=DB_PATH, today=None):
    """Comptes, lectures par statut, populaires de la semaine, puis par famille : lecteurs,
    contributeurs (au moins un livre terminé), lecteurs actifs cette semaine, livres terminés
    en commun (lecteurs de chacun) et livre du moment (le plus commencé cette semaine)."""
    today = today or date.today()
    week_start = days_ago(today, home.WEEK_DAYS - 1).isoformat()
    with db.get_connection(db_path) as conn:
        users = conn.execute("SELECT id, username, profile_family FROM users"
                             " WHERE is_demo = 1").fetchall()
        readings = conn.execute(
            "SELECT r.*, b.title, b.main_category FROM readings r"
            " JOIN users u ON u.id = r.user_id JOIN books b ON b.id = r.book_id"
            " WHERE u.is_demo = 1").fetchall()
    family_of = {u["id"]: u["profile_family"] for u in users}
    week = [r for r in readings
            if r["start_date"] and week_start <= r["start_date"] <= today.isoformat()]
    families = {}
    for family in FAMILIES:
        mine = [r for r in readings if family_of[r["user_id"]] == family]
        finished = Counter(r["book_id"] for r in mine if r["end_date"])
        started = Counter((r["title"], r["main_category"]) for r in week)
        moment = max(((title, n) for (title, cat), n in started.items()
                      if FAMILY_OF[cat] == family), key=lambda t: t[1], default=None)
        families[family] = {
            "members": sum(f == family for f in family_of.values()),
            "contributors": len({r["user_id"] for r in mine if r["end_date"]}),
            "week_readers": len({r["user_id"] for r in week if family_of[r["user_id"]] == family}),
            "shared": sorted((n for n in finished.values() if n >= 2), reverse=True),
            "moment": moment,
        }
    populaires = home.populaires_semaine(today, db_path)
    return {
        "accounts": len(users),
        "statuses": Counter(db.reading_status(r) for r in readings),
        "week_readers": len({r["user_id"] for r in week}),
        "popular": [(e["book"]["title"], e["readers"]) for e in populaires["books"]],
        "families": families,
    }


def print_report(result, out=print):
    out(f"Comptes de démonstration créés : {result['accounts']}")
    out("Lectures : " + ", ".join(f"{result['statuses'][s]} {s}"
                                  for s in (db.TO_READ, db.READING, db.FINISHED)))
    out(f"Lecteurs ayant commencé un livre ces 7 derniers jours : {result['week_readers']}")
    out("Populaires cette semaine :")
    for title, readers in result["popular"]:
        if readers > 1:
            out(f"  {readers} lecteurs · {title}")
    out("Par famille :")
    for family, data in result["families"].items():
        out(f"  {family} : {data['members']} lecteurs, {data['contributors']} contributeurs,"
            f" {data['week_readers']} actifs cette semaine")
        out("    livres terminés en commun : "
            + (", ".join(f"{n} lecteurs" for n in data["shared"]) or "aucun"))
        if data["moment"] and data["moment"][1] > 1 and family != ECLECTIC:
            out(f"    du moment : {data['moment'][0]} ({data['moment'][1]} lecteurs)")


# --- Historique d'un vrai compte ---------------------------------------------------------

def history_rng(pseudo):
    """Graine fixe dérivée du pseudo (crc32 : stable d'une exécution à l'autre)."""
    return random.Random(SEED + zlib.crc32(pseudo.lower().encode()))


def family_moment(user, today, db_path=DB_PATH):
    """Livre « du moment » de la famille : le plus commencé cette semaine (et pas encore
    terminé) par les autres lecteurs de même famille, ou None."""
    span = (days_ago(today, home.WEEK_DAYS - 1).isoformat(), today.isoformat())
    with db.get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT r.book_id FROM readings r JOIN users u ON u.id = r.user_id"
            " WHERE u.profile_family = ? AND u.id != ? AND r.end_date IS NULL"
            " AND r.start_date BETWEEN ? AND ?"
            " GROUP BY r.book_id ORDER BY COUNT(DISTINCT r.user_id) DESC, r.book_id LIMIT 1",
            (user["profile_family"], user["id"], *span)).fetchone()
    index = engine.get_index(db_path)
    return index.books[index.row_of[row["book_id"]]] if row and row["book_id"] in index.row_of \
        else None


def history_ratings(n, rng):
    """n notes : 70 % à 4-5, 20 % à 3, 10 % à 1-2 (arrondis), de la meilleure à la pire."""
    high, mid = round(HISTORY_RATINGS[0] * n), round(HISTORY_RATINGS[1] * n)
    return ([rng.choice((4, 5)) for _ in range(high)] + [3] * mid
            + [rng.choice((1, 2)) for _ in range(n - high - mid)])


def plan_history(user, profile, today, rng, db_path=DB_PATH):
    """Lectures d'un vrai compte : [{book, rank, start, end, added, rating, comment}].

    Terminés : HISTORY_SHARED livres terminés par d'autres lecteurs de sa famille, un livre
    hors profil, le reste dans ses recommandations ; notés du mieux au moins bien classé par
    le barème (le hors profil a donc la moins bonne note). En cours : le livre du moment de
    sa famille et une recommandation, commencés cette semaine. Pile : 3 recommandations.
    """
    index = engine.get_index(db_path)
    saved = db.get_filters(user["id"], db_path) or from_answers(db.load_answers(user["id"],
                                                                              db_path))
    pool = [r["book"] for r in recommend(profile, POOL, to_engine(dict(DEFAULTS, **saved)),
                                         db_path=db_path, max_per_category=None)]
    allowed = [b for b in index.books if not excludes(profile, b)]
    used = set()

    def take(books, k):
        chosen = [b for b in books if b["id"] not in used][:k]
        used.update(b["id"] for b in chosen)
        return chosen

    moment = take([b for b in [family_moment(user, today, db_path)]
                   if b and not excludes(profile, b)], 1)
    shared = take([e["book"] for e in home.lecteurs_comme_toi(user, db_path)["books"]
                   if not excludes(profile, e["book"])], HISTORY_SHARED)
    pool_ids = {b["id"] for b in pool}
    outside = take(rng.sample([b for b in allowed if b["id"] not in pool_ids], 20),
                   HISTORY_OUTSIDE)
    finished = shared + outside + take(pool, HISTORY_FINISHED - len(shared) - len(outside))
    reading = moment + take(pool, HISTORY_READING - len(moment))
    pile = take(pool, HISTORY_PILE)
    if len(finished) + len(reading) + len(pile) < HISTORY_FINISHED + HISTORY_READING \
            + HISTORY_PILE:
        raise SeedError("Pas assez de livres recommandés pour ce profil avec ses filtres.")

    # Terminés répartis sur 6 mois : un créneau par livre, du plus ancien au plus récent.
    slot = (HISTORY_MONTHS_DAYS - FINISHED_SPAN[0]) // len(finished)
    rng.shuffle(finished)
    rows = []
    for i, book in enumerate(finished):
        oldest = HISTORY_MONTHS_DAYS - i * slot
        start = days_ago(today, rng.randint(oldest - slot + 1, oldest))
        span = rng.randint(FINISHED_SPAN[0], min(FINISHED_SPAN[1], (today - start).days))
        rows.append({"book": book, "rank": None, "start": start,
                     "end": start + timedelta(days=span)})
    year = today.year
    by_score = sorted(rows, key=lambda r: -score_book(profile, r["book"], 50.0, None, year)[0])
    for r, rating in zip(by_score, history_ratings(len(by_score), rng)):
        r["rating"] = rating
    for r in rng.sample(rows, len(rows) // 2):
        r["comment"] = comment_for(r["rating"], rng)
    for book in reading:
        rows.append({"book": book, "rank": None, "end": None,
                     "start": days_ago(today, rng.randint(0, home.WEEK_DAYS - 1))})
    for rank, book in enumerate(pile, 1):
        rows.append({"book": book, "rank": rank, "start": None, "end": None,
                     "added": days_ago(today, rng.randint(1, 60))})
    for r in rows:
        r.setdefault("added", r["start"])
        r.setdefault("rating", None)
        r.setdefault("comment", None)
    return {"rows": rows, "shared": shared, "moment": moment[0] if moment else None}


def refuse_if_readings(conn, user, force):
    """Nombre de lectures du compte ; SeedError s'il en a déjà, sauf force."""
    count = conn.execute("SELECT COUNT(*) FROM readings WHERE user_id = ?",
                         (user["id"],)).fetchone()[0]
    if count and not force:
        raise SeedError(f"Refusé : « {user['username']} » a déjà {count} lecture(s). "
                        "Relance avec --force pour les remplacer.")
    return count


def history(pseudo, db_path=DB_PATH, force=False, today=None, out=print):
    """Historique de lecture cohérent avec le profil d'un vrai compte (non démo), puis
    recalcul des tendances observées (save_learned). Refuse si le compte a déjà des
    lectures, sauf force (elles sont alors remplacées). Graine dérivée du pseudo."""
    today = today or date.today()
    user = db.find_user(pseudo, db_path)
    if user is None or user["username"].lower() != pseudo.lower():
        raise SeedError(f"Aucun compte au pseudo « {pseudo} ».")
    if user["is_demo"]:
        raise SeedError(f"« {pseudo} » est un compte de démonstration.")
    profile = db.load_profile(user["id"], db_path)
    if profile is None:
        raise SeedError(f"« {pseudo} » n'a pas encore rempli le questionnaire.")
    with db.get_connection(db_path) as conn:
        refuse_if_readings(conn, user, force)  # refus rapide, avant le calcul du plan

    rng = history_rng(pseudo)
    plan = plan_history(user, profile, today, rng, db_path)
    # Vérification refaite sous verrou d'écriture : un autre lancement a pu écrire pendant
    # le calcul du plan (sinon il serait effacé et le second lancement réussirait aussi).
    with db.get_connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        replaced = refuse_if_readings(conn, user, force)
        conn.execute("DELETE FROM readings WHERE user_id = ?", (user["id"],))
        for r in plan["rows"]:
            last = r["end"] or r["start"] or r["added"]
            conn.execute(
                "INSERT INTO readings (user_id, book_id, rank, start_date, end_date, rating,"
                " comment, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (user["id"], r["book"]["id"], r["rank"], r["start"] and r["start"].isoformat(),
                 r["end"] and r["end"].isoformat(), r["rating"], r["comment"],
                 stamp(r["added"], rng), stamp(last, rng)))
    save_learned(user["id"], profile, db_path)

    statuses = Counter(db.reading_status(r) for r in db.list_readings(user["id"],
                                                                       db_path=db_path))
    out(f"Historique de {user['username']} ({user['profile_family']}) : "
        + ", ".join(f"{statuses[s]} {s}" for s in (db.FINISHED, db.READING, db.TO_READ)))
    out("  partagés avec sa famille : "
        + (" ; ".join(b["title"] for b in plan["shared"]) or "aucun"))
    out(f"  du moment : {plan['moment']['title'] if plan['moment'] else 'aucun'}")
    if replaced:
        out(f"  {replaced} lecture(s) précédente(s) remplacée(s) (--force)")
    return plan


def main(argv):
    if argv[:1] == ["--historique"] and len(argv) in (2, 3) and argv[2:] in ([], ["--force"]):
        try:
            history(argv[1], force=argv[2:] == ["--force"])
        except SeedError as error:
            print(error)
            return 1
        return 0
    if argv not in ([], ["--reset"]):
        print("Usage : python -m src.seed [--reset | --historique <pseudo> [--force]]")
        return 1
    try:
        run(reset=argv == ["--reset"])
    except SeedError as error:
        print(error)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
