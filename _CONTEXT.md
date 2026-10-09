# _CONTEXT.md — « Et maintenant, je lis quoi ? »

Dernière mise à jour : 7 octobre 2026 (v5)

## Rôles
- Mathias : pilote, ne code pas. Valide les décisions, copie les prompts dans Claude Code (VSCode), rapporte les résultats.
- Claude (chat) : chef d'orchestre. Cadre, tranche, rédige les prompts, lit les rapports, corrige le cap.
- Claude Code (VSCode) : exécutant. Écrit et teste le code.

## Projet
Application Python (projet MBA) de recommandation de livres francophones. Un lecteur crée un compte, répond à un questionnaire obligatoire de 10 questions, obtient un profil, puis une page d'accueil à 3 sections. Il suit ses lectures, note les livres, et ses notes font évoluer son profil.

Documents de référence (fournis par Mathias) : périmètre initial, cahier des charges v1.0, **cahier des charges v2 (7 oct., issu d'une démo ChatGPT « version 7 »)**, barème détaillé du questionnaire, 3 maquettes d'interface, slides de cadrage du professeur (MIA Projet Python 2026/2027).

## Tri du cahier des charges v2 (validé par Mathias)
Refusé : FastAPI + PostgreSQL + front PWA séparé ; catalogue Open Library en direct (le barème exige des tags calculés hors ligne) ; hors-ligne / service worker.
Intégré : 8 groupes de genres à l'écran (12 catégories en données) ; thèmes du CDC (8, dont « survie » ajouté) ; 6 ambiances conservées avec libellés rapprochés ; 6 familles de profil (psychologie, suspense, imaginaire, histoire, réel et idées, éclectique) qui servent au groupe « lecteurs comme toi » ; note facultative et modifiable (préférences apprises recalculées depuis toutes les notes) ; sections communautaires masquées sous 5 lecteurs contributeurs ; lecture du moment, pile à lire (Monter/Descendre, pas de glisser-déposer), statuts à lire / en cours / terminé, plusieurs lectures en cours ; trois univers ; bouton renouveler ; recherche titre/auteur dans le catalogue local ; statistiques personnelles ; filtres communs persistés par compte ; Q8 limitée aux 8 groupes (pas de « violence graphique » / « young adult » : données absentes).
Reporté (fin de projet si temps) : bilan PNG 1080×1350, manifest PWA sans hors-ligne, suppression de compte.

## Cadre académique (projet noté)
- Groupe de 4 à 6, 1 manager responsable du temps, si possible 1 développeur. Approche itérative, jalons réalistes, un livrable à la fin.
- Tous les membres doivent partager leurs travaux et comprendre l'ensemble : le code et les choix doivent rester explicables à un non-développeur.
- Livrables attendus : (1) présentation avec, intitulés exacts pour la certification RNCP : « Définition fonctionnelle du projet de développement », « Cahier des charges », « Conception des solutions d'architecture technique » (avec schéma d'architecture), puis Démonstration et Retour d'expérience ; (2) dépôt du projet sur un site de dépôt au choix (→ GitHub) ; (3) slides déposées dans la Dropbox avec le nom de chaque participant.
- Conséquences : pousser le dépôt git sur GitHub avant la fin ; produire un schéma d'architecture propre ; tenir un journal des décisions (ce fichier) pour le retour d'expérience.

