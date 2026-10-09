# Et maintenant, je lis quoi ?

Application web de recommandation de livres francophones, réalisée en Python (Flask) dans le cadre du projet MBA MIA 2026/2027.
Le lecteur crée un compte, répond à un questionnaire de 10 questions et obtient un profil lecteur ; l'accueil lui propose ensuite des livres choisis par un barème, des lectures de « lecteurs comme toi » et les livres populaires de la semaine.
Il suit ses lectures (pile à lire, en cours, terminés), les note, et ses notes font évoluer son profil. Aucun LLM ni embedding : TF-IDF, similarité cosinus et barème explicite sur un catalogue SQLite local.

## Captures

Maquettes d'origine (dans [docs/maquettes/](docs/maquettes/)) :

- [Questionnaire](<docs/maquettes/Capture d’écran 2026-10-07 à 10.49.22.jpg>)
- Profil : [1](docs/maquettes/Profil-1.jpeg), [2](docs/maquettes/Profil-2.jpeg), [3](docs/maquettes/Profil-3.jpeg), [4](docs/maquettes/Profil-4.jpeg)
- Accueil et parcours : [1](<docs/maquettes/WhatsApp Image 2026-10-07 at 10.50.13.jpeg>), [2](<docs/maquettes/WhatsApp Image 2026-10-07 at 10.50.14.jpeg>), [3](<docs/maquettes/WhatsApp Image 2026-10-07 at 10.52.21.jpeg>), [4](<docs/maquettes/WhatsApp Image 2026-10-07 at 10.52.21.2jpeg.jpeg>), [5](<docs/maquettes/WhatsApp Image 2026-10-07 at 10.52.21 3.jpeg>), [6](<docs/maquettes/WhatsApp Image 2026-10-07 at 10.52.21 4.jpeg>), [7](<docs/maquettes/WhatsApp Image 2026-10-07 at 10.54.30.jpeg>)

Architecture : [docs/architecture.md](docs/architecture.md). Évaluation : [docs/evaluation.md](docs/evaluation.md).

## Installation depuis zéro

Prérequis : Python 3.11, une clé API Google Books (Google Cloud Console > Books API > Identifiants).

```bash
git clone <url-du-depot> livres-reco && cd livres-reco

# 1. Environnement Python
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. Secrets : copier le modèle puis remplir les deux valeurs
cp .env.example .env
#   GOOGLE_BOOKS_API_KEY=<ta clé Google Books>
#   SECRET_KEY=<résultat de : python -c "import secrets; print(secrets.token_hex(32))">

# 3. Base SQLite vide (data/books.db)
.venv/bin/python -c "from src.db import init_db; init_db()"

# 4. Collecte Google Books → data/raw/*.json (~11 000 items bruts, quelques minutes)
.venv/bin/python -m src.collect

# 5. Nettoyage + thèmes et ambiances → table books (~1 300 livres)
.venv/bin/python -m src.clean
.venv/bin/python -m src.hide --apply      # remasque les livres listés dans src/hidden_books.txt

# 6. Comptes de démonstration (sections communautaires de l'accueil)
.venv/bin/python -m src.seed --reset

# 7. Lancement
.venv/bin/python run.py                   # puis http://127.0.0.1:5000
```

Google Books ne renvoie pas toujours les mêmes résultats d'un jour à l'autre : un catalogue recollecté peut différer légèrement du nôtre (1 311 livres).

## Commandes utiles

