import base64
import binascii
import re
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field, field_validator

from app.models import AddressType


# A contact photo travels as a self-contained data URL so the in-memory database
# stays the only storage the app needs.
#
# The cap is deliberately tight. `ContactRead` carries the photo, and the list
# endpoint serves up to `MAX_LIMIT` contacts per page, so the per-photo ceiling
# is really a per-*page* ceiling multiplied by 200. At 256 KiB a full page of
# photos is bounded at ~50 MiB worst case, and the client downscales before
# uploading, so a realistic avatar lands two orders of magnitude under the cap.
PHOTO_MAX_CHARS = 256 * 1024
PHOTO_ALLOWED_TYPES = ("png", "jpeg", "gif", "webp")
_PHOTO_DATA_URL = re.compile(
    rf"^data:image/(?P<media>{'|'.join(PHOTO_ALLOWED_TYPES)});base64,(?P<data>[A-Za-z0-9+/]+={{0,2}})$"
)

def _detect_image_type(data: bytes) -> str | None:
    """Identify an image from its magic bytes, or return None if it is not one.

    Deliberately signature-based rather than a full decode: the goal is to prove
    the bytes are the image type they claim to be, which does not justify pulling
    an image-processing dependency into a contacts API.
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


PHOTO_DESCRIPTION = (
    "Profile photo as a base64 data URL, e.g. `data:image/png;base64,...`. "
    f"Allowed types: {', '.join(PHOTO_ALLOWED_TYPES)}. "
    f"Maximum {PHOTO_MAX_CHARS // 1024} KiB once encoded. "
    "Omit or send `null` to fall back to the contact's initials."
)
PHOTO_EXAMPLE = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="


def normalize_photo(value: str | None) -> str | None:
    """Validate a photo data URL, treating blank input as "no photo"."""
    if value is None:
        return None

    value = value.strip()
    if not value:
        return None

    if len(value) > PHOTO_MAX_CHARS:
        raise ValueError(f"Photo must be {PHOTO_MAX_CHARS // 1024} KiB or smaller once base64-encoded")

    match = _PHOTO_DATA_URL.fullmatch(value)
    if match is None:
        raise ValueError(
            "Photo must be a base64 data URL of type " + ", ".join(PHOTO_ALLOWED_TYPES)
        )

    declared = match.group("media")

    # The pattern only proves the payload uses the base64 alphabet. Decoding is
    # what proves it is actually decodable — "A" satisfies the alphabet but is
    # not a whole base64 group, and would be stored as an unusable image.
    try:
        decoded = base64.b64decode(match.group("data"), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Photo is not valid base64 data") from exc

    if not decoded:
        raise ValueError("Photo contains no image data")

    # Decoding proves the payload is base64; it does not prove it is an image.
    # Without this, `data:image/png;base64,SGVsbG8=` ("Hello") would be stored
    # and served as a photo that no client can render.
    detected = _detect_image_type(decoded)
    if detected is None:
        raise ValueError("Photo is not a recognised image")
    if detected != declared:
        raise ValueError(f"Photo is declared as {declared} but its contents are {detected}")

    return value


class AddressBase(BaseModel):
    """One postal address. Every part is optional; the type is not."""

    type: AddressType = Field(
        default=AddressType.HOME,
        description="What this address is used for.",
        examples=[AddressType.HOME],
    )
    street: str | None = Field(
        default=None, max_length=300, description="Street address, including unit or suite.",
        examples=["1 Market St, Suite 400"],
    )
    city: str | None = Field(default=None, max_length=120, description="City or locality.", examples=["San Francisco"])
    state: str | None = Field(default=None, max_length=120, description="State, province, or region.", examples=["CA"])
    postal_code: str | None = Field(default=None, max_length=20, description="Postal or ZIP code.", examples=["94105"])
    country: str | None = Field(default=None, max_length=120, description="Country name.", examples=["USA"])


class AddressCreate(AddressBase):
    """An address as supplied when creating or replacing a contact."""


class AddressRead(AddressBase):
    """A stored address, as returned inside a contact."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="Server-assigned identifier.", examples=[1])
    contact_id: int = Field(description="Contact this address belongs to.", examples=[1])


class ContactBase(BaseModel):
    """Fields shared by every contact request and response."""

    first_name: str = Field(
        min_length=1,
        max_length=100,
        description="Given name. Required, must not be blank.",
        examples=["Ada"],
    )
    last_name: str = Field(
        min_length=1,
        max_length=100,
        description="Family name. Required, must not be blank.",
        examples=["Lovelace"],
    )
    email: EmailStr = Field(
        max_length=320,
        description=(
            "Primary email address. Required and unique across all contacts; "
            "compared case-insensitively and stored lowercased."
        ),
        examples=["ada@example.com"],
    )
    phone: str | None = Field(
        default=None,
        max_length=40,
        description="Phone number. Stored verbatim — any format is accepted.",
        examples=["+1-415-555-0101"],
    )
    company: str | None = Field(
        default=None,
        max_length=200,
        description="Employer or organisation name.",
        examples=["Analytical Engines"],
    )
    job_title: str | None = Field(
        default=None,
        max_length=200,
        description="Role held at the company.",
        examples=["Mathematician"],
    )
    photo: str | None = Field(
        default=None,
        description=PHOTO_DESCRIPTION,
        examples=[PHOTO_EXAMPLE],
    )
    notes: str | None = Field(
        default=None,
        description="Free-form notes about the contact. No length limit.",
        examples=["Met at the SF hackathon."],
    )

    @field_validator("photo")
    @classmethod
    def _check_photo(cls, value: str | None) -> str | None:
        return normalize_photo(value)


