"""Mots vides français ignorés par l'index TF-IDF (src.engine).

Écrits avec leurs accents pour rester lisibles ; src.engine les normalise
(minuscules, sans accents) comme le texte indexé. Les mots d'une lettre (l', d',
à...) sont de toute façon ignorés par le découpage en mots.
"""

STOPWORDS_FR = [
    # Articles et déterminants
    "le", "la", "les", "un", "une", "des", "du", "de", "au", "aux",
    "ce", "cet", "cette", "ces", "mon", "ma", "mes", "ton", "ta", "tes",
    "son", "sa", "ses", "notre", "nos", "votre", "vos", "leur", "leurs",
    "quel", "quelle", "quels", "quelles", "tout", "toute", "tous", "toutes",
    "chaque", "autre", "autres", "même", "mêmes", "plusieurs", "certains",
    "certaines", "aucun", "aucune",
    # Pronoms
    "je", "tu", "il", "elle", "on", "nous", "vous", "ils", "elles", "me", "te",
    "se", "moi", "toi", "lui", "eux", "soi", "en", "qui", "que", "qu", "quoi",
    "dont", "où", "lequel", "laquelle", "lesquels", "celui", "celle", "ceux",
    "celles", "ceci", "cela", "ça",
    # Prépositions
    "dans", "par", "pour", "sur", "sous", "avec", "sans", "entre", "vers",
    "chez", "contre", "depuis", "pendant", "avant", "après", "selon", "parmi",
    "malgré", "envers", "hors", "dès", "jusque", "jusqu",
    # Conjonctions
    "et", "ou", "mais", "donc", "or", "ni", "car", "si", "comme", "quand",
    "lorsque", "lorsqu", "puisque", "alors", "ainsi", "aussi", "puis",
    # Adverbes courants
    "ne", "pas", "plus", "moins", "très", "trop", "bien", "peu", "encore",
    "déjà", "toujours", "jamais", "souvent", "ici", "là", "non", "oui", "tant",
    "tellement", "surtout", "enfin",
    # Auxiliaires et verbes très courants
    "être", "suis", "es", "est", "sommes", "êtes", "sont", "était", "étaient",
    "été", "sera", "seront", "serait", "fut", "furent", "soit", "soient",
    "avoir", "ai", "as", "avons", "avez", "ont", "avait", "avaient", "eu",
    "aura", "auront", "aurait", "faire", "fait", "font", "faisait",
    "pouvoir", "peut", "peuvent", "pourrait", "devoir", "doit", "doivent",
    # Adverbes fréquents
    "parfois", "désormais", "vraiment", "presque", "assez", "beaucoup",
    "longtemps", "ensuite", "pourtant", "cependant", "quelque", "quelques",
    "seulement", "afin", "lors", "comment", "pourquoi",
    # Nombres en lettres
    "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf", "dix",
    "onze", "douze", "treize", "quatorze", "quinze", "seize", "vingt", "cent",
    "cents", "mille",
    # Formes verbales fréquentes
    "va", "vont", "allait", "dit", "dire", "sait", "veut", "faut", "devient",
    "semble", "vient", "pouvait", "devait",
    # Fragments de contraction (n'a, aujourd'hui...)
    "na", "aujourd", "hui",
    # Vocabulaire du livre et de quatrième de couverture
    "roman", "romans", "livre", "livres", "histoire", "histoires",
    "auteur", "auteurs", "tome", "tomes", "prix", "best", "seller", "succès",
    "lecteur", "lecteurs", "page", "pages", "œuvre", "oeuvre", "publié",
    "publiée", "édition", "éditions", "ouvrage", "volume", "chapitre",
    "dernières", "derniers", "années", "grands", "nouveaux", "nouvelle",
]
