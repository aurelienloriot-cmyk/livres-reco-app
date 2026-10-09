"""Connexion SQLite et création du schéma de la base."""

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "books.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY,
    google_id TEXT UNIQUE,
    title TEXT,
    authors TEXT,
    description TEXT,
    categories_raw TEXT,  -- JSON, catégories Google Books
    main_category TEXT,
    categories TEXT,      -- JSON, catégories cibles sous lesquelles le livre a été collecté
    themes TEXT,          -- JSON, liste de thèmes (src.tagging)
    ambiance TEXT,        -- JSON, ambiance ou null (src.tagging)
    published_year INTEGER,
    page_count INTEGER,
    language TEXT,
    isbn TEXT,
    thumbnail TEXT,
    info_link TEXT,
    avg_rating REAL,
    ratings_count INTEGER,
    hidden INTEGER NOT NULL DEFAULT 0  -- 1 = livre mal classé, écarté du catalogue (src.hide)
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    email TEXT,
    password_hash TEXT NOT NULL,
    created_at TEXT,
    profile_label TEXT,
    profile_vector TEXT,  -- JSON, profil complet (src.profile.build_profile)
    profile_confidence REAL,
    profile_family TEXT   -- famille du profil (src.profile.FAMILY_OF)
);

CREATE TABLE IF NOT EXISTS survey_answers (
    user_id INTEGER NOT NULL REFERENCES users(id),
    question_id TEXT NOT NULL,
    answer TEXT,
    answered_at TEXT,
    PRIMARY KEY (user_id, question_id)
);

CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    book_id INTEGER NOT NULL REFERENCES books(id),
    rank INTEGER,         -- position dans la pile à lire ; null une fois commencé
    start_date TEXT,      -- AAAA-MM-JJ
    end_date TEXT,
    rating INTEGER,
    comment TEXT,
    created_at TEXT,
    updated_at TEXT,
    UNIQUE (user_id, book_id)
);

CREATE INDEX IF NOT EXISTS idx_readings_user ON readings(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_readings_rank ON readings(user_id, rank);
CREATE INDEX IF NOT EXISTS idx_readings_book ON readings(book_id);
CREATE INDEX IF NOT EXISTS idx_readings_start ON readings(start_date);
"""


def get_connection(db_path=DB_PATH):
    """Ouvre une connexion SQLite (lignes accessibles par nom de colonne)."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


BOOKS_NEW_COLUMNS = {"categories", "themes", "ambiance"}
BOOKS_ADDED_COLUMNS = {"hidden": "INTEGER NOT NULL DEFAULT 0"}  # ajoutées sans perte
USERS_NEW_COLUMNS = {"email": "TEXT", "profile_confidence": "REAL", "profile_family": "TEXT",
                     "filters": "TEXT",  # filters : JSON (app.filters)
                     "is_demo": "INTEGER NOT NULL DEFAULT 0",  # 1 = compte fictif (src.seed)
                     "draft_answers": "TEXT"}  # JSON, questionnaire refait en cours
READINGS_COLUMNS = "id, user_id, book_id, start_date, end_date, rating, comment"


def migrate_readings(conn):
    """Ancienne table readings (sans rank ni contrainte d'unicité) -> nouveau schéma.

    Les lignes sont recopiées ; pour un même couple (utilisateur, livre), seule la plus
    récente est gardée (la contrainte UNIQUE l'impose). Les livres non commencés
    reçoivent un rang dans la pile, dans l'ordre d'ajout.
    """
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(readings)")}
    if not columns or "rank" in columns:
        return
    conn.execute("ALTER TABLE readings RENAME TO readings_old")
    for index in ("idx_readings_user", "idx_readings_book", "idx_readings_start"):
        conn.execute(f"DROP INDEX IF EXISTS {index}")
    conn.executescript(SCHEMA)
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        f"INSERT INTO readings ({READINGS_COLUMNS}, created_at, updated_at)"
        f" SELECT {READINGS_COLUMNS}, ?, ? FROM readings_old"
        " WHERE id IN (SELECT MAX(id) FROM readings_old GROUP BY user_id, book_id)",
        (now, now),
    )
    conn.execute("DROP TABLE readings_old")
    pile = conn.execute("SELECT id, user_id FROM readings WHERE start_date IS NULL"
                        " ORDER BY user_id, id").fetchall()
    ranks = {}
    for row in pile:
        ranks[row["user_id"]] = ranks.get(row["user_id"], 0) + 1
        conn.execute("UPDATE readings SET rank = ? WHERE id = ?", (ranks[row["user_id"]], row["id"]))


