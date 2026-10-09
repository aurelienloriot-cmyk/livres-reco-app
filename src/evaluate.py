"""Évaluation du MVP contre les critères de réussite.

Produit docs/evaluation.md (rapport daté, tableau de synthèse critère → mesure → verdict)
et docs/evaluation_humaine.md (grille de cohérence à remplir par le groupe). La grille
n'est pas écrasée si elle existe déjà, sauf avec --refaire-humaine.

1. Catalogue : livres uniques non masqués, répartition, couverture thèmes et ambiance.
2. Recherche : 20 requêtes imparfaites (tests/fixtures/recherche_20.json), livre visé
   dans les 5 premiers résultats.
3. Recommandations : similar_books sur 30 livres tirés au hasard, « Choisis pour toi »
   sur les profils de démo ; 5 résultats distincts expliqués.
4. Performance : client de test Flask sur data/books.db, 50 appels par page.
5. Cohérence humaine : 8 profils de démo (un par famille + 2).
6. Diversité : catégories distinctes par profil, livres « passe-partout », avant et après
   la contrainte de profile.diversify (au plus 3 livres de même catégorie).

Usage : python -m src.evaluate [--refaire-humaine]
"""

import json
import random
import statistics
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from app import create_app
from app import filters as user_filters
from src import db, engine, home
from src.db import DB_PATH
from src.engine import normalize
from src.profile import FAMILIES, MAX_PER_CATEGORY
from src.questions import AMBIANCE_LABELS, CATEGORY_LABELS, QUESTIONS_BY_ID, THEME_LABELS
from src.stats import MONTHS

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "docs" / "evaluation.md"
HUMAN = ROOT / "docs" / "evaluation_humaine.md"
QUERIES = ROOT / "tests" / "fixtures" / "recherche_20.json"

SEED = 2026
N = 5                    # résultats attendus (recherche : rang maximal, recommandations : nombre)
MIN_BOOKS = 500
MIN_FOUND = 15           # requêtes réussies sur 20
TARGET_FOUND = 18        # objectif après la recherche approchée
SIMILAR_SAMPLE = 30
CALLS = 50
MAX_MS, TARGET_MS = 3000, 1000
HUMAN_EXTRA = 2          # profils en plus des 6 familles (pris dans les familles les plus grandes)
MIN_COHERENT = 3
WIDESPREAD = 10          # « passe-partout » : livre recommandé à plus de 10 profils
PREFIX = "Recommandé pour"


def pct(part, total):
    return f"{100 * part / total:.1f} %" if total else "-"


def verdict(ok):
    return "✅ atteint" if ok else "❌ non atteint"


def table(header, rows):
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c).replace("|", "\\|") for c in row) + " |" for row in rows]
    return "\n".join(lines)


def today_fr(moment):
    return f"{moment.day} {MONTHS[moment.month - 1]} {moment.year} à {moment:%H:%M}"


# --- 1. Catalogue ---------------------------------------------------------------------------

def catalogue(index):
    """Livres non masqués, dédoublonnés sur (titre, premier auteur) sans accents ni casse."""
    keys = {(normalize(b["title"]).strip(), normalize(b["authors"][0]).strip() if b["authors"]
             else "") for b in index.books}
    books = index.books
    return {
        "indexed": len(books),
        "unique": len(keys),
        "categories": Counter(b["main_category"] for b in books).most_common(),
        "with_themes": sum(1 for b in books if b["themes"]),
        "with_ambiance": sum(1 for b in books if b["ambiance"]),
        "themes": Counter(t for b in books for t in b["themes"]).most_common(),
        "ambiances": Counter(b["ambiance"] for b in books if b["ambiance"]).most_common(),
    }


# --- 2. Recherche ---------------------------------------------------------------------------

def search(index, queries):
    """Rang du livre visé dans engine.find_book (même ordre que /recherche), ou None."""
    rows = []
    for q in queries:
        ids = [b["id"] for b in engine.find_book(index, q["requete"])]
        rank = ids.index(q["id"]) + 1 if q["id"] in ids else None
        rows.append(dict(q, rank=rank, total=len(ids), found=rank is not None and rank <= N))
    return rows


