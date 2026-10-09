"""Attribution de thèmes et d'une ambiance aux livres, par lexiques de mots-clés.

Chaque mot-clé est comparé à la description normalisée (minuscules, sans
accents ni ponctuation) :
- par défaut, en préfixe de début de mot : "enquet" couvre enquête, enquêteur ;
- suffixé de "$", en mot entier (pluriel s/x accepté) : "reve$" couvre rêve,
  rêves, mais pas revenir.

Un thème (ou une ambiance) compte ses mots-clés distincts trouvés et leur nombre
total d'occurrences. À une même position, seul le mot-clé le plus long d'une
catégorie compte ("amitie" et non "ami" + "amitie").

Usage : python -m src.tagging
"""

import json
import random
import re
import unicodedata
from collections import Counter

from src.db import DB_PATH, get_connection, init_db

MAX_DOC_FREQ = 0.30   # mot-clé écarté s'il apparaît dans plus de 30 % des descriptions
MIN_DISTINCT = 2      # mots-clés distincts requis pour attribuer un thème / une ambiance
                      # (ou 1 seul mot-clé STRONG pour une ambiance)
MAX_THEMES = 4

THEMES = {
    "famille": [
        "famille", "famili", "parent", "mere", "pere", "fils", "fille", "frere", "soeur",
        "enfant", "heritage", "generation", "ancetre", "aieul", "cousin", "oncle", "tante",
        "maternel", "paternel", "filiation", "orphelin", "neveu", "niece", "adopt",
    ],
    "amour": [
        "amour", "amoureu", "passion$", "passionnel", "couple", "mariage", "epouse", "epoux",
        "desir", "seduct", "sentiment", "amant", "maitresse", "fiance", "fiancailles",
        "idylle", "romanti", "baiser", "liaison", "coup de foudre", "jalou", "adultere",
        "infidel", "attirance",
    ],
    "amitie": [
        "ami", "amitie", "complic", "camarade", "bande de", "copain", "copine", "compagnon",
        "inseparable", "fraternit", "solidarit", "entraide", "confident", "loyaut", "fidel",
        "pote", "colocataire", "voisin", "retrouvailles", "allie", "soutien",
    ],
    "guerre": [
        "guerre", "soldat", "combat", "bataille", "armee", "arme$", "resistan", "occupation",
        "nazi", "conflit", "militaire", "front$", "tranchee", "poilu", "regiment", "officier",
        "bombard", "invasion", "ennemi", "guerrier", "deport", "holocauste", "shoah",
        "collabor", "mobilis",
    ],
    "crime": [
        "meurtr", "crime", "crimin", "enquet", "inspecteur", "commissaire", "polic", "tueur",
        "assassin", "cadavre", "victime", "suspect", "detective", "disparition", "homicide",
        "flic", "gendarme", "coupable", "alibi", "autopsie", "legiste", "enlevement",
        "kidnapp", "otage", "mafia",
    ],
    "voyage": [
        "voyage", "expedition", "explor", "traversee", "periple", "ile$", "desert", "ocean",
        "navire", "decouverte", "mer$", "bateau", "marin", "continent", "jungle", "exil",
        "frontiere", "nomade", "escale", "itineraire", "contree", "afrique", "amerique",
        "asie", "pays lointain",
    ],
    "societe": [
        "societe", "social", "politique", "pouvoir", "revolution", "injustice", "inegalit",
        "dictature", "regime", "totalitaire", "surveillance", "liberte", "pauvret", "misere",
        "ouvrier", "greve", "racis", "discrimin", "gouvernement", "citoyen", "democrat",
        "propagande", "rebel", "censure", "capitalis",
    ],
    "science": [
        "science", "scientifi", "technolog", "robot", "intelligence artificielle", "machine",
        "laboratoire", "genetique", "planete", "vaisseau", "futur", "chercheur", "spatial",
        "galax", "extraterrestre", "alien$", "androide", "clone", "virus", "informatique",
        "numerique", "ordinateur", "cyber", "mutant", "astronaute",
    ],
    "nature": [
        "nature", "foret", "montagne", "animal", "animaux", "loup", "chien", "cheval$",
        "chevaux", "riviere", "fleuve", "lac$", "sauvage", "climat", "arbre", "jardin",
        "oiseau", "ours$", "paysage", "neige", "vallee", "ecolog", "environnement", "faune",
        "chat$",
    ],
    "memoire": [
        "memoire", "passe$", "souvenir", "siecle", "epoque", "archive", "temoignage",
        "guerre mondiale", "empire", "moyen age", "medieval", "roi$", "reine$", "dynastie",
        "monarchie", "autrefois", "jadis", "chronique", "historique", "oubli", "racine",
        "antiquite", "renaissance", "napoleon", "ancien",
    ],
    "deuil": [
        "deuil", "mort", "perte", "disparu", "absence", "chagrin", "veuf", "veuve",
        "survivant", "douleur", "deces", "funer", "enterrement", "tombe$", "tombeau",
        "cimetiere", "defunt", "suicid", "maladie", "cancer", "agonie", "adieu", "larme",
        "perdu", "souffrance",
    ],
    "secret": [
        "secret", "myster", "enigm", "verite", "mensonge", "menteur", "cache", "revel",
        "complot", "conspir", "etrange", "dissimul", "trahi", "double vie", "soupcon",
        "manipul", "inavou", "tabou", "non dit", "occult", "clandestin", "code$",
    ],
    "initiation": [
        "adolescen", "grandir", "grandit", "apprentissage", "apprenti", "devenir", "destin$",
        "destinee", "quete", "identite", "jeunesse", "initiat", "enfance", "lycee",
        "college$", "ecole", "etudiant", "emancip", "rite de passage", "maturit",
        "age adulte", "eveil", "vocation", "metamorphos",
    ],
    "art": [
        "peintre", "peinture", "musique", "musicien", "ecrivain", "theatre", "cinema",
        "creation", "artiste", "art$", "tableau", "poete", "poesie", "sculpt", "danse",
        "chanteu", "chanson", "opera", "piano", "violon", "photograph", "acteur", "actrice",
        "musee", "compositeur",
    ],
    "survie": [
        "survie", "surviv", "apocalyp", "catastrophe", "cataclysm", "fin du monde", "isole",
        "naufrag", "famine", "penurie", "epidemie", "pandemie", "abri$", "refuge", "hostile",
        "peril", "rescape", "tenir bon", "desastre", "sauvetage", "bunker", "radiation",
        "zombie",
    ],
}

