"""Comptes : inscription, connexion, déconnexion et protection des pages."""

import functools
import re

from flask import (Blueprint, current_app, g, redirect, render_template, request, session,
                   url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from src import db

bp = Blueprint("auth", __name__)

MIN_PASSWORD = 8
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def db_path():
    return current_app.config["DB_PATH"]


@bp.before_app_request
def load_user():
    """Place l'utilisateur connecté (ou None) dans g.user pour chaque requête."""
    user_id = session.get("user_id")
    g.user = db.get_user(user_id, db_path()) if user_id else None
    if user_id and g.user is None:  # compte supprimé : session obsolète
        session.clear()


def login_required(view):
    """Connexion obligatoire (utilisé par le questionnaire)."""
    @functools.wraps(view)
    def wrapped(**kwargs):
        if g.user is None:
            return redirect(url_for("auth.connexion"))
        return view(**kwargs)
    return wrapped


def profile_required(view):
    """Connexion ET profil calculé obligatoires : sinon connexion, puis questionnaire."""
    @functools.wraps(view)
    def wrapped(**kwargs):
        if g.user is None:
            return redirect(url_for("auth.connexion"))
        if not g.user["profile_vector"]:
            return redirect(url_for("survey.questionnaire"))
        return view(**kwargs)
    return wrapped


@bp.route("/inscription", methods=["GET", "POST"])
def inscription():
    if g.user:
        return redirect(url_for("main.accueil"))
    form = request.form
    errors = []
    if request.method == "POST":
        username = form.get("username", "").strip()
        email = form.get("email", "").strip().lower()
        password = form.get("password", "")

        if not 3 <= len(username) <= 30 or "@" in username:
            errors.append("Choisis un pseudo de 3 à 30 caractères, sans « @ ».")
        if not EMAIL_RE.match(email):
            errors.append("Ton adresse e-mail ne semble pas valide.")
        if len(password) < MIN_PASSWORD:
            errors.append(f"Ton mot de passe doit faire au moins {MIN_PASSWORD} caractères.")
        elif password != form.get("confirm", ""):
            errors.append("Les deux mots de passe ne correspondent pas.")
        if not errors:
            if db.find_user(username, db_path()):
                errors.append("Ce pseudo est déjà pris, choisis-en un autre.")
            if db.find_user(email, db_path()):
                errors.append("Un compte existe déjà avec cet e-mail : connecte-toi.")
        if not errors:
            user_id = db.create_user(username, email, generate_password_hash(password),
                                     db_path())
            session.clear()
            session["user_id"] = user_id
            return redirect(url_for("survey.questionnaire"))
    return render_template("auth/inscription.html", errors=errors, form=form)


@bp.route("/connexion", methods=["GET", "POST"])
def connexion():
    if g.user:
        return redirect(url_for("main.accueil"))
    errors = []
    if request.method == "POST":
        user = db.find_user(request.form.get("login", "").strip(), db_path())
        if user is None or not check_password_hash(user["password_hash"],
                                                   request.form.get("password", "")):
            errors.append("Pseudo, e-mail ou mot de passe incorrect.")
        else:
            session.clear()
            session["user_id"] = user["id"]
            return redirect(url_for("main.accueil"))  # le gating renvoie au questionnaire
    return render_template("auth/connexion.html", errors=errors, form=request.form)


@bp.route("/deconnexion")
def deconnexion():
    session.clear()
    return redirect(url_for("auth.connexion"))
