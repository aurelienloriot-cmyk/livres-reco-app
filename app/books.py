"""Recherche, fiche livre et actions de lecture (pile, commencer, terminer)."""

import math
from datetime import date

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template, request,
                   url_for)

from app import filters as user_filters
from app.auth import db_path, profile_required
from src import db, engine, home
from src.questions import AMBIANCE_LABELS, CATEGORY_LABELS, GROUPS, THEME_LABELS

bp = Blueprint("books", __name__)

PER_PAGE = 24
MIN_QUERY = 2
GROUP_OF = {cat: label for label, cats in GROUPS.values() for cat in cats}


def get_book(book_id):
    """Livre du catalogue (champs JSON décodés), ou 404. Un livre masqué (src.hide) reste
    accessible à qui le suit déjà dans sa bibliothèque."""
    index = engine.get_index(db_path())
    if book_id in index.row_of:
        return index.books[index.row_of[book_id]]
    if db.get_reading(g.user["id"], book_id, db_path()):
        book = engine.load_book(book_id, db_path())
        if book:
            return book
    abort(404)


# --- Recherche ---------------------------------------------------------------------------

def search(query, filters):
    """(exacts, approchés) de engine.search_books, parmi les livres qu'acceptent les filtres."""
    return engine.search_books(engine.get_index(db_path()), query, filters.accepts)


@bp.route("/recherche")
@profile_required
def recherche():
    query = request.args.get("q", "").strip()
    page = request.args.get("page", 1, type=int)
    filters = user_filters.load(g.user["id"])
    context = {"query": query, "results": [], "page": 1, "pages": 0, "total": 0,
               "error": None, "language_note": user_filters.language_note(filters)}

    if len(query) < MIN_QUERY:
        if query:
            context["error"] = f"Tape au moins {MIN_QUERY} caractères pour lancer la recherche."
        return render_template("books/recherche.html", **context)
    try:
        exact, approx = search(query, user_filters.to_engine(filters))
    except Exception:  # catalogue absent ou illisible
        current_app.logger.exception("Recherche impossible")
        context["error"] = "La recherche est indisponible pour le moment. Réessaie plus tard."
        return render_template("books/recherche.html", **context)

    results = exact + approx
    pages = max(1, math.ceil(len(results) / PER_PAGE))
    page = min(max(page, 1), pages)
    shown = results[(page - 1) * PER_PAGE:page * PER_PAGE]
    context.update(results=shown, approx={b["id"] for b in approx}, page=page, pages=pages,
                   total=len(results), scores=home.scores_for(g.user, shown, db_path()))
    return render_template("books/recherche.html", **context)


# --- Fiche livre -----------------------------------------------------------------------

@bp.route("/livre/<int:book_id>")
@profile_required
def fiche(book_id):
    book = get_book(book_id)
    query = request.args.get("q", "").strip()
    source = request.args.get("from")
    if book["hidden"]:  # hors index : ni explication ni livres similaires
        reason = None
    elif source in home.SOURCES:
        reason = home.reason(g.user, book, source, db_path=db_path())
    elif query:
        reason = f"Correspond à ta recherche « {query} »."
    else:
        reason = None

    filters = user_filters.to_engine(user_filters.load(g.user["id"]))
    similar = ([] if book["hidden"] else
               engine.similar_books(book_id, 5, filters=filters, db_path=db_path()))

    scores = home.scores_for(g.user, [book] + [s["book"] for s in similar], db_path())
    return render_template(
        "books/fiche.html", book=book, reason=reason, scores=scores, similar=similar,
        reading=db.get_reading(g.user["id"], book_id, db_path()),
        group=GROUP_OF.get(book["main_category"]),
        categories=[CATEGORY_LABELS.get(c, c) for c in dict.fromkeys(
            [book["main_category"], *book["categories"]]) if c],
        themes=[THEME_LABELS.get(t, t) for t in book["themes"]],
        ambiance=AMBIANCE_LABELS.get(book["ambiance"], book["ambiance"]),
        today=date.today().isoformat(),
    )


# --- Actions de lecture ----------------------------------------------------------------
# Chaque action revient sur la page d'origine (champ next) ou la fiche (POST puis
# redirection) : une double soumission ne crée jamais de doublon, la base refusant un
# second suivi du même livre. Terminer mène à la page d'avis.

def back_to(book_id):
    return user_filters.back(url_for("books.fiche", book_id=book_id))


@bp.route("/livre/<int:book_id>/pile", methods=["POST"])
@profile_required
def ajouter(book_id):
    get_book(book_id)
    if db.add_to_pile(g.user["id"], book_id, db_path()):
        flash("Ajouté à ta pile à lire.", "success")
    return back_to(book_id)


@bp.route("/livre/<int:book_id>/commencer", methods=["POST"])
@profile_required
def commencer(book_id):
    get_book(book_id)
    try:
        if db.start_reading(g.user["id"], book_id, request.form.get("date"),
                            db_path=db_path()):
            flash("Bonne lecture !", "success")
    except ValueError as error:
        flash(str(error), "error")
    return back_to(book_id)


@bp.route("/livre/<int:book_id>/terminer", methods=["POST"])
@profile_required
def terminer(book_id):
    get_book(book_id)
    try:
        if db.finish_reading(g.user["id"], book_id, request.form.get("date"),
                             db_path=db_path()):
            flash("Bravo, un livre de plus de terminé !", "success")
            reading = db.get_reading(g.user["id"], book_id, db_path())
            return redirect(url_for("library.avis", reading_id=reading["id"]))
    except ValueError as error:
        flash(str(error), "error")
    return back_to(book_id)