AMBIANCES = {
    "sombre": [
        "sombre", "noir", "violen", "cruaute", "cruel", "horreur", "horrible", "cauchemar",
        "terreur", "terrifi", "angoiss", "oppress", "glac", "inquiet", "tenebr", "macabre",
        "sinistre", "effroi", "effray", "morbide", "sanglant", "desespoir", "obscur",
        "malsain", "funeste",
    ],
    "tendue": [
        "haletant", "suspense", "tension", "traque", "menace", "danger", "urgence",
        "compte a rebours", "rythme", "frisson", "course contre la montre", "fuite",
        "poursui", "piege", "adrenaline", "palpitant", "implacable", "thriller",
        "rebondissement", "intense", "chasse a l homme", "survie", "haleine", "trepidant",
        "addictif",
    ],
    "legere": [
        "drole", "humour", "comedie$", "leger", "rire", "sourire", "tendre", "joyeu",
        "feel good", "petillant", "savoureu", "cocasse", "loufoque", "burlesque", "delicieu",
        "irresistib", "fantaisi", "espiegle", "malicieu", "gaiete", "optimis",
        "bonne humeur", "decale", "farfelu", "rocambolesque",
    ],
    "intimiste": [
        "melancol", "intim", "silence", "solit", "nostalgi", "delicat", "boulevers", "emouv",
        "emotion", "pudeur", "pudique", "sensib", "introspect", "confidence", "fragil",
        "poignant", "subtil", "vulnerab", "touchant", "lumineu", "douceur", "huis clos",
        "portrait", "retenue",
    ],
    "epique": [
        "epique", "epopee", "royaume", "empire", "legend", "heros", "heroique", "conqu",
        "fresque", "grandiose", "saga", "chevalier", "dragon", "prophet", "trone", "souffle",
        "odyssee", "titan", "monumental", "bataille", "guerrier", "dieux", "ampleur",
        "seigneur",
    ],
    "poetique": [
        "poetique", "poesie", "onirique", "reve$", "reveu", "conte$", "merveill", "magie",
        "magique", "magicien", "lyrique", "envout", "fable", "imaginaire", "fee$",
        "feerique", "enchant", "sortilege", "sorci", "songe", "chimere", "surreal",
        "allegor", "myth",
    ],
}