def init_db(db_path=DB_PATH):
    """Crée les tables et index s'ils n'existent pas encore.

    Si la table books date d'un ancien schéma (colonnes manquantes), elle est
    supprimée puis recréée : son contenu est régénéré par src.clean.
    """
    with get_connection(db_path) as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(books)")}
        if columns and not BOOKS_NEW_COLUMNS <= columns:
            conn.execute("DROP TABLE books")
        migrate_readings(conn)
        conn.executescript(SCHEMA)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(books)")}
        for name, sql_type in BOOKS_ADDED_COLUMNS.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE books ADD COLUMN {name} {sql_type}")
        # Colonnes ajoutées à users après coup : ajoutées sans perdre les comptes.
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
        for name, sql_type in USERS_NEW_COLUMNS.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE users ADD COLUMN {name} {sql_type}")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email)")


# --- Profil et réponses au questionnaire ---------------------------------------------

def save_profile(user_id, profile, db_path=DB_PATH):
    """Enregistre le profil (JSON), son libellé, sa confiance et sa famille."""
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE users SET profile_vector = ?, profile_label = ?, profile_confidence = ?,"
            " profile_family = ? WHERE id = ?",
            (json.dumps(profile, ensure_ascii=False), profile["label"], profile["confidence"],
             profile["family"], user_id),
        )


def load_profile(user_id, db_path=DB_PATH):
    """Profil de l'utilisateur, ou None s'il n'a pas encore été calculé."""
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT profile_vector FROM users WHERE id = ?", (user_id,)).fetchone()
    return json.loads(row["profile_vector"]) if row and row["profile_vector"] else None


def save_answer(user_id, question_id, answer, db_path=DB_PATH):
    """Enregistre (ou remplace) la réponse à une question : code ou liste de codes."""
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO survey_answers (user_id, question_id, answer, answered_at)"
            " VALUES (?, ?, ?, ?)",
            (user_id, question_id, json.dumps(answer, ensure_ascii=False),
             datetime.now().isoformat(timespec="seconds")),
        )


def replace_answers(user_id, answers, db_path=DB_PATH):
    """Remplace toutes les réponses de l'utilisateur par answers ({question_id: réponse})."""
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM survey_answers WHERE user_id = ?", (user_id,))
        conn.executemany(
            "INSERT INTO survey_answers (user_id, question_id, answer, answered_at)"
            " VALUES (?, ?, ?, ?)",
            [(user_id, qid, json.dumps(answer, ensure_ascii=False), now_iso())
             for qid, answer in answers.items()],
        )


def load_draft(user_id, db_path=DB_PATH):
    """Brouillon du questionnaire refait ({question_id: réponse}), ou None."""
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT draft_answers FROM users WHERE id = ?", (user_id,)).fetchone()
    return json.loads(row["draft_answers"]) if row and row["draft_answers"] else None


def save_draft(user_id, draft, db_path=DB_PATH):
    """Enregistre le brouillon ; None l'efface."""
    value = None if draft is None else json.dumps(draft, ensure_ascii=False)
    with get_connection(db_path) as conn:
        conn.execute("UPDATE users SET draft_answers = ? WHERE id = ?", (value, user_id))


def load_answers(user_id, db_path=DB_PATH):
    """{question_id: réponse} de l'utilisateur."""
    with get_connection(db_path) as conn:
        rows = conn.execute("SELECT question_id, answer FROM survey_answers WHERE user_id = ?",
                            (user_id,)).fetchall()
    return {row["question_id"]: json.loads(row["answer"]) for row in rows}


