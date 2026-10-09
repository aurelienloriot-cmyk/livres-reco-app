"""Pages principales : accueil, sélections élargies, explorer."""

from datetime import date

from flask import (Blueprint, abort, current_app, g, redirect, render_template, request, session,
                   url_for)

from app import filters as user_filters
from app.auth import db_path, profile_required
from src import db, home
from src.profile import diversify

bp = Blueprint("main", __name__)

SECTION_SIZE = 5
BATCH = 24             # /selection : lots de 24
SEEN_KEY = "pour_toi_seen"    # ids déjà proposés par « Choisis pour toi » (session)
SHOWN_KEY = "pour_toi_shown"  # ids affichés en ce moment
SEEN_MAX = 96
CATALOG_ERROR = "Les suggestions sont indisponibles pour le moment. Réessaie plus tard."


@bp.app_template_filter("jour")
def jour(value):
    return home.format_day(value)


@bp.app_template_filter("affinite")
def affinite(score):
    return home.affinity(score)


@bp.app_template_filter("affinite_niveau")
def affinite_niveau(score):
    return home.affinity_level(score)


@bp.app_context_processor
def inject_library_count():
    """Badge « Ma bibliothèque » du menu latéral."""
    if not g.get("user") or not g.user["profile_vector"]:
        return {}
    return {"library_count": len(db.list_readings(g.user["id"], db_path=db_path()))}


def engine_filters():
    return user_filters.to_engine(user_filters.load(g.user["id"]))


@bp.route("/")
@profile_required
def index():
    return redirect(url_for("main.accueil"))


@bp.route("/accueil")
@profile_required
def accueil():
    current = home.current_reading(g.user["id"], db_path())
    try:
        sections = home_sections()
    except Exception:  # catalogue absent ou illisible
        current_app.logger.exception("Accueil sans suggestions")
        sections, error = [], CATALOG_ERROR
    else:
        error = None
    return render_template("main/accueil.html", active="accueil", sections=sections,
                           current=current, error=error, today=date.today().isoformat(),
                           scores=section_scores(sections))


def section_scores(sections):
    """{id: S} de tous les livres affichés dans les sections, en une passe."""
    return home.scores_for(g.user, [i["book"] for s in sections for i in s["items"]],
                           db_path())


def home_sections():
    """« Choisis pour toi » (ordre renouvelé), puis les sections communautaires."""
    filters = engine_filters()
    best = home.pour_toi(g.user, home.RENEW_POOL, filters, db_path=db_path())
    picks = diversify(home.renouveler(best, session.get(SEEN_KEY, [])), SECTION_SIZE)
    session[SHOWN_KEY] = [r["book"]["id"] for r in picks]
    pour_toi = home.section(
        "pour-toi", "TON PROCHAIN CRUSH LECTURE", "Choisis pour toi",
        "Les correspondances les plus fortes avec tes préférences déclarées.",
        [{"book": r["book"], "note": None} for r in picks],
        "Aucun livre ne passe tes filtres actuels : élargis-les pour voir des suggestions.")
    return [pour_toi, *home.community_sections(g.user, SECTION_SIZE, filters,
                                               db_path=db_path())]


@bp.route("/accueil/renouveler", methods=["POST"])
@profile_required
def renouveler():
    """Les livres affichés passent derrière les autres ; les filtres ne changent pas."""
    seen = session.get(SEEN_KEY, []) + session.get(SHOWN_KEY, [])
    session[SEEN_KEY] = seen[-SEEN_MAX:]
    return redirect(url_for("main.accueil") + "#pour-toi")


@bp.route("/selection/<kind>")
@profile_required
def selection(kind):
    page = max(request.args.get("lots", 1, type=int), 1)
    limit = BATCH * page
    filters = engine_filters()
    if kind == "pour-toi":
        results = home.pour_toi(g.user, limit + 1, filters, db_path=db_path())
        found = home.section(kind, "TON PROCHAIN CRUSH LECTURE", "Choisis pour toi",
                             "Toute ta sélection, de la meilleure correspondance à la suivante.",
                             [{"book": r["book"], "note": None} for r in results],
                             "Aucun livre ne passe tes filtres actuels.")
    else:
        found = next((s for s in home.community_sections(g.user, limit + 1, filters,
                                                         db_path=db_path())
                      if s["kind"] == kind), None)
        if found is None:
            abort(404)
    more = len(found["items"]) > limit
    found["items"] = found["items"][:limit]
    return render_template("main/selection.html", active="accueil", section=found,
                           lots=page, more=more, scores=section_scores([found]))


@bp.route("/explorer")
@profile_required
def explorer():
    try:
        universes, error = home.univers(g.user, filters=engine_filters(), db_path=db_path()), None
    except Exception:  # catalogue absent ou illisible
        current_app.logger.exception("Explorer indisponible")
        universes, error = [], CATALOG_ERROR
    scores = {r["book"]["id"]: r["score"] for u in universes for r in u["items"]}
    return render_template("main/explorer.html", active="explorer", universes=universes,
                           error=error, scores=scores)