# --- 3. Recommandations ---------------------------------------------------------------------

def check(results, source_id=None):
    """Liste des défauts d'une liste de recommandations (vide si correcte)."""
    ids = [r["book"]["id"] for r in results]
    problems = []
    if len(results) != N:
        problems.append(f"{len(results)} résultats")
    if len(set(ids)) != len(ids):
        problems.append("doublons")
    if source_id in ids:
        problems.append("contient le livre source")
    if any(not r["explanation"].startswith(PREFIX) for r in results):
        problems.append("explication manquante")
    return problems


def similar_check(index):
    sample = random.Random(SEED).sample([b["id"] for b in index.books], SIMILAR_SAMPLE)
    failures = []
    for book_id in sample:
        problems = check(engine.similar_books(book_id, N), book_id)
        if problems:
            failures.append((index.books[index.row_of[book_id]]["title"], ", ".join(problems)))
    return {"tested": len(sample), "failures": failures}


def demo_users(db_path=DB_PATH):
    with db.get_connection(db_path) as conn:
        return conn.execute("SELECT * FROM users WHERE is_demo = 1 ORDER BY id").fetchall()


def pour_toi(user, db_path=DB_PATH, max_per_category=MAX_PER_CATEGORY):
    """« Choisis pour toi » tel que l'accueil le calcule : filtres du compte, hors
    bibliothèque, popularité du groupe (sans l'ordre renouvelé, propre à la session).
    max_per_category=None : sans la contrainte de diversité (mesure « avant »)."""
    saved = db.get_filters(user["id"], db_path) or user_filters.from_answers(
        db.load_answers(user["id"], db_path))
    flt = user_filters.to_engine(dict(user_filters.DEFAULTS, **saved))
    return home.pour_toi(user, N, flt, db_path=db_path, max_per_category=max_per_category)


# --- 4. Performance -------------------------------------------------------------------------