# --- Comptes utilisateurs ---------------------------------------------------------------

def create_user(username, email, password_hash, db_path=DB_PATH):
    """Crée un compte et renvoie son id."""
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO users (username, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (username, email, password_hash, datetime.now().isoformat(timespec="seconds")),
        )
        return cursor.lastrowid


def find_user(login, db_path=DB_PATH):
    """Utilisateur dont le pseudo ou l'e-mail vaut login (sans tenir compte de la casse)."""
    with get_connection(db_path) as conn:
        return conn.execute(
            "SELECT * FROM users WHERE lower(username) = lower(?) OR lower(email) = lower(?)",
            (login, login),
        ).fetchone()


def get_user(user_id, db_path=DB_PATH):
    with get_connection(db_path) as conn:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def get_filters(user_id, db_path=DB_PATH):
    """Filtres enregistrés (dict), ou None s'ils n'ont jamais été créés."""
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT filters FROM users WHERE id = ?", (user_id,)).fetchone()
    return json.loads(row["filters"]) if row and row["filters"] else None


def save_filters(user_id, filters, db_path=DB_PATH):
    with get_connection(db_path) as conn:
        conn.execute("UPDATE users SET filters = ? WHERE id = ?",
                     (json.dumps(filters, ensure_ascii=False), user_id))


# --- Lectures -----------------------------------------------------------------------------
# Statut dérivé des dates : à lire (pas de début), en cours (début sans fin), terminé (fin).

TO_READ, READING, FINISHED = "à lire", "en cours", "terminé"


def reading_status(reading):
    if reading["end_date"]:
        return FINISHED
    return READING if reading["start_date"] else TO_READ


def parse_day(value):
    """'AAAA-MM-JJ' -> date, sinon ValueError avec un message affichable."""
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError("Cette date n'est pas valide.") from None


def check_dates(start, end=None, today=None):
    """Règles de saisie : début ≤ fin ≤ aujourd'hui, début jamais dans le futur."""
    today = today or date.today()
    if end is not None and end < start:
        raise ValueError("La date de fin ne peut pas précéder la date de début.")
    if end is not None and end > today:
        raise ValueError("La date de fin ne peut pas être dans le futur.")
    if start > today:
        raise ValueError("La date de début ne peut pas être dans le futur.")


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def get_reading(user_id, book_id, db_path=DB_PATH):
    """Lecture de ce livre par cet utilisateur (dict avec "status"), ou None."""
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM readings WHERE user_id = ? AND book_id = ?",
                           (user_id, book_id)).fetchone()
    return dict(row, status=reading_status(row)) if row else None


def add_to_pile(user_id, book_id, db_path=DB_PATH):
    """Ajoute le livre en fin de pile à lire. False s'il est déjà suivi (pas de doublon)."""
    with get_connection(db_path) as conn:
        now = now_iso()
        try:
            conn.execute(
                "INSERT INTO readings (user_id, book_id, rank, created_at, updated_at)"
                " VALUES (?, ?, (SELECT COALESCE(MAX(rank), 0) + 1 FROM readings"
                " WHERE user_id = ?), ?, ?)",
                (user_id, book_id, user_id, now, now),
            )
        except sqlite3.IntegrityError:
            return False
    return True


def start_reading(user_id, book_id, start_date, today=None, db_path=DB_PATH):
    """Commence un livre (depuis la pile ou directement). La date ne peut pas être future.

    False si le livre est déjà commencé ou terminé ; ValueError si la date est invalide.
    """
    day = parse_day(start_date)
    check_dates(day, today=today)
    reading = get_reading(user_id, book_id, db_path)
    if reading and reading["status"] != TO_READ:
        return False
    with get_connection(db_path) as conn:
        now = now_iso()
        if reading is None:
            try:
                conn.execute(
                    "INSERT INTO readings (user_id, book_id, start_date, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?)", (user_id, book_id, day.isoformat(), now, now))
            except sqlite3.IntegrityError:  # double soumission simultanée
                return False
            return True
        updated = conn.execute(
            "UPDATE readings SET start_date = ?, rank = NULL, updated_at = ?"
            " WHERE id = ? AND start_date IS NULL", (day.isoformat(), now, reading["id"]))
        if updated.rowcount:
            close_gap(conn, user_id, reading["rank"])
    return bool(updated.rowcount)


