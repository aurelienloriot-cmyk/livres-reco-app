"""Ma bibliothèque (pile à lire, en cours, terminés), avis de lecture et page profil."""

from datetime import date

from flask import (Blueprint, abort, flash, g, redirect, render_template, request, url_for)

from app.auth import db_path, profile_required
from src import db, engine, home, stats
from src.profile import save_learned
from src.questions import AMBIANCE_LABELS, CATEGORY_LABELS, THEME_LABELS

bp = Blueprint("library", __name__)

# Onglets : paramètre ?onglet=, statut de lecture, libellé.
TABS = {"a-lire": (db.TO_READ, "À lire"), "en-cours": (db.READING, "En cours"),
        "termines": (db.FINISHED, "Terminés")}
TAB_OF = {status: slug for slug, (status, _) in TABS.items()}
EXCERPT = 140  # longueur de l'extrait du commentaire


def to_tab(status, book_id=None):
    return redirect(url_for("library.bibliotheque", onglet=TAB_OF[status],
                            _anchor=f"livre-{book_id}" if book_id else None))


def owned_reading(reading_id):
    """Lecture de l'utilisateur connecté, ou 404."""
    reading = db.find_reading(g.user["id"], reading_id, db_path())
    if reading is None:
        abort(404)
    return reading


def relearn():
    """Les notes ont changé : profil recalculé depuis ses valeurs initiales."""
    save_learned(g.user["id"], db.load_profile(g.user["id"], db_path()), db_path())


# --- Bibliothèque ---------------------------------------------------------------------

@bp.route("/bibliotheque")
@profile_required
def bibliotheque():
    tab = request.args.get("onglet")
    if tab not in TABS:
        tab = "a-lire"
    counts = db.count_readings(g.user["id"], db_path())
    tabs = [{"slug": slug, "label": label, "count": counts[status]}
            for slug, (status, label) in TABS.items()]
    readings = db.list_readings(g.user["id"], TABS[tab][0], db_path())
    return render_template("library/bibliotheque.html", active="bibliotheque", tab=tab,
                           tabs=tabs, excerpt=EXCERPT, readings=readings,
                           scores=home.scores_for(g.user, shelf_books(readings), db_path()),
                           today=date.today().isoformat())


def shelf_books(readings):
    """Livres complets des lectures (index, sinon base pour un livre masqué)."""
    index = engine.get_index(db_path())
    books = [index.books[index.row_of[r["book_id"]]] if r["book_id"] in index.row_of
             else engine.load_book(r["book_id"], db_path()) for r in readings]
    return [b for b in books if b]


@bp.route("/lecture/<int:reading_id>/monter", methods=["POST"])
@profile_required
def monter(reading_id):
    reading = owned_reading(reading_id)
    db.move_in_pile(g.user["id"], reading_id, -1, db_path())
    return to_tab(db.TO_READ, reading["book_id"])


@bp.route("/lecture/<int:reading_id>/descendre", methods=["POST"])
@profile_required
def descendre(reading_id):
    reading = owned_reading(reading_id)
    db.move_in_pile(g.user["id"], reading_id, +1, db_path())
    return to_tab(db.TO_READ, reading["book_id"])


@bp.route("/lecture/<int:reading_id>/retirer", methods=["GET", "POST"])
@profile_required
def retirer(reading_id):
    """Retrait d'une lecture ; une lecture terminée demande d'abord confirmation."""
    reading = owned_reading(reading_id)
    finished = reading["status"] == db.FINISHED
    if request.method == "GET" or (finished and request.form.get("confirme") != "1"):
        return render_template("library/retirer.html", active="bibliotheque", reading=reading,
                               tab=TAB_OF[reading["status"]])
    db.remove_reading(g.user["id"], reading_id, db_path())
    if finished:
        relearn()
    flash(f"« {reading['title']} » a été retiré de ta bibliothèque.", "success")
    return to_tab(reading["status"])


@bp.route("/lecture/<int:reading_id>/dates", methods=["POST"])
@profile_required
def dates(reading_id):
    reading = owned_reading(reading_id)
    try:
        if db.update_dates(g.user["id"], reading_id, request.form.get("start_date"),
                           request.form.get("end_date"), db_path=db_path()):
            flash("Dates mises à jour.", "success")
    except ValueError as error:
        flash(str(error), "error")
    return to_tab(reading["status"], reading["book_id"])


# --- Avis ----------------------------------------------------------------------------------

def parse_rating(value):
    """'' -> None (pas de note), '1'..'5' -> entier, sinon ValueError."""
    if not value:
        return None
    if value not in {"1", "2", "3", "4", "5"}:
        raise ValueError("La note doit être comprise entre 1 et 5.")
    return int(value)


@bp.route("/lecture/<int:reading_id>/avis", methods=["GET", "POST"])
@profile_required
def avis(reading_id):
    reading = owned_reading(reading_id)
    if reading["status"] != db.FINISHED:
        flash("Tu pourras donner ton avis une fois le livre terminé.", "error")
        return to_tab(reading["status"], reading["book_id"])
    error = None
    rating, comment = reading["rating"], reading["comment"] or ""
    if request.method == "POST":
        comment = request.form.get("comment", "")
        try:
            rating = parse_rating(request.form.get("rating", ""))
            db.save_review(g.user["id"], reading_id, rating, comment, db_path())
        except ValueError as e:
            error = str(e)
        else:
            relearn()
            flash("Ton avis est enregistré.", "success")
            return to_tab(db.FINISHED, reading["book_id"])
    return render_template("library/avis.html", active="bibliotheque", reading=reading,
                           rating=rating, comment=comment, error=error,
                           comment_max=db.COMMENT_MAX)


# --- Profil et statistiques ---------------------------------------------------------------

DIMENSIONS = (("genres", CATEGORY_LABELS), ("themes", THEME_LABELS),
              ("ambiances", AMBIANCE_LABELS))
MOOD_LABELS = {"theme": THEME_LABELS, "ambiance": AMBIANCE_LABELS}


def trends(profile):
    """Écarts appris par les notes : [« Polar +0,10 », ...], les plus marqués d'abord."""
    gaps = []
    for dim, labels in DIMENSIONS:
        initial = profile["initial"][dim]
        for key, value in profile[dim].items():
            gap = round(value - initial.get(key, 0.0), 2)
            if gap:
                gaps.append((abs(gap), f"{labels.get(key, key)} {gap:+.2f}".replace(".", ",")))
    return [text for _, text in sorted(gaps, key=lambda item: -item[0])]


@bp.route("/profil")
@profile_required
def profil():
    user_id = g.user["id"]
    profile = db.load_profile(user_id, db_path())
    data = stats.compute(db.list_finished_for_stats(user_id, db_path()))
    for row in data["moods"]:
        row["label"] = MOOD_LABELS[row["kind"]].get(row["key"], row["key"])
    return render_template(
        "library/profil.html", active="profil", profile=profile,
        confidence=round(profile["confidence"] * 100), trends=trends(profile),
        counts=db.count_readings(user_id, db_path()),
        draft=db.load_draft(user_id, db_path()) is not None,
        stats=data, labels=CATEGORY_LABELS)


@bp.route("/statistiques")
@profile_required
def statistiques():
    return redirect(url_for("library.profil", _anchor="statistiques"))
