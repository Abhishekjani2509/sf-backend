BASE = "/api/v1/contacts"


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "sqlite"


def test_create_contact(client, payload):
    response = client.post(BASE, json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["id"] > 0
    assert body["email"] == "ada@example.com"
    assert body["full_name"] == "Ada Lovelace"
    assert body["created_at"] and body["updated_at"]


def test_create_requires_valid_email(client, payload):
    response = client.post(BASE, json={**payload, "email": "not-an-email"})
    assert response.status_code == 422


def test_create_requires_names(client, payload):
    response = client.post(BASE, json={**payload, "first_name": ""})
    assert response.status_code == 422


def test_duplicate_email_conflicts(client, payload):
    assert client.post(BASE, json=payload).status_code == 201
    response = client.post(BASE, json={**payload, "email": "ADA@example.com"})
    assert response.status_code == 409


def test_get_contact(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.get(f"{BASE}/{contact_id}")
    assert response.status_code == 200
    assert response.json()["id"] == contact_id


def test_get_missing_contact_returns_404(client):
    assert client.get(f"{BASE}/9999").status_code == 404


def test_list_pagination_and_total(client, payload):
    for index in range(5):
        client.post(BASE, json={**payload, "email": f"user{index}@example.com"})

    response = client.get(BASE, params={"limit": 2, "offset": 2})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["limit"] == 2 and body["offset"] == 2


def test_list_search(client, payload):
    client.post(BASE, json=payload)
    client.post(
        BASE,
        json={**payload, "first_name": "Grace", "last_name": "Hopper", "email": "grace@example.com", "company": "US Navy"},
    )

    hits = client.get(BASE, params={"search": "hopper"}).json()
    assert hits["total"] == 1
    assert hits["items"][0]["last_name"] == "Hopper"

    by_company = client.get(BASE, params={"search": "navy"}).json()
    assert by_company["total"] == 1

    misses = client.get(BASE, params={"search": "nobody"}).json()
    assert misses["total"] == 0


def test_list_sorting(client, payload):
    client.post(BASE, json={**payload, "last_name": "Zhang", "email": "z@example.com"})
    client.post(BASE, json={**payload, "last_name": "Adams", "email": "a@example.com"})

    names = [
        item["last_name"]
        for item in client.get(BASE, params={"sort_by": "last_name", "order": "asc"}).json()["items"]
    ]
    assert names == ["Adams", "Zhang"]


def test_list_rejects_bad_sort_field(client):
    assert client.get(BASE, params={"sort_by": "; DROP TABLE contacts"}).status_code == 422


def test_patch_updates_only_sent_fields(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.patch(f"{BASE}/{contact_id}", json={"phone": "+1-000-000-0000"})
    assert response.status_code == 200
    body = response.json()
    assert body["phone"] == "+1-000-000-0000"
    assert body["first_name"] == "Ada"
    assert body["company"] == "Analytical Engines"


def test_patch_duplicate_email_conflicts(client, payload):
    first = client.post(BASE, json=payload).json()["id"]
    client.post(BASE, json={**payload, "email": "grace@example.com"})
    response = client.patch(f"{BASE}/{first}", json={"email": "grace@example.com"})
    assert response.status_code == 409


def test_patch_same_email_is_allowed(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.patch(f"{BASE}/{contact_id}", json={"email": payload["email"]})
    assert response.status_code == 200


def test_put_replaces_contact(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.put(
        f"{BASE}/{contact_id}",
        json={"first_name": "Grace", "last_name": "Hopper", "email": "grace@example.com"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["full_name"] == "Grace Hopper"
    assert body["company"] is None  # omitted fields are cleared by PUT


def test_put_missing_contact_returns_404(client):
    response = client.put(
        f"{BASE}/9999",
        json={"first_name": "A", "last_name": "B", "email": "ab@example.com"},
    )
    assert response.status_code == 404


def test_delete_contact(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    assert client.delete(f"{BASE}/{contact_id}").status_code == 204
    assert client.get(f"{BASE}/{contact_id}").status_code == 404
    assert client.delete(f"{BASE}/{contact_id}").status_code == 404


def test_root_lists_entrypoints(client):
    body = client.get("/").json()
    assert body["contacts"] == BASE


# --------------------------------------------------------------------------- #
# Contact photo                                                               #
# --------------------------------------------------------------------------- #

PNG_PIXEL = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAA"
    "DUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def test_contact_defaults_to_no_photo(client, payload):
    response = client.post(BASE, json=payload)
    assert response.status_code == 201
    assert response.json()["photo"] is None


def test_create_contact_with_photo(client, payload):
    response = client.post(BASE, json={**payload, "photo": PNG_PIXEL})
    assert response.status_code == 201
    assert response.json()["photo"] == PNG_PIXEL


def test_blank_photo_is_stored_as_null(client, payload):
    response = client.post(BASE, json={**payload, "photo": "   "})
    assert response.status_code == 201
    assert response.json()["photo"] is None


def test_photo_must_be_an_image_data_url(client, payload):
    response = client.post(BASE, json={**payload, "photo": "https://example.com/ada.png"})
    assert response.status_code == 422


def test_photo_rejects_disallowed_media_type(client, payload):
    response = client.post(BASE, json={**payload, "photo": "data:application/pdf;base64,AAAA"})
    assert response.status_code == 422


def test_photo_rejects_oversized_payload(client, payload):
    oversized = "data:image/png;base64," + ("A" * (256 * 1024))
    response = client.post(BASE, json={**payload, "photo": oversized})
    assert response.status_code == 422


def test_photo_rejects_undecodable_base64(client, payload):
    """The alphabet alone is not enough — "A" is not a whole base64 group."""
    response = client.post(BASE, json={**payload, "photo": "data:image/png;base64,A"})
    assert response.status_code == 422


def test_photo_rejects_empty_payload(client, payload):
    response = client.post(BASE, json={**payload, "photo": "data:image/png;base64,===="})
    assert response.status_code == 422


def test_photo_rejects_non_image_bytes(client, payload):
    """Valid base64 that decodes to "Hello" is not a PNG."""
    response = client.post(BASE, json={**payload, "photo": "data:image/png;base64,SGVsbG8="})
    assert response.status_code == 422


def test_photo_rejects_media_type_mismatch(client, payload):
    """A real PNG payload declared as a JPEG is a lie worth rejecting."""
    png_as_jpeg = PNG_PIXEL.replace("data:image/png", "data:image/jpeg")
    response = client.post(BASE, json={**payload, "photo": png_as_jpeg})
    assert response.status_code == 422


def test_photo_accepts_each_allowed_type(client, payload):
    import base64 as _b64

    samples = {
        "jpeg": b"\xff\xd8\xff\xdb" + b"\x00" * 8,
        "gif": b"GIF89a" + b"\x00" * 8,
        "webp": b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 4,
    }
    for index, (media, raw) in enumerate(samples.items()):
        encoded = _b64.b64encode(raw).decode()
        response = client.post(
            BASE,
            json={
                **payload,
                "email": f"{media}@example.com",
                "photo": f"data:image/{media};base64,{encoded}",
            },
        )
        assert response.status_code == 201, (media, response.text)
        assert response.json()["photo"].startswith(f"data:image/{media};base64,")


def test_patch_preserves_photo_when_not_sent(client, payload):
    contact_id = client.post(BASE, json={**payload, "photo": PNG_PIXEL}).json()["id"]

    response = client.patch(f"{BASE}/{contact_id}", json={"job_title": "Countess"})
    assert response.status_code == 200
    body = response.json()
    assert body["job_title"] == "Countess"
    assert body["photo"] == PNG_PIXEL


def test_patch_can_clear_photo(client, payload):
    contact_id = client.post(BASE, json={**payload, "photo": PNG_PIXEL}).json()["id"]

    response = client.patch(f"{BASE}/{contact_id}", json={"photo": None})
    assert response.status_code == 200
    assert response.json()["photo"] is None


def test_put_without_photo_clears_it(client, payload):
    """PUT is a full replacement, so an omitted photo is intentionally dropped.

    The UI must therefore round-trip the existing photo through its edit form —
    see the hidden `photo` input in `ContactPhotoField`.
    """
    contact_id = client.post(BASE, json={**payload, "photo": PNG_PIXEL}).json()["id"]

    response = client.put(f"{BASE}/{contact_id}", json=payload)
    assert response.status_code == 200
    assert response.json()["photo"] is None


def test_put_round_trips_photo(client, payload):
    contact_id = client.post(BASE, json={**payload, "photo": PNG_PIXEL}).json()["id"]

    response = client.put(f"{BASE}/{contact_id}", json={**payload, "photo": PNG_PIXEL})
    assert response.status_code == 200
    assert response.json()["photo"] == PNG_PIXEL


# --------------------------------------------------------------------------- #
# Multiple addresses                                                          #
# --------------------------------------------------------------------------- #

HOME = {"type": "home", "street": "12 Ockham Rd", "city": "London", "country": "UK"}
WORK = {"type": "work", "street": "1 Market St", "city": "San Francisco", "state": "CA"}


def test_contact_can_hold_several_addresses(client, payload):
    response = client.post(BASE, json={**payload, "addresses": [HOME, WORK]})
    assert response.status_code == 201

    addresses = response.json()["addresses"]
    assert [a["type"] for a in addresses] == ["home", "work"]
    assert [a["city"] for a in addresses] == ["London", "San Francisco"]


def test_addresses_default_to_empty(client, payload):
    response = client.post(BASE, json={**payload, "addresses": []})
    assert response.status_code == 201
    assert response.json()["addresses"] == []


def test_each_address_links_back_to_its_contact(client, payload):
    body = client.post(BASE, json={**payload, "addresses": [HOME, WORK]}).json()

    assert {a["contact_id"] for a in body["addresses"]} == {body["id"]}
    assert len({a["id"] for a in body["addresses"]}) == 2


def test_address_type_is_constrained(client, payload):
    response = client.post(BASE, json={**payload, "addresses": [{**HOME, "type": "holiday"}]})
    assert response.status_code == 422


def test_many_addresses_of_the_same_type_are_allowed(client, payload):
    """Two work addresses is a normal thing, not a validation error."""
    response = client.post(BASE, json={**payload, "addresses": [WORK, {**WORK, "city": "Oakland"}]})
    assert response.status_code == 201
    assert [a["city"] for a in response.json()["addresses"]] == ["San Francisco", "Oakland"]


def test_put_replaces_the_whole_address_set(client, payload):
    contact_id = client.post(BASE, json={**payload, "addresses": [HOME, WORK]}).json()["id"]

    response = client.put(f"{BASE}/{contact_id}", json={**payload, "addresses": [HOME]})
    assert response.status_code == 200
    assert [a["type"] for a in response.json()["addresses"]] == ["home"]


def test_patch_leaves_addresses_alone_when_not_sent(client, payload):
    contact_id = client.post(BASE, json={**payload, "addresses": [HOME, WORK]}).json()["id"]

    response = client.patch(f"{BASE}/{contact_id}", json={"job_title": "Countess"})
    assert response.status_code == 200
    assert len(response.json()["addresses"]) == 2


def test_patch_can_clear_addresses_with_an_empty_list(client, payload):
    contact_id = client.post(BASE, json={**payload, "addresses": [HOME]}).json()["id"]

    response = client.patch(f"{BASE}/{contact_id}", json={"addresses": []})
    assert response.status_code == 200
    assert response.json()["addresses"] == []


def test_replaced_addresses_do_not_linger(client, payload):
    """delete-orphan must remove the old rows, not just detach them."""
    from app.database import SessionLocal
    from app.models import Address

    contact_id = client.post(BASE, json={**payload, "addresses": [HOME, WORK]}).json()["id"]
    client.put(f"{BASE}/{contact_id}", json={**payload, "addresses": [HOME]})

    with SessionLocal() as db:
        assert db.query(Address).count() == 1


def test_deleting_a_contact_deletes_its_addresses(client, payload):
    from app.database import SessionLocal
    from app.models import Address

    contact_id = client.post(BASE, json={**payload, "addresses": [HOME, WORK]}).json()["id"]
    assert client.delete(f"{BASE}/{contact_id}").status_code == 204

    with SessionLocal() as db:
        assert db.query(Address).count() == 0


def test_search_reaches_into_addresses(client, payload):
    client.post(BASE, json={**payload, "addresses": [HOME]})
    client.post(BASE, json={**payload, "email": "b@example.com", "addresses": [WORK]})

    response = client.get(BASE, params={"search": "London"})
    assert response.status_code == 200
    assert response.json()["total"] == 1
