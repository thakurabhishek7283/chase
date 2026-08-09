"""The company-name normalisation rule, tested as a pure function.

Deduplication of public data rests entirely on this, so it is worth pinning
away from the HTTP layer as well as through it.
"""

import pytest

from app.services.slug import InvalidCompanyNameError, slugify_company


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Acme", "acme"),
        ("Acme Inc", "acme"),
        ("Acme, Inc.", "acme"),
        ("ACME   Incorporated", "acme"),
        ("Acme-Inc", "acme"),
        ("Acme Group Holdings Ltd", "acme"),
        ("Nestlé", "nestle"),
        ("Pied Piper", "pied-piper"),
        ("  Hooli  ", "hooli"),
        ("Ernst & Young", "ernst-young"),
    ],
)
def test_spellings_that_must_collapse(name: str, expected: str) -> None:
    assert slugify_company(name) == expected


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Stripe", "Stripe Inc"),
        ("Basecamp", "basecamp llc"),
        ("Siemens AG", "siemens"),
    ],
)
def test_pairs_that_are_the_same_company(left: str, right: str) -> None:
    assert slugify_company(left) == slugify_company(right)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        # Normalisation must not merge genuinely different employers.
        ("Acme", "Acme Labs Berlin"),
        ("Alpha", "Alphabet"),
        ("Meta", "Meta Platforms Research"),
    ],
)
def test_distinct_companies_stay_distinct(left: str, right: str) -> None:
    assert slugify_company(left) != slugify_company(right)


def test_a_name_that_is_only_a_legal_suffix_survives() -> None:
    """Stripping every token would collapse these onto each other."""
    assert slugify_company("Group") == "group"
    assert slugify_company("Ltd") == "ltd"
    assert slugify_company("Group") != slugify_company("Ltd")


def test_punctuation_only_names_are_refused() -> None:
    with pytest.raises(InvalidCompanyNameError):
        slugify_company("!!! ???")