| Commande | Rôle |
|---|---|
| `.venv/bin/python -m pytest` | Lance les tests (214) |
| `.venv/bin/python -m src.evaluate` | Régénère [docs/evaluation.md](docs/evaluation.md) ; `--refaire-humaine` écrase aussi la grille humaine |
| `.venv/bin/python -m src.hide "titre partiel ou id"` | Masque un livre mal classé et l'ajoute à `src/hidden_books.txt` |
| `.venv/bin/python -m src.hide --list` | Liste les livres masqués |
| `.venv/bin/python -m src.hide --apply` | Remasque la liste après reconstruction de la base |
| `.venv/bin/python -m src.suspects` | Liste des livres qui ressemblent à des essais, à revoir avant masquage |
| `.venv/bin/python -m src.seed --historique <pseudo>` | Crée un historique de lecture cohérent pour un vrai compte (`--force` s'il a déjà des lectures) |
| `.venv/bin/python -m src.engine "titre"` | Affiche les livres proches d'un titre (TF-IDF) |
| `.venv/bin/python -m src.collect --dry-run` | Affiche le plan de collecte sans appeler l'API |

**Relance le serveur après un masquage** : une application déjà lancée garde l'index TF-IDF en mémoire et continue de proposer le livre masqué tant qu'elle n'a pas redémarré.

## Structure du dépôt

```
livres-reco/
├── run.py                 lancement local de Flask
├── requirements.txt       dépendances figées
├── .env.example           modèle des secrets (.env non versionné)
├── src/                   logique métier, testable sans Flask
│   ├── collect.py         collecte Google Books → data/raw/*.json
│   ├── clean.py           filtrage, dédoublonnage, chargement SQLite
│   ├── tagging.py         thèmes et ambiance par lexiques de mots-clés
│   ├── db.py              schéma et requêtes SQLite
│   ├── engine.py          TF-IDF + cosinus : livres proches, recherche, nouveauté
│   ├── questions.py       les 10 questions et leur poids
│   ├── profile.py         barème, profil lecteur, apprentissage par les notes
│   ├── home.py            sections de l'accueil
│   ├── stats.py           statistiques personnelles
│   ├── seed.py            comptes de démonstration
│   ├── hide.py            masquage des livres mal classés
│   ├── suspects.py        détection des livres suspects
│   └── evaluate.py        évaluation du MVP
├── app/                   application Flask
│   ├── __init__.py        create_app, blueprints
│   ├── auth.py  survey.py  main.py  books.py  library.py  filters.py
│   ├── templates/         pages Jinja2
│   └── static/            CSS maison, JS vanilla, logo
├── tests/                 tests pytest
├── docs/                  maquettes, architecture, évaluation
└── data/                  base et JSON bruts (non versionnés)
```

## Comptes de démonstration

**Données fictives** : ces 46 comptes sont créés par `src/seed.py` (marqués `is_demo` en base) pour peupler les sections communautaires. Ils ne correspondent à aucune personne réelle.

- Mot de passe commun : `demo1234` ; e-mail : `<pseudo>@exemple.fr`.

| Famille de profil | Pseudos |
|---|---|
| suspense | aline, karim, sophie, mehdi, lucie, yann, bastien, chloe, rachid, margaux, gaspard |
| psychologie | nour, clement, ines, marc, nina, julien, elise, samir, manon, victor, zoe |
| imaginaire | theo, jade, hugo, emma, lina, adam |
| histoire | pierre, salome, antoine, ophelie, baptiste, leila |
| réel et idées | fatou, louis, gilles, aicha, raphael, odile |
| éclectique | camille, mathis, rose, kevin, anais, paul |

## Limites connues

- **Catalogue issu de Google Books** : 1 311 livres, figé, dont 21 masqués (1 290 visibles) ; la qualité dépend des descriptions fournies par les éditeurs. Couvertures via Open Library (souvent en anglais), avec repli sur la miniature Google puis une carte colorée.
- **Non-fiction résiduelle** : quelques études et catalogues passent encore les filtres ; ils sont masqués au cas par cas avec `src.hide`.
- **Ambiance détectée sur environ 40 % des livres** (thèmes : 75 %) : la question 3 est ignorée pour les autres livres, sans malus.
- **Catalogue français uniquement** : la question 7 (langues) est posée mais sans effet ; la question 4 (format) est enregistrée mais non calculée.
- **Non réalisés** : bilan de lecture en image PNG, manifest PWA, suppression de compte.

## Licence

MIT.
