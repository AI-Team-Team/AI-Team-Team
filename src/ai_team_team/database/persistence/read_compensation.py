"""Exact compensation proofs for cancelled, unreturned Host body reads only."""

from .records import DomainRecord, thaw


READ_FIELDS = frozenset({"read_at", "read_revision_number", "unread_override"})


def permits_read_compensation(previous, later, proofs):
    """Never grant a general watermark-regression or projection-rewrite bypass."""
    if previous.table_name != "chat_personal_views" or later.identity != previous.identity:
        return False
    for proof in proofs:
        prepared = DomainRecord.capture("chat_personal_views", proof["prepared"])
        original = DomainRecord.capture("chat_personal_views", proof["previous"])
        if prepared != previous or original.identity != previous.identity:
            continue
        if prepared.version != original.version + 1 or later.version != prepared.version + 1:
            continue
        if any(original.values[key] != prepared.values[key] for key in original.values
               if key not in READ_FIELDS | {"state_version"}):
            continue
        expected = {**thaw(prepared.values), **{key: original.values[key] for key in READ_FIELDS},
                    "state_version": later.version}
        if thaw(later.values) == expected:
            return True
    return False