# Mots-clés assez univoques pour attribuer une ambiance à eux seuls.
# Ils sont ajoutés au lexique de l'ambiance (voir ambiance_lexicon).
STRONG = {
    "sombre": ["glacant", "cauchemar", "terreur", "macabre", "terrifiant", "morbide",
               "tenebreu", "sanglant"],
    "tendue": ["haletant", "suspense", "compte a rebours", "palpitant", "trepidant",
               "course contre la montre", "adrenaline", "chasse a l homme"],
    "legere": ["drole", "humour", "comedie$", "loufoque", "cocasse", "burlesque", "feel good",
               "rocambolesque"],
    "intimiste": ["melancol", "intimiste", "bouleversant", "poignant", "introspect", "pudique"],
    "epique": ["epopee", "epique", "fresque", "odyssee", "grandiose", "heroic fantasy"],
    "poetique": ["onirique", "poetique", "lyrique", "feerique", "fantasmagori", "surreal"],
}


def ambiance_lexicon(ambiances=None, strong=None):
    """Lexique des ambiances complété par les mots-clés STRONG (sans doublon)."""
    ambiances = AMBIANCES if ambiances is None else ambiances
    strong = STRONG if strong is None else strong
    return {
        name: keywords + [kw for kw in strong.get(name, []) if kw not in keywords]
        for name, keywords in ambiances.items()
    }


# --- Normalisation et correspondance ------------------------------------------

def normalize(text):
    """'Sœur, l'Enquête !' -> 'soeur l enquete' : minuscules, sans accents ni ponctuation."""
    text = (text or "").lower().replace("œ", "oe").replace("æ", "ae")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def keyword_pattern(keyword):
    """Regex d'un mot-clé : préfixe de début de mot, ou mot entier s'il finit par '$'."""
    if keyword.endswith("$"):
        return re.compile(r"\b" + re.escape(normalize(keyword[:-1])) + r"[sx]?\b")
    return re.compile(r"\b" + re.escape(normalize(keyword)))


def compile_lexicon(lexicon, excluded=()):
    """{nom: [mots-clés]} -> {nom: [(mot-clé, regex)]}, sans les mots-clés écartés."""
    return {
        name: [(kw, keyword_pattern(kw)) for kw in keywords if kw not in excluded]
        for name, keywords in lexicon.items()
    }


def count_hits(text, patterns):
    """Occurrences par mot-clé dans un texte normalisé : {mot-clé: nb}.

    À une même position, seul le mot-clé le plus long est retenu.
    """
    by_position = {}
    for kw, pattern in patterns:
        for match in pattern.finditer(text):
            current = by_position.get(match.start())
            if current is None or len(kw) > len(current):
                by_position[match.start()] = kw
    return Counter(by_position.values())


def scores(text, compiled, strong=None):
    """{nom: (nb mots-clés distincts, nb occurrences)} pour les catégories retenues :
    au moins MIN_DISTINCT mots-clés distincts, ou un mot-clé de strong[nom]."""
    strong = strong or {}
    result = {}
    for name, patterns in compiled.items():
        hits = count_hits(text, patterns)
        if len(hits) >= MIN_DISTINCT or any(kw in strong.get(name, ()) for kw in hits):
            result[name] = (len(hits), sum(hits.values()))
    return result


# --- Attribution ---------------------------------------------------------------

def assign_themes(text, compiled_themes):
    """Jusqu'à MAX_THEMES thèmes, classés par occurrences puis mots-clés distincts."""
    found = scores(text, compiled_themes)
    order = list(compiled_themes)
    ranked = sorted(found, key=lambda t: (-found[t][1], -found[t][0], order.index(t)))
    return ranked[:MAX_THEMES]


def assign_ambiance(text, compiled_ambiances, strong=STRONG):
    """L'ambiance la mieux représentée (occurrences, puis mots-clés distincts) parmi
    celles ayant 2 mots-clés distincts ou 1 mot-clé STRONG.

    None si aucune n'atteint le seuil ou en cas d'égalité parfaite : jamais devinée.
    """
    found = scores(text, compiled_ambiances, strong)
    if not found:
        return None
    ranked = sorted(found, key=lambda a: (found[a][1], found[a][0]), reverse=True)
    if len(ranked) > 1 and found[ranked[0]] == found[ranked[1]]:
        return None
    return ranked[0]


