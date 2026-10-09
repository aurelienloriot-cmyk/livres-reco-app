"""Questionnaire : une question par page, reprise automatique, création du profil,
questionnaire refait (brouillon)."""

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from app.auth import db_path, login_required, profile_required
from app.filters import from_answers
from src import db
from src.profile import build_profile, save_learned
from src.questions import NEUTRAL, QUESTIONS

bp = Blueprint("survey", __name__)

TOTAL = len(QUESTIONS)
EXCLUSIVE = {NEUTRAL, "aucun"}  # options qui désélectionnent toutes les autres
OTHER_TEXT_ID = "q1_autre"      # texte libre de l'option « Autre » (q1), sans effet sur le profil


def first_unanswered(answers):
    """Numéro (1-10) de la première question sans réponse, ou None si tout est répondu."""
    for n, question in enumerate(QUESTIONS, 1):
        if question["id"] not in answers:
            return n
    return None


def clean_answer(question, values):
    """Codes envoyés -> réponse à enregistrer (liste ou code), ou None si invalide."""
    allowed = {o["code"] for o in question["options"]}
    codes = [v for v in dict.fromkeys(values) if v in allowed]
    for code in EXCLUSIVE:
        if code in codes:
            codes = [code]
    if not codes:
        return None
    if question["type"] == "single":
        return codes[0] if len(codes) == 1 else None
    return codes


@bp.route("/questionnaire")
@login_required
def questionnaire():
    """Point d'entrée : reprend à la première question sans réponse."""
    if g.user["profile_vector"]:
        return redirect(url_for("main.accueil"))
    n = first_unanswered(db.load_answers(g.user["id"], db_path())) or TOTAL
    return redirect(url_for("survey.question", n=n))


@bp.route("/questionnaire/<int:n>", methods=["GET", "POST"])
@login_required
def question(n):
    if g.user["profile_vector"]:
        return redirect(url_for("main.accueil"))
    user_id = g.user["id"]

    def store(question_id, answer):
        db.save_answer(user_id, question_id, answer, db_path())

    return ask(n, db.load_answers(user_id, db_path()), "survey.question", store,
               lambda: finish(user_id))


def ask(n, answers, endpoint, store, done, retake=False):
    """Affiche la question n ou enregistre sa réponse via store(question_id, réponse) ;
    done() est appelé une fois la question 10 validée."""
    if not 1 <= n <= TOTAL:
        abort(404)
    # Pas de saut en avant : on ne dépasse pas la première question sans réponse.
    resume = first_unanswered(answers)
    if resume is not None and n > resume:
        return redirect(url_for(endpoint, n=resume))

    q = QUESTIONS[n - 1]
    error = None
    if request.method == "POST":
        answer = clean_answer(q, request.form.getlist("answer"))
        if answer is None:
            error = ("Choisis une réponse pour continuer." if q["type"] == "single"
                     else "Choisis au moins une réponse pour continuer.")
        else:
            store(q["id"], answer)
            if q["id"] == "q1":
                text = request.form.get("autre", "").strip()[:100] if "autre" in answer else ""
                store(OTHER_TEXT_ID, text)
            if n < TOTAL:
                return redirect(url_for(endpoint, n=n + 1))
            return done()

    saved = answers.get(q["id"])
    selected = [saved] if isinstance(saved, str) else (saved or [])
    return render_template("survey/question.html", q=q, n=n, total=TOTAL, selected=selected,
                           other_text=answers.get(OTHER_TEXT_ID, ""), exclusive=EXCLUSIVE,
                           error=error, endpoint=endpoint, retake=retake)


def finish(user_id):
    """Question 10 validée : calcul et enregistrement du profil."""
    answers = db.load_answers(user_id, db_path())
    resume = first_unanswered(answers)
    if resume is not None:
        return redirect(url_for("survey.question", n=resume))
    db.save_profile(user_id, build_profile(answers), db_path())
    return redirect(url_for("survey.profil_cree"))


@bp.route("/profil-cree")
@profile_required
def profil_cree():
    return render_template("survey/profil_cree.html",
                           profile=db.load_profile(g.user["id"], db_path()))


# --- Refaire le questionnaire ----------------------------------------------------------
# Les réponses vont dans un brouillon (users.draft_answers) : le profil actif ne change
# qu'à la validation de la question 10.

@bp.route("/questionnaire/refaire")
@profile_required
def refaire():
    """Commence le brouillon, ou le reprend à la première question sans réponse."""
    draft = db.load_draft(g.user["id"], db_path())
    if draft is None:
        db.save_draft(g.user["id"], {}, db_path())
        draft = {}
    return redirect(url_for("survey.refaire_question", n=first_unanswered(draft) or TOTAL))


@bp.route("/questionnaire/refaire/<int:n>", methods=["GET", "POST"])
@profile_required
def refaire_question(n):
    user_id = g.user["id"]
    draft = db.load_draft(user_id, db_path())
    if draft is None:
        return redirect(url_for("survey.refaire"))

    def store(question_id, answer):
        draft[question_id] = answer
        db.save_draft(user_id, draft, db_path())

    return ask(n, draft, "survey.refaire_question", store, lambda: finish_retake(user_id),
               retake=True)


def finish_retake(user_id):
    """Brouillon complet : il remplace les réponses, le profil est recalculé (questionnaire
    neuf + toutes les notes), les filtres de départ suivent, le brouillon est effacé."""
    draft = db.load_draft(user_id, db_path()) or {}
    resume = first_unanswered(draft)
    if resume is not None:
        return redirect(url_for("survey.refaire_question", n=resume))
    db.replace_answers(user_id, draft, db_path())
    save_learned(user_id, build_profile(draft), db_path())
    db.save_filters(user_id, from_answers(draft), db_path())
    db.save_draft(user_id, None, db_path())
    flash("Ton profil est à jour avec tes nouvelles réponses.", "success")
    return redirect(url_for("library.profil"))


@bp.route("/questionnaire/refaire/abandonner", methods=["POST"])
@profile_required
def abandonner():
    db.save_draft(g.user["id"], None, db_path())
    flash("Brouillon abandonné : ton profil n'a pas changé.", "success")
    return redirect(url_for("library.profil"))
