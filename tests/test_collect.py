from src.collect import parse_items, raw_path, slugify

FAKE_RESPONSE = {
    "kind": "books#volumes",
    "totalItems": 2,
    "items": [
        {
            "id": "abc123",
            "volumeInfo": {
                "title": "Le Crime de l'Orient-Express",
                "authors": ["Agatha Christie"],
                "language": "fr",
                "categories": ["Fiction"],
            },
        },
        {"id": "def456", "volumeInfo": {"title": "Sans auteur"}},
    ],
}


def test_parse_items_keeps_raw_fields_and_adds_metadata():
    items = parse_items(FAKE_RESPONSE, "policier")
    assert len(items) == 2
    assert items[0]["title"] == "Le Crime de l'Orient-Express"
    assert items[0]["authors"] == ["Agatha Christie"]
    assert items[0]["_target_category"] == "policier"
    assert items[0]["_google_id"] == "abc123"
    assert "authors" not in items[1]  # aucun nettoyage ni complétion


def test_parse_items_without_results():
    assert parse_items({"totalItems": 0}, "policier") == []


def test_parse_items_does_not_mutate_response():
    parse_items(FAKE_RESPONSE, "policier")
    assert "_target_category" not in FAKE_RESPONSE["items"][0]["volumeInfo"]


def test_slug_and_path():
    assert slugify("subject:science fiction") == "subject-science-fiction"
    assert raw_path("littérature générale", "prix Goncourt").name == (
        "litterature-generale__prix-goncourt.json"
    )