_FULL_EXAMPLE = {
    "first_name": "Ada",
    "last_name": "Lovelace",
    "email": "ada@example.com",
    "phone": "+1-415-555-0101",
    "company": "Analytical Engines",
    "job_title": "Mathematician",
    "notes": "Met at the SF hackathon.",
    "addresses": [
        {
            "type": "home",
            "street": "1 Market St, Suite 400",
            "city": "San Francisco",
            "state": "CA",
            "postal_code": "94105",
            "country": "USA",
        }
    ],
}
_MINIMAL_EXAMPLE = {"first_name": "Grace", "last_name": "Hopper", "email": "grace@example.com"}


class ContactCreate(ContactBase):
    """Body of `POST /api/v1/contacts`. Only the two names and email are required."""

    addresses: list[AddressCreate] = Field(
        default_factory=list,
        description="Addresses to attach. Any number, each with its own type.",
    )

    model_config = ConfigDict(json_schema_extra={"examples": [_FULL_EXAMPLE, _MINIMAL_EXAMPLE]})


class ContactReplace(ContactBase):
    """
    Body of `PUT /api/v1/contacts/{contact_id}`.

    This is a full replacement: any optional field you omit is set back to `null`,
    and the addresses you send replace the existing set outright. Use `PATCH` if
    you only want to change some fields.
    """

    addresses: list[AddressCreate] = Field(
        default_factory=list,
        description="Replaces every existing address. Omit to remove them all.",
    )

    model_config = ConfigDict(json_schema_extra={"examples": [_FULL_EXAMPLE]})


class ContactUpdate(BaseModel):
    """
    Body of `PATCH /api/v1/contacts/{contact_id}`.

    Every field is optional. Only the fields actually present in the request are
    written; omitted fields keep their current value. Sending an explicit `null`
    clears that field.
    """

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"phone": "+1-415-555-0199", "job_title": "Chief Engineer"}]}
    )

    first_name: str | None = Field(default=None, min_length=1, max_length=100, description="New given name.")
    last_name: str | None = Field(default=None, min_length=1, max_length=100, description="New family name.")
    email: EmailStr | None = Field(
        default=None,
        max_length=320,
        description="New email address. Must not belong to another contact.",
    )
    phone: str | None = Field(default=None, max_length=40, description="New phone number.")
    company: str | None = Field(default=None, max_length=200, description="New company.")
    job_title: str | None = Field(default=None, max_length=200, description="New job title.")
    addresses: list[AddressCreate] | None = Field(
        default=None,
        description="Replaces every existing address. Omit to leave them untouched.",
    )
    photo: str | None = Field(default=None, description="New photo; send `null` to remove it.")
    notes: str | None = Field(default=None, description="New notes; replaces the existing text.")

    @field_validator("photo")
    @classmethod
    def _check_photo(cls, value: str | None) -> str | None:
        return normalize_photo(value)


class ContactRead(ContactBase):
    """A stored contact, as returned by every contact endpoint."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    **_FULL_EXAMPLE,
                    "id": 1,
                    "full_name": "Ada Lovelace",
                    "created_at": "2026-08-19T16:22:58.189507Z",
                    "updated_at": "2026-08-19T16:22:58.189511Z",
                }
            ]
        },
    )

    id: int = Field(description="Server-assigned identifier.", examples=[1])
    addresses: list[AddressRead] = Field(
        default_factory=list,
        description="Every address on file, oldest first.",
    )
    created_at: datetime = Field(
        description="UTC timestamp of when the contact was created.",
        examples=["2026-08-19T16:22:58.189507Z"],
    )
    updated_at: datetime = Field(
        description="UTC timestamp of the last modification.",
        examples=["2026-08-19T16:22:58.189511Z"],
    )

    @field_validator("created_at", "updated_at")
    @classmethod
    def _as_utc(cls, value: datetime) -> datetime:
        # SQLite discards tzinfo on write; the stored values are UTC, so label
        # them as such rather than emitting an ambiguous naive timestamp.
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

    @computed_field(description="Convenience concatenation of first and last name.", examples=["Ada Lovelace"])
    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class ContactPage(BaseModel):
    """One page of contacts plus the totals a client needs to paginate."""

    items: list[ContactRead] = Field(description="Contacts on this page, ordered by the requested sort.")
    total: int = Field(
        description="Total contacts matching the query, ignoring `limit` and `offset`.",
        examples=[42],
    )
    limit: int = Field(description="Page size that was applied.", examples=[50])
    offset: int = Field(description="Number of records skipped.", examples=[0])


class HealthResponse(BaseModel):
    """Result of the liveness probe."""

    status: str = Field(description="Always `ok` when the service can serve traffic.", examples=["ok"])
    database: str = Field(description="Active SQLAlchemy dialect.", examples=["sqlite"])
    contacts: int = Field(description="Number of contacts currently stored.", examples=[3])


class RootResponse(BaseModel):
    """Discovery document listing the API's entry points."""

    name: str = Field(description="Human-readable service name.", examples=["Contacts API"])
    version: str = Field(description="Service version.", examples=["0.1.0"])
    docs: str = Field(description="Path to the Swagger UI.", examples=["/docs"])
    redoc: str = Field(description="Path to the ReDoc UI.", examples=["/redoc"])
    openapi: str = Field(description="Path to the OpenAPI 3.1 document.", examples=["/openapi.json"])
    contacts: str = Field(description="Base path of the contacts collection.", examples=["/api/v1/contacts"])
    health: str = Field(description="Path to the liveness probe.", examples=["/health"])


class ErrorResponse(BaseModel):
    """Shape of every non-validation error returned by the API."""

    detail: str = Field(
        description="Human-readable explanation of the failure.",
        examples=["Contact 42 not found"],
    )