def close_gap(conn, user_id, rank):
    """La pile se resserre après le départ du rang rank : les livres suivants avancent
    d'un rang (ordre croissant pour ne jamais violer l'unicité du rang)."""
    later = conn.execute("SELECT id FROM readings WHERE user_id = ? AND rank > ?"
                         " ORDER BY rank", (user_id, rank)).fetchall()
    for row in later:
        conn.execute("UPDATE readings SET rank = rank - 1 WHERE id = ?", (row["id"],))


def finish_reading(user_id, book_id, end_date, today=None, db_path=DB_PATH):
    """Termine un livre en cours : début ≤ fin ≤ aujourd'hui, sinon ValueError.

    False si le livre n'est pas en cours (absent, à lire ou déjà terminé).
    """
    day = parse_day(end_date)
    reading = get_reading(user_id, book_id, db_path)
    if reading is None or reading["status"] != READING:
        return False
    check_dates(date.fromisoformat(reading["start_date"]), day, today)
    with get_connection(db_path) as conn:
        updated = conn.execute(
            "UPDATE readings SET end_date = ?, updated_at = ? WHERE id = ? AND end_date IS NULL",
            (day.isoformat(), now_iso(), reading["id"]))
    return bool(updated.rowcount)


LIST_ORDER = {
    TO_READ: ("r.start_date IS NULL", "r.rank"),
    READING: ("r.start_date IS NOT NULL AND r.end_date IS NULL", "r.start_date DESC, r.id DESC"),
    FINISHED: ("r.end_date IS NOT NULL", "r.end_date DESC, r.id DESC"),
}