def tag(description, compiled_themes, compiled_ambiances):
    """Description brute -> (thèmes, ambiance)."""
    text = normalize(description)
    return assign_themes(text, compiled_themes), assign_ambiance(text, compiled_ambiances)


# --- Garde-fou : fréquence documentaire ---------------------------------------

def doc_frequencies(texts, lexicons):
    """{mot-clé: part des textes normalisés qui le contiennent}."""
    keywords = {kw for lexicon in lexicons for kws in lexicon.values() for kw in kws}
    if not texts:
        return {kw: 0.0 for kw in keywords}
    patterns = {kw: keyword_pattern(kw) for kw in keywords}
    return {kw: sum(1 for t in texts if p.search(t)) / len(texts) for kw, p in patterns.items()}


def too_frequent(texts, lexicons, max_freq=MAX_DOC_FREQ):
    """Mots-clés présents dans plus de max_freq des textes : {mot-clé: fréquence}."""
    freqs = doc_frequencies(texts, lexicons)
    return {kw: f for kw, f in sorted(freqs.items(), key=lambda x: -x[1]) if f > max_freq}


# --- Pipeline -----------------------------------------------------------------

def tag_books(books, themes=THEMES, ambiances=None, strong=STRONG):
    """books : [(id, description)]. Renvoie ({id: (thèmes, ambiance)}, mots-clés écartés)."""
    ambiances = ambiance_lexicon(ambiances, strong)
    texts = [normalize(desc) for _, desc in books]
    excluded = too_frequent(texts, [themes, ambiances])
    compiled_themes = compile_lexicon(themes, excluded)
    compiled_ambiances = compile_lexicon(ambiances, excluded)
    tags = {
        book_id: (assign_themes(text, compiled_themes),
                  assign_ambiance(text, compiled_ambiances, strong))
        for (book_id, _), text in zip(books, texts)
    }
    return tags, excluded


def run(db_path=DB_PATH):
    """Tague tous les livres de la table books et enregistre themes / ambiance (JSON)."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        books = [(r["id"], r["description"]) for r in conn.execute("SELECT id, description FROM books")]
        tags, excluded = tag_books(books)
        conn.executemany(
            "UPDATE books SET themes = ?, ambiance = ? WHERE id = ?",
            [(json.dumps(t, ensure_ascii=False), json.dumps(a), book_id)
             for book_id, (t, a) in tags.items()],
        )
    return {"tags": tags, "excluded": excluded}


def print_report(report, db_path=DB_PATH, sample_size=10):
    tags, excluded = report["tags"], report["excluded"]
    total = len(tags)
    print(f"Livres tagués          : {total}")
    print(f"Mots-clés écartés (> {MAX_DOC_FREQ:.0%} des descriptions) :")
    for kw, freq in excluded.items():
        print(f"  - {kw:<22} {freq:>6.1%}")
    if not excluded:
        print("  (aucun)")
    if not total:
        return

    with_theme = sum(1 for t, _ in tags.values() if t)
    print(f"Livres avec >= 1 thème : {with_theme / total:.1%}")
    print("Distribution des thèmes (livres) :")
    for theme, count in Counter(t for ts, _ in tags.values() for t in ts).most_common():
        print(f"  - {theme:<12} {count:>5}  ({count / total:.1%})")

    with_ambiance = sum(1 for _, a in tags.values() if a)
    print(f"Livres avec ambiance   : {with_ambiance / total:.1%}")
    print("Distribution des ambiances :")
    for ambiance, count in Counter(a for _, a in tags.values() if a).most_common():
        print(f"  - {ambiance:<12} {count:>5}  ({count / total:.1%})")

    print(f"Échantillon aléatoire ({sample_size}) :")
    ids = random.sample(list(tags), min(sample_size, total))
    with get_connection(db_path) as conn:
        for book_id in ids:
            row = conn.execute("SELECT title, main_category FROM books WHERE id = ?", (book_id,)).fetchone()
            themes, ambiance = tags[book_id]
            print(f"  - {row['title'][:50]:<50} [{row['main_category']}] "
                  f"thèmes={themes} ambiance={ambiance}")


def main():
    print_report(run())


if __name__ == "__main__":
    main()
