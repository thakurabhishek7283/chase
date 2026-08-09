"""Shared vocabulary for community-contributed, admin-moderated records.

Companies and job profiles are public data any user may propose, so both carry
the same review lifecycle. The constants live here rather than being spelled
twice so a new state is added in one place — and the CHECK constraints below
are generated from this tuple, which makes the database and the application
physically incapable of disagreeing about what a valid status is.
"""

MODERATION_STATUSES: tuple[str, ...] = ("pending", "approved", "rejected")


def status_check(table: str) -> str:
    """SQL for the `status` CHECK constraint on a moderated table."""
    values = ", ".join(f"'{s}'" for s in MODERATION_STATUSES)
    return f"status IN ({values})"


def status_constraint_name(table: str) -> str:
    return f"ck_{table}_status"
