"""Statistiques personnelles, calculées sur les lectures terminées (logique pure).

Chaque lecture est un dict : book_id, title, start_date, end_date (AAAA-MM-JJ),
rating (1..5 ou None), page_count (entier ou None), categories (liste) ;
facultatifs : authors (liste), themes (liste), ambiance (code ou None).
Dates civiles, fuseau Europe/Paris ; les pages sont rattachées à la date de fin.
Un indicateur sans donnée vaut None : jamais de faux zéro.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
TOP_GENRES = 5
TOP_MOODS = 8
MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
          "septembre", "octobre", "novembre", "décembre")


def today_paris():
    return datetime.now(PARIS).date()


def has_pages(reading):
    return bool(reading["page_count"])  # 0 ou None : nombre de pages inconnu


def favorite(readings):
    """Note la plus haute ; égalité → terminé le plus récemment ; aucune note → None."""
    rated = [r for r in readings if r["rating"] is not None]
    if not rated:
        return None
    return max(rated, key=lambda r: (r["rating"], r["end_date"], r.get("id") or 0))


def biggest(readings):
    """Lecture au plus grand nombre de pages connu, ou None."""
    known = [r for r in readings if has_pages(r)]
    return max(known, key=lambda r: (r["page_count"], r["end_date"])) if known else None


def average_rating(readings):
    """Note moyenne à une décimale, ou None si aucune note."""
    ratings = [r["rating"] for r in readings if r["rating"] is not None]
    return round(sum(ratings) / len(ratings), 1) if ratings else None


def pace(readings, today):
    """Pages par semaine : pages connues ÷ max(1, jours depuis le premier début ÷ 7)."""
    pages = sum(r["page_count"] for r in readings if has_pages(r))
    if not pages:
        return None
    first = min(date.fromisoformat(r["start_date"] or r["end_date"]) for r in readings)
    weeks = max(1, (today - first).days / 7)
    return round(pages / weeks)


def finished_this_month(readings, today):
    """Lectures terminées du 1er du mois courant à aujourd'hui (inclus)."""
    first = today.replace(day=1)
    return [r for r in readings if first <= date.fromisoformat(r["end_date"]) <= today]


def genres(readings, limit=TOP_GENRES):
    """[{category, count, rated, average}] : chaque catégorie comptée une fois par livre."""
    by_genre = {}
    for r in readings:
        for category in set(r["categories"]):
            by_genre.setdefault(category, []).append(r["rating"])
    rows = []
    for category, ratings in by_genre.items():
        notes = [x for x in ratings if x is not None]
        rows.append({"category": category, "count": len(ratings), "rated": len(notes),
                     "average": round(sum(notes) / len(notes), 1) if notes else None})
    rows.sort(key=lambda row: (-row["count"], row["category"]))  # égalité : ordre alphabétique
    return rows[:limit]


def moods(readings, limit=TOP_MOODS):
    """[{kind: 'theme' | 'ambiance', key, count}] : thèmes et ambiances des livres terminés,
    chacun compté une fois par livre, les plus fréquents d'abord."""
    counts = {}
    for r in readings:
        keys = {("theme", t) for t in r.get("themes") or []}
        if r.get("ambiance"):
            keys.add(("ambiance", r["ambiance"]))
        for key in keys:
            counts[key] = counts.get(key, 0) + 1
    rows = [{"kind": kind, "key": key, "count": n} for (kind, key), n in counts.items()]
    rows.sort(key=lambda row: (-row["count"], row["kind"], row["key"]))
    return rows[:limit]


def compute(readings, today=None):
    """Tous les indicateurs de la section statistiques de /profil."""
    today = today or today_paris()
    known = [r for r in readings if has_pages(r)]
    rated = [r for r in readings if r["rating"] is not None]
    return {
        "finished": len(readings),
        "favorite": favorite(readings),
        "pace": pace(readings, today) if readings else None,
        "month": len(finished_this_month(readings, today)),
        "month_name": MONTHS[today.month - 1],
        "average": average_rating(readings),
        "rated": len(rated),
        "pages": sum(r["page_count"] for r in known) if known else None,
        "unknown_pages": len(readings) - len(known),
        "biggest": biggest(readings),
        "genres": genres(readings),
        "moods": moods(readings),
    }
