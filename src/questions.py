"""Questionnaire lecteur : 10 questions, leurs options et leur poids dans le barème.

Chaque réponse est une liste de codes (type "multi") ou un code (type "single").
Le code "neutre" est toujours accepté : il retire la question du calcul, sans malus.
"""

NEUTRAL = "neutre"
NEUTRAL_OPTION = {"code": NEUTRAL, "label": "Je ne sais pas / je ne souhaite pas me prononcer"}

# Les 12 catégories du catalogue (codes = valeurs de books.main_category) et leur libellé à l'écran.
CATEGORY_LABELS = {
    "littérature générale": "Littérature",
    "thriller": "Thriller",
    "policier": "Polar",
    "science-fiction": "Science-fiction",
    "dystopie": "Dystopie",
    "fantastique": "Fantasy & fantastique",
    "horreur": "Horreur",
    "roman historique": "Roman historique",
    "romance": "Romance",
    "aventure": "Aventure",
    "biographie": "Biographies & récits",
    "essai": "Essais & idées",
}

THEME_LABELS = {
    "famille": "famille", "amour": "amour", "amitie": "amitié", "guerre": "guerre",
    "crime": "crime", "voyage": "voyage", "societe": "société", "science": "science",
    "nature": "nature", "memoire": "mémoire", "deuil": "deuil", "secret": "secret",
    "initiation": "initiation", "art": "art", "survie": "survie",
}

AMBIANCE_LABELS = {
    "sombre": "sombre", "tendue": "tendue", "legere": "légère", "intimiste": "intimiste",
    "epique": "épique", "poetique": "poétique",
}


def options(pairs):
    """[(code, label), ...] -> options de question, option neutre ajoutée à la fin."""
    return [{"code": code, "label": label} for code, label in pairs] + [NEUTRAL_OPTION]


# Groupes proposés à l'écran (q1, q8) : code -> (libellé, catégories du catalogue).
GROUPS = {
    "litterature": ("Littérature générale", ["littérature générale"]),
    "thriller_polar": ("Thriller & polar", ["thriller", "policier"]),
    "science_fiction": ("Science-fiction", ["science-fiction", "dystopie"]),
    "fantasy": ("Fantasy & fantastique", ["fantastique", "horreur"]),
    "histoire_aventure": ("Histoire & aventure", ["roman historique", "aventure"]),
    "romance": ("Romance", ["romance"]),
    "biographies": ("Biographies & récits", ["biographie"]),
    "essais": ("Essais & idées", ["essai"]),
}

GROUP_OPTIONS = [(code, label) for code, (label, _) in GROUPS.items()]

QUESTIONS = [
    {
        "id": "q1", "type": "multi", "weight": 24,
        "text": "Qu'est-ce que tu aimes lire, spontanément ?",
        "help": "Choisis autant de genres que tu veux.",
        "options": options(GROUP_OPTIONS + [("autre", "Autre chose (précise si tu veux)")]),
    },
    {
        "id": "q2", "type": "multi", "weight": 22,
        "text": "Quels sujets te parlent le plus ?",
        "help": "Les thèmes vers lesquels tu reviens souvent.",
        "options": options([
            ("famille", "Famille"), ("secret", "Secrets"), ("survie", "Survie"),
            ("societe", "Société et politique"), ("amour", "Amour"), ("crime", "Enquête"),
            ("science", "Science et technologie"), ("memoire", "Destins historiques"),
        ]),
    },
    {
        "id": "q3", "type": "multi", "weight": 12,
        "text": "Quelle ambiance te fait du bien ?",
        "help": "L'atmosphère que tu recherches dans un livre.",
        "options": options([
            ("sombre", "Sombre"), ("tendue", "Haletante"),
            ("legere", "Drôle et réconfortante"), ("intimiste", "Psychologique et intime"),
            ("epique", "Épique et dépaysante"), ("poetique", "Contemplative et poétique"),
            ("varie", "Je varie"),
        ]),
    },
    {
        "id": "q4", "type": "multi", "weight": 12,  # posée et stockée, non calculée (MVP)
        "text": "Comment aimes-tu qu'une histoire soit racontée ?",
        "help": "Le rythme et la forme qui te conviennent.",
        "options": options([
            ("fresque", "Fresque"), ("huis_clos", "Huis clos"),
            ("rapide", "Intrigue rapide"), ("premiere_personne", "Première personne"),
            ("choral", "Récit choral"), ("saga_familiale", "Saga familiale"),
            ("enquete", "Enquête"), ("sans_pref", "Sans préférence"),
        ]),
    },
    {
        "id": "q5", "type": "single", "weight": 8,
        "text": "Tu préfères des livres plutôt…",
        "help": "La longueur qui te donne envie d'ouvrir le livre.",
        "options": options([
            ("court", "Courts (moins de 250 pages)"), ("moyen", "Moyens (250 à 450 pages)"),
            ("long", "Longs (plus de 450 pages)"), ("toutes", "Toutes les longueurs"),
        ]),
    },
    {
        "id": "q6", "type": "single", "weight": 6,
        "text": "Côté époque de publication ?",
        "help": "Plutôt nouveautés ou grands classiques ?",
        "options": options([
            ("nouveautes", "Les nouveautés (3 dernières années)"),
            ("recents", "Les livres récents (10 dernières années)"),
            ("classiques", "Les classiques"), ("toutes", "Toutes les périodes"),
        ]),
    },
    {
        "id": "q7", "type": "multi", "weight": 0,  # filtre sans effet : catalogue 100 % français
        "text": "Dans quelle langue lis-tu ?",
        "help": "Pour l'instant, le catalogue est en français.",
        "options": options([
            ("fr", "Français"), ("en", "Anglais"), ("es", "Espagnol"), ("ar", "Arabe"),
            ("zh", "Chinois mandarin"), ("hi", "Hindi"), ("toutes", "Toutes"),
        ]),
    },
    {
        "id": "q8", "type": "multi", "weight": 0,  # exclusion
        "text": "Y a-t-il des genres que tu préfères éviter ?",
        "help": "On ne te les proposera pas.",
        "options": options(GROUP_OPTIONS + [("aucun", "Aucune")]),
    },
    {
        "id": "q9", "type": "single", "weight": 8,  # bonus R
        "text": "Qu'est-ce qui compte le plus pour toi dans une recommandation ?",
        "help": "On en tiendra compte en bonus.",
        "options": options([
            ("themes", "Qu'elle parle de mes sujets préférés"),
            ("nouveau", "Qu'elle me fasse découvrir du nouveau"),
            ("profil", "Qu'elle plaise aux lecteurs comme moi"),
            ("temps", "Qu'elle colle au temps que j'ai pour lire"),
            ("varier", "Qu'elle me fasse varier les plaisirs"),
        ]),
    },
    {
        "id": "q10", "type": "single", "weight": 8,  # bonus D
        "text": "Tu as envie d'être surpris·e ?",
        "help": "Rester en terrain connu ou sortir de ta zone de confort.",
        "options": options([
            ("proche", "Reste proche de mes goûts"), ("mixte", "Un peu des deux"),
            ("surprise", "Surprends-moi !"), ("sans_pref", "Pas de préférence"),
        ]),
    },
]

QUESTIONS_BY_ID = {q["id"]: q for q in QUESTIONS}
