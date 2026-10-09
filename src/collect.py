"""Collecte des livres depuis une source externe."""

import argparse
import json
import os
import re
import time
import unicodedata
from pathlib import Path

import requests
from dotenv import load_dotenv

API_URL = "https://www.googleapis.com/books/v1/volumes"
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

MAX_RESULTS = 40  # maximum autorisé par l'API
MAX_PAGES = 12
DELAY_SECONDS = 1.0  # délai minimal entre deux appels (pas de clé API)
MAX_ATTEMPTS = 3
TIMEOUT_SECONDS = 15

QUERIES = {
    "littérature générale": ["roman français contemporain", "prix Goncourt", "chronique familiale roman",
                             "roman intimiste", "premier roman"],
    "thriller": ["thriller roman", "suspense psychologique", "tueur en série"],
    "policier": ["roman policier", "enquête inspecteur", "polar meurtre"],
    "science-fiction": ["science-fiction roman", "space opera", "voyage dans le temps",
                        "roman anticipation", "intelligence artificielle roman",
                        "colonisation planète roman", "cyberpunk roman"],
    "dystopie": ["roman dystopie", "société totalitaire futur", "roman post-apocalyptique"],
    "fantastique": ["roman fantasy", "magie dragons", "royaume elfes sorcier"],
    "horreur": ["roman horreur", "épouvante surnaturel", "maison hantée"],
    "roman historique": ["roman historique", "saga historique", "roman Moyen Âge"],
    "romance": ["roman d'amour", "comédie romantique", "romance passion",
                "romance contemporaine", "amour impossible roman"],
    "aventure": ["roman d'aventure", "aventure exploration", "pirates trésor"],
    "biographie": ["biographie", "mémoires autobiographie", "récit de vie témoignage"],
    "essai": ["essai philosophie", "essai société", "essai sciences humaines",
              "essai féminisme", "essai écologie", "essai histoire des idées",
              "essai sur le travail", "pamphlet"],
}


class CollectError(Exception):
    """Levée quand une requête échoue après MAX_ATTEMPTS tentatives."""


class FatalApiError(CollectError):
    """Erreur qui touchera toutes les requêtes : inutile de continuer la collecte."""


# Fragment du message d'erreur de l'API -> explication affichée.
FATAL_ERRORS = {
    "per day": "quota journalier épuisé",
    "API key not valid": "clé API invalide",
}


_last_call = 0.0


def _wait_rate_limit():
    """Garantit au moins DELAY_SECONDS entre deux appels à l'API."""
    global _last_call
    elapsed = time.monotonic() - _last_call
    if elapsed < DELAY_SECONDS:
        time.sleep(DELAY_SECONDS - elapsed)
    _last_call = time.monotonic()


