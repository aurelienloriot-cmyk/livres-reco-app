"""Filtres communs (recherche, livres proches, accueil) : panneau latéral, persistés par compte.

Un filtre est un dict JSON :
  {"languages": [...], "genres": [...], "exclusions": [...], "period": "...", "max_pages": n|None}
genres et exclusions sont des codes de groupe (src.questions.GROUPS).

Conversion en engine.Filters : ET entre familles de critères, OU à l'intérieur d'une
famille, exclusion prioritaire sur les genres acceptés.
"""

from datetime import date

from flask import Blueprint, g, redirect, request, url_for

from app.auth import db_path, profile_required
from src import db
from src.engine import Filters
from src.profile import CLASSIC_AGE, PERIODS, expand_groups
from src.questions import GROUPS, QUESTIONS_BY_ID

bp = Blueprint("filters", __name__)

# Langues de q7 (sans « Toutes » ni l'option neutre) : aucune case cochée = toutes.
LANGUAGES = {o["code"]: o["label"] for o in QUESTIONS_BY_ID["q7"]["options"]
             if o["code"] not in ("toutes", "neutre")}
CATALOG_LANGUAGE = "fr"  # seule langue présente dans le catalogue
GROUP_LABELS = {code: label for code, (label, _) in GROUPS.items()}
PERIOD_LABELS = {
    "toutes": "Toutes les périodes",
    "nouveautes": "Nouveautés (3 dernières années)",
    "recents": "Récents (10 dernières années)",
    "classiques": f"Classiques (plus de {CLASSIC_AGE} ans)",
}
PAGE_OPTIONS = [None, 200, 300, 400, 500, 700, 1000]  # None = sans limite

DEFAULTS = {"languages": [], "genres": [], "exclusions": [], "period": "toutes",
            "max_pages": None}


def from_answers(answers):
    """Filtres de départ tirés du questionnaire : exclusions (q8) et période (q6)."""
    q8 = answers.get("q8") or []
    period = answers.get("q6")
    return dict(DEFAULTS,
                exclusions=[c for c in q8 if c in GROUPS],
                period=period if period in PERIOD_LABELS else "toutes")


def clean(form):
    """Formulaire du panneau -> filtres valides (valeurs inconnues ignorées)."""
    try:
        pages = int(form.get("max_pages") or 0) or None
    except ValueError:
        pages = None
    period = form.get("period")
    return {
        "languages": [c for c in LANGUAGES if c in form.getlist("languages")],
        "genres": [c for c in GROUPS if c in form.getlist("genres")],
        "exclusions": [c for c in GROUPS if c in form.getlist("exclusions")],
        "period": period if period in PERIOD_LABELS else "toutes",
        "max_pages": pages if pages in PAGE_OPTIONS else None,
    }


def load(user_id):
    """Filtres du compte ; créés depuis le questionnaire au premier appel."""
    filters = db.get_filters(user_id, db_path())
    if filters is None:
        filters = from_answers(db.load_answers(user_id, db_path()))
        db.save_filters(user_id, filters, db_path())
    return dict(DEFAULTS, **filters)


def to_engine(filters, year=None):
    """Filtres du compte -> engine.Filters."""
    year = year or date.today().year
    result = Filters(
        languages=set(filters["languages"]),
        categories_in=set(expand_groups(filters["genres"])),
        categories_out=set(expand_groups(filters["exclusions"])),
        max_pages=filters["max_pages"],
    )
    period = filters["period"]
    if period in PERIODS:                 # au plus 3 ou 10 ans
        result.year_min = year - PERIODS[period][0]
    elif period == "classiques":          # plus de 25 ans
        result.year_max = year - CLASSIC_AGE - 1
    return result


def active_labels(filters):
    """Critères actifs, en clair, pour les pastilles sous l'en-tête."""
    labels = []
    if filters["languages"]:
        labels.append("Langue : " + ", ".join(LANGUAGES[c] for c in filters["languages"]))
    if filters["genres"]:
        labels.append("Genres : " + ", ".join(GROUP_LABELS[c] for c in filters["genres"]))
    if filters["exclusions"]:
        labels.append("Sans : " + ", ".join(GROUP_LABELS[c] for c in filters["exclusions"]))
    if filters["period"] != "toutes":
        labels.append(PERIOD_LABELS[filters["period"]])
    if filters["max_pages"]:
        labels.append(f"{filters['max_pages']} pages max.")
    return labels


def language_note(filters):
    """Avertissement si aucune langue choisie n'a de livre dans le catalogue."""
    if filters["languages"] and CATALOG_LANGUAGE not in filters["languages"]:
        return ("Pour l'instant, le catalogue ne contient que des livres en français : "
                "ajoute le français à tes langues pour voir des résultats.")
    return None


@bp.app_context_processor
def inject_filters():
    """Filtres du compte disponibles dans tous les gabarits des pages protégées."""
    if not g.get("user") or not g.user["profile_vector"]:
        return {}
    filters = load(g.user["id"])
    return {"user_filters": filters, "active_filters": active_labels(filters),
            "filter_options": {"languages": LANGUAGES, "groups": GROUP_LABELS,
                               "periods": PERIOD_LABELS, "pages": PAGE_OPTIONS}}


def back(default=None):
    """Page d'origine (chemin interne uniquement), sinon default ou l'accueil."""
    target = request.form.get("next", "")
    if target.startswith("/") and not target.startswith("//"):
        return redirect(target)
    return redirect(default or url_for("main.accueil"))


@bp.route("/filtres", methods=["POST"])
@profile_required
def enregistrer():
    db.save_filters(g.user["id"], clean(request.form), db_path())
    return back()


@bp.route("/filtres/reinitialiser", methods=["POST"])
@profile_required
def reinitialiser():
    """Retour aux filtres de départ (ceux tirés du questionnaire)."""
    db.save_filters(g.user["id"], from_answers(db.load_answers(g.user["id"], db_path())),
                    db_path())
    return back()
