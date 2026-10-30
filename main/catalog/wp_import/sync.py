"""Upsert one model's rows by wp_id, writing only what changed."""

from dataclasses import dataclass, field


@dataclass
class SyncResult:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    missing: list[int] = field(default_factory=list)  # in Django, no longer in WP
    pruned: int = 0
    changed_fields: set[str] = field(default_factory=set)


def missing_wp_ids(model, source_wp_ids):
    """wp_ids that exist in Django but not in the source. NULL wp_ids are never included."""
    existing = model.objects.filter(wp_id__isnull=False).values_list("wp_id", flat=True)
    return sorted(set(existing) - set(source_wp_ids))


def sync_by_wp_id(model, rows, *, create_only=()):
    """Create new rows, update changed ones, leave the rest alone.

    ``rows`` is {wp_id: {field_attname: value}}. Fields in ``create_only`` are
    written when a row is created and never compared or updated afterwards
    (Django owns them from then on).

    Changes are found by comparing field values, not WordPress's
    post_modified: ACF/meta edits don't update post_modified.

    Returns (SyncResult, {wp_id: pk}) for every source row.
    """
    existing = {obj.wp_id: obj for obj in model.objects.filter(wp_id__in=list(rows))}
    result = SyncResult()
    to_create, to_update = [], []

    for wp_id, values in rows.items():
        obj = existing.get(wp_id)
        if obj is None:
            to_create.append(model(wp_id=wp_id, **values))
            continue
        changed = [
            name for name, value in values.items()
            if name not in create_only and getattr(obj, name) != value
        ]
        if not changed:
            result.unchanged += 1
            continue
        for name in changed:
            setattr(obj, name, values[name])
        result.changed_fields.update(changed)
        to_update.append(obj)

    created = model.objects.bulk_create(to_create)
    if to_update:
        model.objects.bulk_update(to_update, sorted(result.changed_fields))
    result.created = len(created)
    result.updated = len(to_update)

    ids = {obj.wp_id: obj.pk for obj in existing.values()}
    ids.update({obj.wp_id: obj.pk for obj in created})
    return result, ids