## Décisions prises
| Sujet | Décision |
|---|---|
| Périmètre | Parcours complet : comptes, questionnaire, profil, home 3 sections, suivi lecture, notes. Les exclusions du document initial sont caduques sur ces points. |
| Architecture | Monolithe Python : collecte Google Books → nettoyage → SQLite → moteur → Flask. Pas de FastAPI, pas d'embeddings, pas de LLM. |
| Interface | **Flask + Jinja2 + CSS maison** (Streamlit abandonné : incapable de reproduire les maquettes). JS vanilla minimal. Tutoiement obligatoire. |
| Auth | Pseudo + e-mail + mot de passe haché (werkzeug). Sessions Flask. Décorateur `@profile_required` sur toute route hors inscription/connexion/questionnaire. |
| Catalogue | Français uniquement, 12 catégories, description ≥ 200 car., pageCount 60-1500. Pas de fusion de catégories à l'écran (les 12 restent distinctes, libellés chaleureux). |
| Q2/Q3/Q4 | Thèmes (Q2) et ambiance (Q3) dérivés par lexiques de mots-clés sur la description. Q4 format : posée et stockée mais non calculée dans le MVP. |
| Dimensions neutres | Une dimension neutre au questionnaire reste hors de P même après apprentissage par les notes ; valeurs apprises conservées (« tendances observées »). |
| Départage | (S, nombre de dimensions calculées, avg_rating si ≥ 5 votes, id). Un seul livre par auteur dans une liste. |
| Catalogue figé | clean.py ne sera plus retouché. Résidus de non-fiction acceptés (ex. « Lire Patrick Modiano », « Crime & châtiment » musée d'Orsay). |
| Q6 classiques | Règle MVP : 100 % si publié il y a > 25 ans, 50 % sinon. |
| Q7 langues | Posée pour le cahier des charges, sans effet (catalogue 100 % français). À documenter. |
| Moteurs | Le barème (score S) classe « À lire ensuite ». TF-IDF + cosinus sert aux livres proches depuis une fiche et à l'indice de nouveauté N (Q10). |
| Sections 2 et 3 | « Lecteurs comme toi » = même profile_label ; « Populaires cette semaine » = readings démarrées sur 7 jours. Repli explicite si données insuffisantes + script de seed pour la démo. |
| Couvertures | **Open Library** par ISBN (`https://covers.openlibrary.org/b/isbn/{isbn}-M.jpg`, URL affichée, jamais téléchargée ; couvertures souvent en anglais, accepté). Repli : miniature Google, puis carte colorée façon maquette. Repli géré côté HTML (`onerror`), sans étape de collecte supplémentaire. |

## Barème (résumé)
- Q1 genres 24, Q2 thèmes 22, Q3 ambiance 12, Q4 format 12 (non calculé), Q5 longueur 8, Q6 période 6. Q7 langue = filtre, Q8 exclusions = filtre. Q9 bonus priorité ≤ 8, Q10 bonus découverte ≤ 8.
- P = moyenne pondérée des dimensions renseignées ET calculables. S = 0,84 × P + R + D.
- Réponse neutre = valide, retirée du dénominateur, jamais un malus. Donnée manquante = dimension ignorée.
- Confiance = poids renseignés ÷ 84 (« toutes les longueurs / périodes » exclues du dénominateur).
- Après lecture : note 4-5 → +0,05 sur genres/thèmes/ambiance du livre ; 1-2 → −0,05 ; plafond ±0,30. Exclusions manuelles priment.

## Questionnaire (codes) — src/questions.py
- Q1 genres : 8 groupes (GROUPS) dépliés en catégories : Littérature générale ; Thriller & polar (thriller, policier) ; Science-fiction (science-fiction, dystopie) ; Fantasy & fantastique (fantastique, horreur) ; Histoire & aventure (roman historique, aventure) ; Romance ; Biographies & récits ; Essais & idées. + « Autre » (texte, sans effet). Multi.
- Q2 thèmes proposés (8) : famille, secret, survie, societe, amour, crime (« Enquête »), science, memoire (« Destins historiques »). 6 autres codes existent en données (amitie, guerre, voyage, nature, deuil, initiation, art) mais ne sont pas proposés. Multi.
- Q3 ambiance (6 + varie) : sombre, tendue (« Haletante »), legere (« Drôle et réconfortante »), intimiste (« Psychologique et intime »), epique (« Épique et dépaysante »), poetique (« Contemplative et poétique »). Multi.
- Q4 format : fresque, huis clos, intrigue rapide, première personne, récit choral, saga familiale, enquête, sans préférence. Multi, stocké seulement.
- Q5 longueur : court (< 250), moyen (250-450), long (> 450), toutes. Unique.
- Q6 période : nouveautes (≤ 3 ans), recents (≤ 10), classiques (> 25 ans), toutes. Unique.
- Q7 langues : fr, en, es, ar, zh, hi, toutes. Multi, sans effet (catalogue français, signalé à l'écran).
- Q8 à éviter : les 8 groupes + aucune. Multi.
- Q9 priorité : themes, nouveau, profil, temps, varier. Unique.
- Q10 découverte : proche (0×N), mixte (0,5×N), surprise (1×N), sans_pref (0,5×N). Unique.
- Chaque question a l'option neutre « Je ne sais pas / je ne souhaite pas me prononcer ».

## Schéma SQLite (data/books.db)
- books : id, google_id, title, authors (JSON), description, categories_raw (JSON), main_category, categories (JSON, 12 cat. cibles), themes (JSON), ambiance (JSON), published_year, page_count, language, isbn, thumbnail, info_link, avg_rating, ratings_count
- users : id, username, email, password_hash, created_at, profile_label, profile_family, profile_confidence, profile_vector (JSON : genres, themes, ambiances, formats, length, period, languages, exclusions, priority, discovery, answered, initial, label, label_description, label_tags, family)
- survey_answers : user_id, question_id, answer, answered_at
- readings : id, user_id, book_id, start_date, end_date, rating, comment

## Structure du code
```
livres-reco/
  CLAUDE.md  requirements.txt  .env (clé Google, gitignoré)  .env.example
  data/raw/*.json (36+ fichiers, 12 Mo)   data/books.db
  docs/maquettes/{questionnaire,profil,accueil}.png
  src/collect.py  clean.py  tagging.py  stopwords_fr.py  db.py  engine.py  questions.py  profile.py
  app/__init__.py  auth.py (profile_required)  survey.py  main.py  templates/  static/css/style.css  static/js/survey.js
  run.py
  tests/ (conftest.py + test_*.py)
```
Environnement : macOS, Python 3.11 via `/opt/homebrew/bin/python3.11`, `.venv`. Commandes : `.venv/bin/python -m src.collect|clean|tagging|engine "titre"|profile --demo`, `.venv/bin/pytest`, `.venv/bin/python run.py` (http://127.0.0.1:5000).

## État d'avancement
- [x] 1. Init, CLAUDE.md, db.py
- [x] 2. collect.py — clé API, 49 requêtes, ~11 000 items bruts
- [x] 3. clean.py + tagging.py — catalogue figé à **1 311 livres** (romance 218, thriller 177, policier 161, SF 150, essai 99, dystopie 96, biographie 89, fantastique 83, litt. gén. 77, aventure 59, horreur 53, rom. historique 49). Filtres : langue, auteurs, description ≥ 200, pages 60-1500, année, titres, non-fiction (catégories Google + titres + vocabulaire d'étude + langue du contenu ≥ 15 % de mots vides), texte d'éditeur répété, doublons d'édition. Thèmes 75 %, ambiance ~40 %.
- [x] 4. engine.py — TF-IDF (11 000 termes), 0,8 cos + 0,2 Jaccard, explication « Recommandé pour… », novelty, cache pkl. ~4 ms par requête.
- [x] 5. profile.py + questions.py — barème implémenté (ex. A vérifié : P 76,1, confiance 54,8 %), libellés, familles, recompute_learned. --demo validé.
- [x] 6. Flask : inscription/connexion, questionnaire 10 pages avec reprise, gating, /profil-cree, accueil provisoire. 122 tests.
- [x] 6b. Réconciliation CDC v2 (groupes, thèmes, familles, notes recalculées).
- [x] 7a. Fiche livre (couverture Open Library → Google → carte colorée), actions Commencer/Terminer, recherche titre/auteur, filtres persistés par compte (app/filters.py, layout.html).
- [x] 7b. Accueil complet (src/home.py, app/main.py) : lecture du moment, Choisis pour toi + Renouveler (pénalité 100 pts en session) + Voir toute la sélection (lots de 24), Lecteurs comme toi, Populaires J-6..J, seuil 5 lecteurs → Sélection {famille}, /explorer 3 univers (NEIGHBORS pour compléter).
- [x] 8. Bibliothèque 3 onglets, pile Monter/Descendre, avis (cœurs, note facultative, commentaire ≤ 2000), /profil avec tendances observées, Refaire le questionnaire (brouillon users.draft_answers).
- [x] 9a. Seed : 46 comptes fictifs (is_demo, mdp demo1234, <pseudo>@exemple.fr), deux vagues à graines fixes 2026/2027 ; toutes les familles ≥ 6 contributeurs ; 36 actifs/semaine ; livres du moment par famille (MOMENT_PICKS). `python -m src.seed --reset`.
- [x] Masquage : books.hidden, src/hidden_books.txt, `python -m src.hide "<titre|id>"`, --apply, --list ; 19 livres masqués ; `python -m src.suspects` (trop large, 435 résultats).
- [x] 9b. Statistiques (src/stats.py, /statistiques) : 7 indicateurs, None jamais 0.
- [x] Test visuel par Mathias → corrections : masquage ("L'essai", Lovecraft id 430…), boutons et titres accueil, badges d'affinité.
- [x] 10. Évaluation (src/evaluate.py → docs/evaluation.md) : catalogue 1 290 non masqués ✅ ; recherche 20/20 (après apostrophes + approché mots ≥ 5 lettres) ✅ ; similar_books 30/30 et recommend 46/46 ✅ ; p95 2-20 ms ✅ ; diversité 36 % → 49 % (max 3 livres/catégorie) ; cohérence humaine : docs/evaluation_humaine.md (8 profils) à remplir par le groupe ⏳.
- [x] 11a. Charte : violet #7B61FF, rose #FF6F96, encre #1E1B3A, Nunito 500/900, logo extrait de docs/charte/logo.pdf (app/static/img/logo.png, favicon).
- [x] 11b. /profil fusionné avec les statistiques (/statistiques redirige) : profil dominant, anneau de confiance, compteurs, 3 raccourcis, stats (livre préféré, pages/semaine, livres du mois, note moyenne, pages, plus gros livre, genres en barres, thèmes/ambiances). Sans bloc « Partage ton bilan ».
- [x] Mobile 360 px : en-tête réduit, barre de navigation basse, filtres plein écran, aucun défilement horizontal.
- [x] Affinité : « S % d'affinité » sur toutes les cartes et fiches, couleur par seuils 80/60/40.
- [x] seed --historique <pseudo> [--force] : historique réaliste pour un compte réel (10 terminés / 2 en cours / 3 à lire), verrou transactionnel. Appliqué à toto.
- [ ] 12. README complet, docs/architecture.md (Mermaid), requirements figé — en cours
- [ ] GitHub : dépôt privé `livres-reco`, URL à donner au prof
- [ ] Grille d'évaluation humaine remplie par le groupe (critère ≥ 3/5 cohérentes par profil)
- [ ] Slides RNCP : Définition fonctionnelle, Cahier des charges, Conception des solutions d'architecture technique (schéma), Démonstration, Retour d'expérience ; dépôt Dropbox avec noms des participants
- Reporté : bilan PNG 1080×1350, manifest PWA, suppression de compte
- Tests : 214 au dernier comptage.

## Retour d'expérience (matière pour la soutenance)
- Google Books : max 20 résultats/page malgré maxResults=40 ; `subject:` seul renvoie 0 ; `langRestrict=fr` laisse passer ~30 % de non-français ; ne distingue pas fiction et études → 6 passes de nettoyage.
- TF-IDF sur descriptions courtes : voisins faibles quand la description est une dédicace (Balzac) ou sans thème (Vargas).
- Le barème « donnée manquante = dimension ignorée » avantage les livres peu renseignés → départage par nombre de dimensions calculées.
- Streamlit abandonné dès que les maquettes sont arrivées ; Flask + Jinja2 choisi.
- CDC v2 (démo ChatGPT) trié plutôt qu'appliqué : simplicité exigée par le cours.
- Recherche par sous-chaîne exacte : 15/20 seulement ; apostrophes typographiques et recherche approchée → 20/20.
- Barème strict → 5 livres de la même catégorie (1,8 catégorie sur 5) ; règle de diversité « max 3 par catégorie » → 49 %.
- Mise à jour du profil par incréments successifs dépendait de l'ordre des notes → recalcul depuis zéro à chaque note.
- Course entre deux lancements du seed → vérification dans la transaction (BEGIN IMMEDIATE).
- Catalogue : ne jamais relancer clean.py une fois des lectures créées (ids) ; masquage via src.hide.
- Méthode : un prompt = un module, /clear entre modules, Claude Code rapporte et propose, le chat tranche. ~30 prompts, 214 tests, une journée.

## Points ouverts
- Catalogue : ne plus relancer clean.py (ids référencés par les lectures) ; masquer via src.hide uniquement.
- recompute_learned : somme des écarts puis plafond ±0,30 une seule fois (indépendant de l'ordre des notes).
- Le serveur Flask garde l'index TF-IDF en mémoire : le relancer après un masquage.
- Comptes réels de Mathias : toto (éclectique, historique généré) ; un compte suspense serait plus démonstratif pour la soutenance (seed --historique applicable).
- Démo : la grille humaine est à faire remplir par les membres du groupe ; décision à prendre sur le bloc « Partage ton bilan » (PNG) après l'évaluation.

## Règles de travail
- Un prompt = un module. `/clear` au changement de module, pas pour une correction du module en cours.
- Commit git après chaque étape validée.
- Ne jamais coller la clé API dans un prompt ni dans le chat.
- Claude Code rapporte ; le chat tranche. Les propositions de Claude Code sont validées explicitement avant application.
- Réponses et prompts concis, pas de tokens inutiles.
