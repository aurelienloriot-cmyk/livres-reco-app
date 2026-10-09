# livres-reco

## Objectif
Application web Flask de recommandation de livres francophones.
Recommandations par TF-IDF + similarité cosinus sur un catalogue local SQLite (`data/books.db`).
Comptes utilisateurs simples, questionnaire obligatoire, profil lecteur et suivi de lecture.

## Catégories (12)
littérature générale, thriller, policier, science-fiction, dystopie, fantastique, horreur, roman historique, romance, aventure, biographie, essai

## Structure
- `src/` : collecte, nettoyage, base, moteur, profil.
- `app/` : application Flask (`__init__.py`, routes, `templates/` Jinja2, `static/`).

## Règles
- Python 3.11.
- Code simple et explicable.
- Interface : Flask + Jinja2 + CSS maison.
- Pas de framework JS : JS vanilla minimal uniquement.
- Pas de LLM.
- Pas de framework d'auth externe : sessions Flask signées, mots de passe hachés avec werkzeug.
- Pas de FastAPI.
- Pas d'embeddings.
- L'interface tutoie l'utilisateur.
- Réponses concises ; ne pas réécrire des fichiers non demandés.

## Design
Suivre les captures de `docs/maquettes/` et la charte `docs/charte/Logo.pdf` :
- Couleurs (variables CSS) : `--violet` #7B61FF, `--rose` #FF6F96, `--encre` #1E1B3A ; vert citron (`--lime`) pour les badges.
- Police Nunito partout : Medium (500) pour le texte, Black (900) pour les titres.
- Fond clair dégradé, cartes arrondies.
- Logo : `app/static/img/logo.png` (livre ouvert violet/rose avec un visage), favicon `app/static/img/favicon.png`.

## Conventions
- Toute route hors inscription, connexion et questionnaire est protégée par le décorateur `@profile_required`, qui redirige vers le questionnaire tant que le profil n'est pas calculé.
