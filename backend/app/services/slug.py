"""Company-name normalisation — the deduplication key for public company data.

Any user can add a company, so the same employer will be typed a dozen ways:
"Acme, Inc.", "ACME Inc", "Acme  Incorporated". A unique index on the raw name
accepts every one of them. Collapsing to a slug first makes the database itself
reject the duplicate, rather than relying on the user to search before typing.

The transformation is deliberately conservative. It normalises *punctuation,
case, and legal suffixes* — the ways one company's name is spelled — and never
tries to guess that two different names are the same business. "Meta" and
"Facebook" are a human judgement call, and belong to the admin review step.
"""

import re
import unicodedata

#: Corporate form suffixes, stripped from the end of a name. These carry no
#: identifying information — nobody means a different company by "Acme Ltd"
#: than by "Acme". Ordered longest-first so "pvt ltd" is consumed before "ltd".
_LEGAL_SUFFIXES: tuple[str, ...] = (
    "pvt ltd",
    "private limited",
    "pty ltd",
    "limited",
    "incorporated",
    "corporation",
    "company",
    "holdings",
    "group",
    "labs",
    "llc",
    "llp",
    "plc",
    "gmbh",
    "bv",
    "nv",
    "sarl",
    "sas",
    "spa",
    "srl",
    "ab",
    "as",
    "oy",
    "inc",
    "ltd",
    "corp",
    "co",
    "sa",
    "ag",
)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_SUFFIX_PATTERN = re.compile(
    r"(?:\s+(?:" + "|".join(re.escape(s) for s in _LEGAL_SUFFIXES) + r"))+$"
)


class InvalidCompanyNameError(ValueError):
    """The name normalises to nothing — it was punctuation or whitespace only."""


def slugify_company(name: str) -> str:
    """Reduce a company name to its deduplication key.

    >>> slugify_company("Acme, Inc.")
    'acme'
    >>> slugify_company("ACME   Incorporated")
    'acme'
    >>> slugify_company("Ltd")
    'ltd'
    """
    # Decompose accents so "Nestlé" and "Nestle" are one company.
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))

    # Separators become spaces before suffix stripping, so "Acme-Inc" and
    # "Acme Inc" reach the suffix rule in the same shape.
    cleaned = _NON_ALNUM.sub(" ", ascii_only.lower()).strip()

    # Strip suffixes repeatedly: "Acme Group Holdings Ltd" is still Acme.
    while True:
        stripped = _SUFFIX_PATTERN.sub("", cleaned).strip()
        if stripped == cleaned:
            break
        cleaned = stripped

    # A name that is *only* a suffix ("Ltd", "Group") is a real, if odd, name.
    # Falling back to the pre-strip form beats collapsing all of them to "".
    if not cleaned:
        cleaned = _NON_ALNUM.sub(" ", ascii_only.lower()).strip()

    slug = _NON_ALNUM.sub("-", cleaned).strip("-")
    if not slug:
        raise InvalidCompanyNameError(
            f"{name!r} contains no letters or digits, so it cannot identify a company."
        )
    return slug