def slugify(text):
    """'subject:science fiction' -> 'subject-science-fiction'."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def raw_path(category, query):
    return RAW_DIR / f"{slugify(category)}__{slugify(query)}.json"


def _api_message(resp):
    """Message d'erreur renvoyé par l'API (sans l'URL, qui contient la clé)."""
    try:
        return resp.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return resp.reason


def fetch_page(session, query, start_index, api_key=None):
    """Appelle volumes.list ; retry avec backoff sur 429/5xx et erreurs réseau."""
    params = {
        "q": query,
        "langRestrict": "fr",
        "printType": "books",
        "maxResults": MAX_RESULTS,
        "startIndex": start_index,
    }
    if api_key:
        params["key"] = api_key
    for attempt in range(1, MAX_ATTEMPTS + 1):
        _wait_rate_limit()
        try:
            resp = session.get(API_URL, params=params, timeout=TIMEOUT_SECONDS)
            if not resp.ok:
                for fragment, reason in FATAL_ERRORS.items():
                    if fragment in resp.text:
                        raise FatalApiError(f"{reason} (HTTP {resp.status_code})")
            if resp.ok:
                return resp.json()
            error = f"HTTP {resp.status_code} : {_api_message(resp)}"
            if resp.status_code != 429 and resp.status_code < 500:
                raise CollectError(error)  # autre 4xx : inutile de réessayer
        except requests.ConnectionError as exc:
            # Pas de str(exc) : il contient l'URL, donc la clé API.
            error = f"réseau : {type(exc).__name__}"
        except requests.Timeout:
            error = "timeout"
        if attempt < MAX_ATTEMPTS:
            wait = 2 ** attempt  # 2 s, 4 s
            print(f"    échec ({error}), nouvel essai dans {wait} s")
            time.sleep(wait)
    raise CollectError(f"{query!r} startIndex={start_index} : {error}")


def parse_items(response, category):
    """Extrait les volumeInfo bruts d'une réponse et y ajoute la catégorie cible.

    volumeInfo ne contient pas l'identifiant Google : on le recopie dans
    "_google_id" pour pouvoir dédoublonner plus tard.
    """
    items = []
    for item in response.get("items", []):
        info = dict(item.get("volumeInfo", {}))
        info["_google_id"] = item.get("id")
        info["_target_category"] = category
        items.append(info)
    return items


def collect_query(session, category, query, max_pages=MAX_PAGES, api_key=None):
    """Parcourt jusqu'à max_pages pages pour une requête et renvoie les items."""
    # L'API renvoie souvent moins que maxResults (20 au lieu de 40) et totalItems
    # varie d'une page à l'autre : on avance du nombre d'items réellement reçus
    # et on s'arrête sur une page vide.
    items = []
    start_index = 0
    for _ in range(max_pages):
        response = fetch_page(session, query, start_index, api_key)
        page_items = parse_items(response, category)
        if not page_items:
            break
        items.extend(page_items)
        start_index += len(page_items)
    return items


def save_items(path, items):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)  # écriture atomique : pas de fichier partiel en cas d'arrêt


def run(categories, max_pages=MAX_PAGES, dry_run=False):
    """Collecte toutes les requêtes des catégories demandées. Renvoie le total d'items."""
    total = 0
    session = requests.Session()
    api_key = os.environ.get("GOOGLE_BOOKS_API_KEY") or None
    if not dry_run:
        print("Clé API : " + ("oui" if api_key else "non (quota anonyme partagé)"))
    for category in categories:
        for query in QUERIES[category]:
            path = raw_path(category, query)
            label = f"[{category}] {query!r}"
            if path.exists():
                print(f"{label} : déjà collecté ({path.name}), ignoré")
                continue
            if dry_run:
                print(f"{label} : {max_pages} page(s) max -> {path.name}")
                continue
            try:
                items = collect_query(session, category, query, max_pages, api_key)
            except FatalApiError as exc:
                print(f"{label} : {exc}, arrêt de la collecte")
                return total
            except (CollectError, requests.RequestException, ValueError) as exc:
                print(f"{label} : abandon ({exc})")
                continue
            if not items:
                print(f"{label} : 0 item, aucun fichier écrit")
                continue
            save_items(path, items)
            total += len(items)
            print(f"{label} : {len(items)} items")
    return total


def main(argv=None):
    parser = argparse.ArgumentParser(description="Collecte Google Books (JSON brut).")
    parser.add_argument("--categories", help="liste séparée par des virgules (défaut : toutes)")
    parser.add_argument("--max-pages", type=int, default=MAX_PAGES)
    parser.add_argument("--dry-run", action="store_true", help="affiche le plan sans appeler l'API")
    args = parser.parse_args(argv)
    load_dotenv()  # GOOGLE_BOOKS_API_KEY depuis .env (l'environnement reste prioritaire)

    categories = list(QUERIES)
    if args.categories:
        categories = [c.strip() for c in args.categories.split(",")]
        unknown = [c for c in categories if c not in QUERIES]
        if unknown:
            parser.error(f"catégories inconnues : {', '.join(unknown)}")

    total = run(categories, args.max_pages, args.dry_run)
    if not args.dry_run:
        print(f"Total : {total} items bruts")


if __name__ == "__main__":
    main()
