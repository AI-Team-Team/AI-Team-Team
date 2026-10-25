"""Undo unobserved provisional additions after a failed runtime publication."""

from sqlalchemy import select, text

from ai_team_team.database.models import ACTIVITY_TABLES


def discard_provisional_records(session, publication_id):
    manifests = ACTIVITY_TABLES["publication_manifests"]
    manifest = session.execute(select(manifests).where(manifests.c.publication_id == publication_id)).mappings().one_or_none()
    if manifest is not None and manifest["status"] != "rolled_back":
        from .recovery_images import restore_images
        restore_images(session, manifest["recovery_before"])
    notices = ACTIVITY_TABLES["agent_notifications"]
    incidents = ACTIVITY_TABLES["recovery_incidents"]
    event_ids = session.execute(select(notices.c.system_event_id).where(notices.c.publication_id == publication_id)).scalars().all()
    session.execute(notices.delete().where(notices.c.publication_id == publication_id))
    session.execute(incidents.delete().where(incidents.c.publication_id == publication_id))
    for identifier in event_ids:
        session.execute(text("DELETE FROM system_memory_events WHERE event_id=:id"), {"id": identifier})
