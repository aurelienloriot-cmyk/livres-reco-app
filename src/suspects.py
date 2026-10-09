"""Livres non masqués qui ressemblent à des essais sur la littérature, à passer en revue
avant de les masquer avec src.hide.

Critères (sans accents ni casse) : la description contient une des expressions de
DESCRIPTION_HINTS, ou le titre suit le schéma « ... : de X à Y ».

Usage : python -m src.suspects
"""

import json
import re
import sys

from src import db, engine

DESCRIPTION_HINTS = ["ce livre", "cet ouvrage", "l'auteur", "etudi", "analys", "oeuvre de"]
TITLE_RE = re.compile(r" : de .+ a ")


def simplify(text):
    """Comme engine.normalize, avec œ -> oe et apostrophe typographique -> droite."""
    return engine.normalize(text or "").replace("œ", "oe").replace("’", "'")


def reasons(book):
    """Critères remplis par le livre (liste vide si aucun)."""
    description = simplify(book["description"])
    found = [f"« {hint} »" for hint in DESCRIPTION_HINTS if hint in description]
    if TITLE_RE.search(simplify(book["title"])):
        found.append("titre « de X à Y »")
    return found


def find_suspects(db_path=db.DB_PATH):
    """[(livre, critères)] des livres non masqués, par id."""
    with db.get_connection(db_path) as conn:
        rows = conn.execute("SELECT * FROM books WHERE hidden = 0 ORDER BY id").fetchall()
    return [(row, found) for row in rows if (found := reasons(row))]


def main(db_path=db.DB_PATH):
    suspects = find_suspects(db_path)
    for row, found in suspects:
        authors = ", ".join(json.loads(row["authors"]) if row["authors"] else []) or "?"
        print(f"{row['id']:>5}  {row['title']} — {authors} [{row['main_category']}]"
              f"  ({', '.join(found)})")
    print(f"\n{len(suspects)} livres suspects. Masquer : python -m src.hide <id>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
