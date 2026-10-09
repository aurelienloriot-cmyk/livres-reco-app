"""Masquage des livres mal classés (essais sur la littérature, catalogues...).

Un livre masqué (books.hidden = 1) reste dans la base : les ids ne bougent pas et
les lectures existantes restent dans la bibliothèque de leur propriétaire. Il
disparaît de l'index TF-IDF, donc des recommandations, de la recherche et de l'accueil.

La liste est versionnée dans src/hidden_books.txt (un google_id par ligne, titre en
commentaire) : après une reconstruction de la base par src.clean, --apply la remasque.

Usage :
    python -m src.hide "titre partiel ou id"
    python -m src.hide --apply
    python -m src.hide --list
"""

import json
import sys
from pathlib import Path

from src import db, engine

HIDDEN_FILE = Path(__file__).resolve().parent / "hidden_books.txt"


def read_hidden_file(path=HIDDEN_FILE):
    """google_ids du fichier, dans l'ordre (commentaires « # ... » et lignes vides ignorés)."""
    if not path.exists():
        return []
    ids = [line.split("#", 1)[0].strip() for line in path.read_text(encoding="utf-8").splitlines()]
    return [i for i in ids if i]


def append_hidden_file(book, path=HIDDEN_FILE):
    """Ajoute « google_id  # titre — auteurs » au fichier, sauf s'il y est déjà."""
    if book["google_id"] in read_hidden_file(path):
        return
    authors = ", ".join(json.loads(book["authors"]) if book["authors"] else [])
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{book['google_id']}  # {book['title']}" + (f" — {authors}" if authors else "") + "\n")


def find_matches(query, db_path=db.DB_PATH):
    """Livres dont l'id ou le google_id vaut query, sinon dont le titre la contient
    (sans accents ni casse)."""
    with db.get_connection(db_path) as conn:
        rows = conn.execute("SELECT * FROM books ORDER BY id").fetchall()
    exact = [r for r in rows if query in (str(r["id"]), r["google_id"])]
    if exact:
        return exact
    q = engine.normalize(query)
    return [r for r in rows if q in engine.normalize(r["title"] or "")]


def invalidate_index(db_path=db.DB_PATH):
    """Supprime data/tfidf.pkl et vide le cache mémoire : l'index sera reconstruit.
    (Une application déjà lancée garde son index en mémoire : la relancer.)"""
    Path(db_path).parent.joinpath("tfidf.pkl").unlink(missing_ok=True)
    engine.reset_cache()


def hide_books(book_ids, db_path=db.DB_PATH, hidden_file=HIDDEN_FILE):
    """Masque les livres et les ajoute au fichier ; renvoie le nombre de livres masqués."""
    with db.get_connection(db_path) as conn:
        for book_id in book_ids:
            conn.execute("UPDATE books SET hidden = 1 WHERE id = ?", (book_id,))
            append_hidden_file(conn.execute("SELECT * FROM books WHERE id = ?",
                                            (book_id,)).fetchone(), hidden_file)
    invalidate_index(db_path)
    return len(book_ids)


def apply_hidden_file(db_path=db.DB_PATH, hidden_file=HIDDEN_FILE):
    """Remasque tous les livres du fichier : (masqués, google_ids absents de la base)."""
    ids = read_hidden_file(hidden_file)
    missing = []
    with db.get_connection(db_path) as conn:
        for google_id in ids:
            if not conn.execute("UPDATE books SET hidden = 1 WHERE google_id = ?",
                                (google_id,)).rowcount:
                missing.append(google_id)
    invalidate_index(db_path)
    return len(ids) - len(missing), missing


def describe(row):
    authors = ", ".join(json.loads(row["authors"]) if row["authors"] else []) or "auteur inconnu"
    status = " [déjà masqué]" if row["hidden"] else ""
    return f"{row['title']} — {authors} ({row['published_year'] or '?'}, id {row['id']}){status}"


def choose(matches):
    """Plusieurs correspondances : l'utilisateur choisit les numéros à masquer."""
    for n, row in enumerate(matches, 1):
        print(f"  {n}. {describe(row)}")
    answer = input("Numéros à masquer (ex. 1,3 ; « tous » ; vide pour annuler) : ").strip()
    if answer.lower() == "tous":
        return matches
    try:
        return [matches[int(n) - 1] for n in answer.replace(" ", "").split(",") if n]
    except (ValueError, IndexError):
        print("Réponse invalide, rien n'est masqué.")
        return []


def main(argv, db_path=db.DB_PATH):
    db.init_db(db_path)
    if argv == ["--apply"]:
        count, missing = apply_hidden_file(db_path)
        print(f"{count} livres masqués d'après {HIDDEN_FILE.name}.")
        if missing:
            print("Absents de la base : " + ", ".join(missing))
        return 0
    if argv == ["--list"]:
        with db.get_connection(db_path) as conn:
            rows = conn.execute("SELECT * FROM books WHERE hidden = 1 ORDER BY id").fetchall()
        for row in rows:
            print(f"  {describe(row)}")
        print(f"{len(rows)} livres masqués.")
        return 0
    if len(argv) != 1 or argv[0].startswith("--"):
        print(__doc__.split("Usage :")[1].rstrip())
        return 1

    matches = find_matches(argv[0], db_path)
    if not matches:
        print(f"Aucun livre ne correspond à « {argv[0]} ».")
        return 1
    if len(matches) == 1:
        print(describe(matches[0]))
        chosen = matches
    else:
        print(f"{len(matches)} livres correspondent :")
        chosen = choose(matches)
    chosen = [row for row in chosen if not row["hidden"]]
    if chosen:
        hide_books([row["id"] for row in chosen], db_path)
        print(f"{len(chosen)} livre(s) masqué(s), ajouté(s) à {HIDDEN_FILE.name}.")
    else:
        print("Rien à masquer.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