def p95(values):
    """Rang le plus proche : la valeur sous laquelle se trouvent 95 % des mesures."""
    ordered = sorted(values)
    return ordered[max(0, -(-95 * len(ordered) // 100) - 1)]


def performance(user_id, queries, index):
    """{page: (médiane ms, p95 ms, erreurs)} ; un premier appel par page (chargement de
    l'index et des gabarits) est exclu des mesures."""
    app = create_app({"TESTING": True, "SECRET_KEY": "evaluation", "DB_PATH": DB_PATH})
    client = app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = user_id
    rng = random.Random(SEED)
    book_ids = [b["id"] for b in index.books]
    pages = {
        "/accueil": lambda i: "/accueil",
        "/recherche?q=…": lambda i: f"/recherche?q={queries[i % len(queries)]['requete']}",
        "/livre/<id>": lambda i: f"/livre/{rng.choice(book_ids)}",
        "/explorer": lambda i: "/explorer",
    }
    results = {}
    for name, url in pages.items():
        client.get(url(0))
        times, errors = [], 0
        for i in range(CALLS):
            start = time.perf_counter()
            response = client.get(url(i))
            times.append((time.perf_counter() - start) * 1000)
            errors += response.status_code != 200
        results[name] = (statistics.median(times), p95(times), errors)
    return results


# --- 5. Cohérence humaine -------------------------------------------------------------------

def human_profiles(users):
    """Premier profil de chaque famille, puis le deuxième des familles les plus peuplées."""
    by_family = {f: [u for u in users if u["profile_family"] == f] for f in FAMILIES}
    chosen = [members[0] for members in by_family.values() if members]
    largest = sorted(by_family.values(), key=len, reverse=True)[:HUMAN_EXTRA]
    return chosen + [members[1] for members in largest if len(members) > 1]


def answer_text(qid, answer):
    labels = {o["code"]: o["label"] for o in QUESTIONS_BY_ID[qid]["options"]}
    codes = answer if isinstance(answer, list) else [answer]
    return ", ".join(labels.get(c, c) for c in codes) if codes else "-"


def human_grid(entries, moment):
    keys = [("q1", "Genres"), ("q2", "Thèmes"), ("q3", "Ambiances"), ("q5", "Longueur"),
            ("q8", "À éviter"), ("q10", "Découverte")]
    lines = [
        "# Évaluation humaine des recommandations",
        "",
        f"_Grille générée le {today_fr(moment)} par `python -m src.evaluate`._",
        "",
        f"Pour chaque profil, chaque membre du groupe lit les réponses puis juge si chacune "
        f"des 5 recommandations « Choisis pour toi » est cohérente (oui/non). "
        f"Critère : au moins {MIN_COHERENT}/5 jugées cohérentes par profil.",
    ]
    for user, results in entries:
        answers = db.load_answers(user["id"])
        lines += ["", f"## {user['username']} — {user['profile_label']} "
                      f"(famille {user['profile_family']})", ""]
        lines += [f"- **{label}** : {answer_text(q, answers.get(q, []))}" for q, label in keys]
        lines += ["", table(
            ["#", "Livre", "Catégorie", "Explication", "Cohérent ? (oui/non)"],
            [(i, f"{r['book']['title']} — {', '.join(r['book']['authors'])}",
              CATEGORY_LABELS.get(r["book"]["main_category"], r["book"]["main_category"]),
              r["explanation"], "") for i, r in enumerate(results, 1)]),
            "", "Score : ___ / 5"]
    return "\n".join(lines) + "\n"


# --- 6. Diversité ---------------------------------------------------------------------------

def diversity(recos):
    """recos : {pseudo: résultats}. Part des catégories distinctes par profil, livres
    recommandés à plus de WIDESPREAD profils."""
    shares = {name: len({r["book"]["main_category"] for r in results}) / N
              for name, results in recos.items() if results}
    counts = Counter(r["book"]["id"] for results in recos.values() for r in results)
    titles = {r["book"]["id"]: r["book"]["title"] for results in recos.values() for r in results}
    widespread = [(titles[i], c) for i, c in counts.most_common() if c > WIDESPREAD]
    crowded = sum(1 for results in recos.values() if results and max(Counter(
        r["book"]["main_category"] for r in results).values()) > MAX_PER_CATEGORY)
    return {"mean": statistics.mean(shares.values()), "min": min(shares.values()),
            "distinct": len(counts), "widespread": widespread, "crowded": crowded,
            "top": [(titles[i], c) for i, c in counts.most_common(5)]}


# --- Rapport --------------------------------------------------------------------------------

def report(moment, cat, found, similar, recos, failures, perf, human, div, before):
    n_found = sum(r["found"] for r in found)
    n_recos = len(recos)
    perf_max = max(p for _, p, _ in perf.values())
    perf_errors = sum(e for _, _, e in perf.values())
    synthese = [
        ("Catalogue ≥ 500 livres uniques", f"{cat['unique']} livres", verdict(
            cat["unique"] >= MIN_BOOKS)),
        ("Recherche : livre visé dans le top 5 pour ≥ 15/20", f"{n_found}/20",
         verdict(n_found >= MIN_FOUND)
         + (f" (objectif ≥ {TARGET_FOUND} atteint)" if n_found >= TARGET_FOUND else "")),
        ("Livres proches : 5 résultats distincts expliqués", f"{len(similar['failures'])} échec(s) "
         f"sur {similar['tested']}", verdict(not similar["failures"])),
        ("« Choisis pour toi » : 5 résultats expliqués", f"{len(failures)} échec(s) sur "
         f"{n_recos} profils", verdict(not failures)),
        ("Temps de réponse < 3 s (objectif CDC < 1 s)", f"p95 max {perf_max:.0f} ms, "
         f"{perf_errors} erreur(s)", verdict(perf_max < MAX_MS and not perf_errors)
         + (" (objectif < 1 s atteint)" if perf_max < TARGET_MS else "")),
        ("Cohérence humaine ≥ 3/5 par profil", f"{len(human)} profils à juger",
         "⏳ à remplir (docs/evaluation_humaine.md)"),
        ("Diversité (indicatif)", f"{div['mean'] * 100:.0f} % de catégories distinctes en "
         f"moyenne (avant contrainte : {before['mean'] * 100:.0f} %), "
         f"{len(div['widespread'])} livre(s) passe-partout", "ℹ️ sans seuil"),
    ]

    out = [
        "# Évaluation du MVP",
        "",
        f"_Rapport généré le {today_fr(moment)} par `python -m src.evaluate`, "
        f"sur `data/books.db`._",
        "",
        "## Synthèse",
        "",
        table(["Critère", "Mesure", "Verdict"], synthese),
        "",
        "## 1. Catalogue",
        "",
        f"- Livres non masqués (indexés) : **{cat['indexed']}**",
        f"- Livres uniques (titre + premier auteur, sans accents ni casse) : **{cat['unique']}** "
        f"(critère ≥ {MIN_BOOKS})",
        f"- Avec au moins un thème : {cat['with_themes']} ({pct(cat['with_themes'], cat['indexed'])})",
        f"- Avec une ambiance : {cat['with_ambiance']} "
        f"({pct(cat['with_ambiance'], cat['indexed'])})",
        "",
        "### Répartition par catégorie principale",
        "",
        table(["Catégorie", "Livres", "Part"],
              [(c, n, pct(n, cat["indexed"])) for c, n in cat["categories"]]),
        "",
        "### Thèmes et ambiances",
        "",
        table(["Thème", "Livres"], [(THEME_LABELS.get(t, t), n) for t, n in cat["themes"]]),
        "",
        table(["Ambiance", "Livres"],
              [(AMBIANCE_LABELS.get(a, a), n) for a, n in cat["ambiances"]]),
        "",
        "## 2. Retrouver un livre",
        "",
        f"20 requêtes de `tests/fixtures/recherche_20.json`, écrites à partir de livres tirés "
        f"au hasard dans le catalogue (4 par type d'imperfection). Recherche sans filtre, "
        f"même fonction que `/recherche` (`engine.search_books` : apostrophes typographiques "
        f"normalisées, résultats exacts puis, sous {engine.MIN_EXACT} exacts, résultats "
        f"approchés). **Score : {n_found}/20** (critère ≥ {MIN_FOUND}, objectif "
        f"≥ {TARGET_FOUND}).",
        "",
        table(["Type", "Requête", "Livre visé", "Rang", "Résultats", "Top 5"],
              [(r["type"], f"`{r['requete']}`", r["titre"], r["rank"] or "absent", r["total"],
                "✅" if r["found"] else "❌") for r in found]),
        "",
        "Par type : " + ", ".join(
            f"{t} {sum(r['found'] for r in found if r['type'] == t)}/"
            f"{sum(r['type'] == t for r in found)}" for t in dict.fromkeys(r["type"] for r in found))
        + ".",
        "",
        "## 3. Recommandations",
        "",
        f"- `similar_books` sur {similar['tested']} livres tirés au hasard (graine {SEED}) : "
        f"5 résultats distincts, sans le livre source, chacun expliqué par « {PREFIX} … ». "
        f"**Échecs : {len(similar['failures'])}.**",
        f"- « Choisis pour toi » (`recommend` avec filtres du compte, hors bibliothèque) pour "
        f"les {n_recos} profils de démo : 5 résultats distincts expliqués. "
        f"**Échecs : {len(failures)}.**",
    ]
    for title, problem in similar["failures"]:
        out.append(f"  - livre « {title} » : {problem}")
    for name, problem in failures:
        out.append(f"  - profil {name} : {problem}")
    out += [
        "",
        "## 4. Performance",
        "",
        f"Client de test Flask sur `data/books.db`, connecté avec un profil de démo ; "
        f"{CALLS} appels par page après un appel de chauffe (chargement de l'index). "
        f"Les requêtes de recherche reprennent celles de la section 2, les fiches sont tirées "
        f"au hasard. Critère < {MAX_MS / 1000:.0f} s, objectif du cahier des charges "
        f"< {TARGET_MS / 1000:.0f} s.",
        "",
        table(["Page", "Médiane", "p95", "Erreurs", "Verdict"],
              [(page, f"{med:.0f} ms", f"{p:.0f} ms", err,
                "✅ < 1 s" if p < TARGET_MS and not err else
                "⚠️ < 3 s" if p < MAX_MS and not err else "❌")
               for page, (med, p, err) in perf.items()]),
        "",
        "## 5. Cohérence humaine",
        "",
        f"Grille dans `docs/evaluation_humaine.md` : {len(human)} profils de démo (le premier "
        f"de chaque famille, plus le deuxième des {HUMAN_EXTRA} familles les plus peuplées), "
        f"leurs réponses clés et leurs 5 recommandations « Choisis pour toi ». "
        f"À remplir par les membres du groupe ; critère : au moins {MIN_COHERENT}/5 jugées "
        f"cohérentes par profil.",
        "",
        table(["Profil", "Libellé", "Famille"],
              [(u["username"], u["profile_label"], u["profile_family"]) for u in human]),
        "",
        "## 6. Diversité",
        "",
        f"`profile.recommend` garde au plus {MAX_PER_CATEGORY} livres de même catégorie "
        f"principale parmi les {N} recommandations quand le vivier le permet "
        f"(`profile.diversify`, sinon complété sans contrainte). Mesure sur les {n_recos} "
        f"profils de démo, sans puis avec cette contrainte :",
        "",
        table(["Indicateur", "Avant", "Après"], [
            ("Catégories distinctes (moyenne)", f"{before['mean'] * 100:.0f} %",
             f"**{div['mean'] * 100:.0f} %**"),
            ("Catégories distinctes (minimum)",
             f"{before['min'] * 100:.0f} % ({round(before['min'] * N)}/5)",
             f"{div['min'] * 100:.0f} % ({round(div['min'] * N)}/5)"),
            (f"Profils avec plus de {MAX_PER_CATEGORY} livres d'une même catégorie",
             before["crowded"], div["crowded"]),
            ("Livres distincts recommandés", f"{before['distinct']} / {n_recos * N}",
             f"{div['distinct']} / {n_recos * N}"),
            (f"Livres « passe-partout » (plus de {WIDESPREAD} profils)",
             len(before["widespread"]), len(div["widespread"])),
        ]),
        "",
        "Livres les plus recommandés (après) :",
        "",
        table(["Livre", "Profils"], div["top"]),
    ]
    return "\n".join(out) + "\n"


def main(argv):
    if argv not in ([], ["--refaire-humaine"]):
        print("Usage : python -m src.evaluate [--refaire-humaine]")
        return 1
    moment = datetime.now()
    index = engine.get_index()
    queries = json.loads(QUERIES.read_text(encoding="utf-8"))
    users = demo_users()

    cat = catalogue(index)
    found = search(index, queries)
    similar = similar_check(index)
    recos = {u["username"]: pour_toi(u) for u in users}
    failures = [(name, ", ".join(p)) for name, results in recos.items() if (p := check(results))]
    perf = performance(users[0]["id"], queries, index)
    human = human_profiles(users)
    div = diversity(recos)
    before = diversity({u["username"]: pour_toi(u, max_per_category=None) for u in users})

    REPORT.write_text(report(moment, cat, found, similar, recos, failures, perf, human, div,
                             before), encoding="utf-8")
    print(f"Rapport : {REPORT.relative_to(ROOT)}")
    if HUMAN.exists() and not argv:
        print(f"Grille conservée : {HUMAN.relative_to(ROOT)} (--refaire-humaine pour la "
              "régénérer)")
    else:
        HUMAN.write_text(human_grid([(u, recos[u["username"]]) for u in human], moment),
                         encoding="utf-8")
        print(f"Grille : {HUMAN.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