def query_readings(sql, params, db_path=DB_PATH):
    """Lectures (avec titre, auteurs et couverture du livre) choisies par la clause sql.

    Les livres masqués (hidden) restent listés : la lecture appartient à l'utilisateur."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT r.*, b.title, b.authors, b.isbn, b.thumbnail, b.hidden FROM readings r"
            f" JOIN books b ON b.id = r.book_id {sql}", params).fetchall()
    return [dict(row, status=reading_status(row),
                 authors=json.loads(row["authors"]) if row["authors"] else []) for row in rows]


def list_readings(user_id, status=None, db_path=DB_PATH):
    """Lectures de l'utilisateur avec le titre, les auteurs et la couverture du livre.

    status : TO_READ (par rang), READING ou FINISHED (plus récent d'abord), None = toutes.
    """
    where, order = LIST_ORDER[status] if status else ("1", "r.updated_at DESC, r.id DESC")
    return query_readings(f"WHERE r.user_id = ? AND {where} ORDER BY {order}", (user_id,),
                          db_path)


def find_reading(user_id, reading_id, db_path=DB_PATH):
    """Lecture d'id reading_id si elle appartient à l'utilisateur, sinon None."""
    rows = query_readings("WHERE r.id = ? AND r.user_id = ?", (reading_id, user_id), db_path)
    return rows[0] if rows else None


def count_readings(user_id, db_path=DB_PATH):
    """{TO_READ: n, READING: n, FINISHED: n}."""
    counts = {TO_READ: 0, READING: 0, FINISHED: 0}
    for reading in list_readings(user_id, db_path=db_path):
        counts[reading["status"]] += 1
    return counts


# --- Bibliothèque : pile, retrait, dates, avis --------------------------------------------

def move_in_pile(user_id, reading_id, step, db_path=DB_PATH):
    """Échange le livre avec son voisin de pile : step = -1 (monter) ou +1 (descendre).

    False s'il n'est pas dans la pile ou déjà en bout de pile.
    """
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT rank FROM readings WHERE id = ? AND user_id = ?"
                           " AND rank IS NOT NULL", (reading_id, user_id)).fetchone()
        if row is None:
            return False
        rank = row["rank"]
        other = conn.execute("SELECT id FROM readings WHERE user_id = ? AND rank = ?",
                             (user_id, rank + step)).fetchone()
        if other is None:
            return False
        # Rang libéré d'abord : l'unicité (user_id, rank) n'est jamais violée.
        conn.execute("UPDATE readings SET rank = NULL WHERE id = ?", (reading_id,))
        conn.execute("UPDATE readings SET rank = ? WHERE id = ?", (rank, other["id"]))
        conn.execute("UPDATE readings SET rank = ? WHERE id = ?", (rank + step, reading_id))
    return True


def remove_reading(user_id, reading_id, db_path=DB_PATH):
    """Supprime la lecture (avec sa note et son avis) ; la renvoie, ou None si absente."""
    reading = find_reading(user_id, reading_id, db_path)
    if reading is None:
        return None
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM readings WHERE id = ?", (reading_id,))
        if reading["rank"] is not None:
            close_gap(conn, user_id, reading["rank"])
    return reading


def update_dates(user_id, reading_id, start_date, end_date=None, today=None, db_path=DB_PATH):
    """Modifie le début (lecture en cours) ou le début et la fin (lecture terminée), avec
    les mêmes règles qu'à la saisie. False si la lecture n'est ni en cours ni terminée."""
    reading = find_reading(user_id, reading_id, db_path)
    if reading is None or reading["status"] == TO_READ:
        return False
    start = parse_day(start_date)
    end = parse_day(end_date) if reading["status"] == FINISHED else None
    check_dates(start, end, today)
    with get_connection(db_path) as conn:
        conn.execute("UPDATE readings SET start_date = ?, end_date = ?, updated_at = ?"
                     " WHERE id = ?",
                     (start.isoformat(), end and end.isoformat(), now_iso(), reading_id))
    return True


COMMENT_MAX = 2000


def save_review(user_id, reading_id, rating, comment, db_path=DB_PATH):
    """Enregistre la note (1 à 5, ou None = pas de note) et le commentaire privé d'une
    lecture terminée ; remplace l'avis précédent. False si la lecture n'est pas terminée."""
    if rating is not None and rating not in range(1, 6):
        raise ValueError("La note doit être comprise entre 1 et 5.")
    comment = (comment or "").strip() or None
    if comment and len(comment) > COMMENT_MAX:
        raise ValueError(f"Ton commentaire dépasse {COMMENT_MAX} caractères.")
    reading = find_reading(user_id, reading_id, db_path)
    if reading is None or reading["status"] != FINISHED:
        return False
    with get_connection(db_path) as conn:
        conn.execute("UPDATE readings SET rating = ?, comment = ?, updated_at = ? WHERE id = ?",
                     (rating, comment, now_iso(), reading_id))
    return True


def list_ratings(user_id, db_path=DB_PATH):
    """[(book_id, note)] des lectures notées de l'utilisateur."""
    with get_connection(db_path) as conn:
        rows = conn.execute("SELECT book_id, rating FROM readings WHERE user_id = ?"
                            " AND rating IS NOT NULL ORDER BY id", (user_id,)).fetchall()
    return [(row["book_id"], row["rating"]) for row in rows]


def list_finished_for_stats(user_id, db_path=DB_PATH):
    """Lectures terminées avec auteurs, pages, catégories, thèmes et ambiance (src.stats)."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT r.id, r.book_id, r.start_date, r.end_date, r.rating, b.title, b.authors,"
            " b.page_count, b.categories, b.themes, b.ambiance FROM readings r"
            " JOIN books b ON b.id = r.book_id"
            " WHERE r.user_id = ? AND r.end_date IS NOT NULL ORDER BY r.id",
            (user_id,)).fetchall()
    return [dict(row, **{key: json.loads(row[key]) if row[key] else default
                         for key, default in (("authors", []), ("categories", []),
                                              ("themes", []), ("ambiance", None))})
            for row in rows]
