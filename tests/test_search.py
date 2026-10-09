"""Recherche et filtres communs."""

from werkzeug.datastructures import MultiDict

from app import filters
from conftest import login, make_user
from src import db

YEAR = 2026


def book(id_, cats, year=2020, pages=300, language="fr"):
    return {"id": id_, "main_category": cats[0], "categories": cats,
            "published_year": year, "page_count": pages, "language": language}


def engine_filters(**values):
    return filters.to_engine(dict(filters.DEFAULTS, **values), year=YEAR)


def titles(page):
    return page.get_data(as_text=True)


def test_recherche_insensible_aux_accents(app, client):
    login(client, make_user(app))
    for query in ("etoiles", "ÉTOILES", "Étoi"):
        assert "Étoiles lointaines" in titles(client.get(f"/recherche?q={query}"))
    page = titles(client.get("/recherche?q=helene durand"))  # par auteur
    assert "Étoiles lointaines" in page and "1 livre trouvé" in page
    assert "/livre/3?q=" in page


def test_apostrophes_typographiques_des_deux_cotes(app, client):
    login(client, make_user(app))
    for query in ("cœurs d'ete", "Cœurs d’été", "cœurs d´été"):
        page = titles(client.get(f"/recherche?q={query}"))
        assert "Cœurs d&#39;été" in page and "Résultat approché" not in page, query


def test_resultats_approches_marques(app, client):
    login(client, make_user(app))
    page = titles(client.get("/recherche?q=etoiles lointanes"))  # une lettre en moins
    assert "Étoiles lointaines" in page and "Résultat approché" in page
    page = titles(client.get("/recherche?q=julie peit"))  # auteur, une faute par mot
    assert "Cœurs d&#39;été" in page and "Résultat approché" in page


def test_approche_seulement_sous_cinq_exacts():
    from src import engine
    books = [{"id": i, "title": t, "authors": []} for i, t in enumerate(
        ["Le lac", "Un lac", "Lac bleu", "Lac noir", "Petit lac", "Le bac"], 1)]
    index = engine.Index(books, {}, None, None, {})
    assert engine.search_books(index, "lac") == (books[:5], [])
    exact, approx = engine.search_books(index, "le lac", None)
    assert [b["id"] for b in exact] == [1] and 6 in [b["id"] for b in approx]
    assert engine.one_edit("demin", "demain") and not engine.one_edit("vye", "vies")


def test_recherche_trop_courte_ou_vide(app, client):
    login(client, make_user(app))
    assert "au moins 2 caractères" in titles(client.get("/recherche?q=e"))
    assert "Aucun livre trouvé" in titles(client.get("/recherche?q=zzzz"))
    assert "Tape un titre" in titles(client.get("/recherche"))


def test_recherche_erreur(app, client, monkeypatch):
    login(client, make_user(app))

    def broken(*args, **kwargs):
        raise RuntimeError("catalogue illisible")
    monkeypatch.setattr("src.engine.get_index", broken)
    assert "indisponible" in titles(client.get("/recherche?q=lac"))


def test_exclusion_prioritaire():
    f = engine_filters(genres=["science_fiction"], exclusions=["histoire_aventure"])
    assert f.accepts(book(1, ["science-fiction"]))
    assert not f.accepts(book(2, ["science-fiction", "aventure"]))  # accepté ET exclu
    assert not f.accepts(book(3, ["romance"]))                       # genre non accepté


def test_livre_sans_pages_ecarte_par_le_plafond():
    assert engine_filters().accepts(book(1, ["thriller"], pages=None))
    assert not engine_filters(max_pages=400).accepts(book(1, ["thriller"], pages=None))
    assert engine_filters(max_pages=400).accepts(book(1, ["thriller"], pages=400))
    assert not engine_filters(max_pages=400).accepts(book(1, ["thriller"], pages=401))


def test_periodes():
    assert engine_filters(period="nouveautes").accepts(book(1, ["thriller"], year=2023))
    assert not engine_filters(period="nouveautes").accepts(book(1, ["thriller"], year=2022))
    assert not engine_filters(period="recents").accepts(book(1, ["thriller"], year=None))
    assert engine_filters(period="classiques").accepts(book(1, ["thriller"], year=2000))
    assert not engine_filters(period="classiques").accepts(book(1, ["thriller"], year=2001))


def test_filtres_dans_la_recherche(app, client):
    user = make_user(app)
    login(client, user)
    assert "Le Lac sans fond" in titles(client.get("/recherche?q=lac"))
    client.post("/filtres", data={"max_pages": "400", "next": "/recherche?q=lac"})
    page = titles(client.get("/recherche?q=lac"))
    assert "Le Mystère du lac" in page and "Le Lac sans fond" not in page
    assert "400 pages max." in page  # critère actif affiché

    client.post("/filtres", data=MultiDict([("genres", "thriller_polar"),
                                            ("exclusions", "thriller_polar")]))
    assert "Aucun livre trouvé" in titles(client.get("/recherche?q=lac"))


def test_langue_sans_resultat_signalee(app, client):
    login(client, make_user(app))
    client.post("/filtres", data={"languages": "en"})
    page = titles(client.get("/recherche?q=lac"))
    assert "Aucun livre trouvé" in page and "que des livres en français" in page


def test_filtres_preremplis_puis_reinitialises(app, client):
    user = make_user(app)  # q8 : fantasy ; q6 : récents
    login(client, user)
    page = titles(client.get("/accueil"))
    assert "Sans : Fantasy &amp; fantastique" in page and 'action="/recherche"' in page
    saved = db.get_filters(user, app.config["DB_PATH"])
    assert saved["exclusions"] == ["fantasy"] and saved["period"] == "recents"

    client.post("/filtres", data={"period": "toutes"})
    assert db.get_filters(user, app.config["DB_PATH"])["period"] == "toutes"
    response = client.post("/filtres/reinitialiser", data={"next": "/recherche?q=lac"})
    assert response.headers["Location"] == "/recherche?q=lac"
    assert db.get_filters(user, app.config["DB_PATH"])["period"] == "recents"


def test_redirection_externe_refusee(app, client):
    login(client, make_user(app))
    response = client.post("/filtres", data={"next": "//exemple.com"})
    assert response.headers["Location"] == "/accueil"


def test_clean_ignore_les_valeurs_inconnues():
    form = MultiDict([("languages", "xx"), ("genres", "romance"), ("genres", "pirate"),
                      ("period", "jurassique"), ("max_pages", "250")])
    assert filters.clean(form) == dict(filters.DEFAULTS, genres=["romance"])
