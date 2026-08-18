"""Temporary compatibility adapter for the Event-to-Activity cutover.

The adapter accepts the historical Event object/query vocabulary while every
write is persisted in Activity, Occurrence or CapacityPool. It deliberately
contains no parallel business fields and can be removed after all callers have
migrated to the canonical APIs.
"""

from django.core.exceptions import ValidationError
from django.db import transaction

from activities.models import Activity, Occurrence
from capacity.models import CapacityPool

from .models import Event, EventQuerySet, EventStatus, EventVisibility, _occurrence_status_for_activity


_ACTIVITY_FIELDS = {
    "organization": "space",
    "organization_id": "space_id",
    "organizer": "created_by",
    "organizer_id": "created_by_id",
    "title": "title",
    "short_description": "short_description",
    "description": "description",
    "status": "status",
    "visibility": "visibility",
}
_OCCURRENCE_FIELDS = {
    "start_at": "start_at",
    "end_at": "end_at",
    "timezone": "timezone",
}
_LEGACY_FIELDS = frozenset((*_ACTIVITY_FIELDS, *_OCCURRENCE_FIELDS, "capacity"))
_EVENT_STATUS_LABELS = {
    "draft": "Brouillon",
    "published": "Publié",
    "cancelled": "Annulé",
    "completed": "Terminé",
    "archived": "Archivé",
}
_EVENT_VISIBILITY_LABELS = {
    "public": "Public",
    "unlisted": "Non répertorié",
    "private": "Privé",
}


def _pending(instance):
    return instance.__dict__.setdefault("_legacy_event_values", {})


def _dirty(instance):
    return instance.__dict__.setdefault("_legacy_event_dirty", set())


def _property(name, canonical_name, relation):
    original = getattr(Event, name)

    def getter(instance):
        if not instance.activity_id and name in _pending(instance):
            return _pending(instance)[name]
        return original.fget(instance)

    def setter(instance, value):
        _pending(instance)[name] = value
        _dirty(instance).add(name)
        if instance.activity_id:
            target = instance.activity if relation == "activity" else instance.primary_occurrence
            if target is not None:
                setattr(target, canonical_name, value)

    return property(getter, setter, doc=original.__doc__)


def _capacity_property():
    original = Event.capacity

    def getter(instance):
        if "capacity" in _pending(instance):
            return _pending(instance)["capacity"]
        return original.fget(instance)

    def setter(instance, value):
        _pending(instance)["capacity"] = value
        _dirty(instance).add("capacity")

    return property(getter, setter, doc=original.__doc__)


def _choice_display(choices, value):
    try:
        return choices(value).label
    except (TypeError, ValueError):
        return value or ""


def _event_choice_display(labels, choices, value):
    return labels.get(value, _choice_display(choices, value))


def _install_properties():
    for legacy, canonical in _ACTIVITY_FIELDS.items():
        setattr(Event, legacy, _property(legacy, canonical, "activity"))
    for legacy, canonical in _OCCURRENCE_FIELDS.items():
        setattr(Event, legacy, _property(legacy, canonical, "occurrence"))
    Event.capacity = _capacity_property()
    Event.get_status_display = lambda instance: _event_choice_display(
        _EVENT_STATUS_LABELS, EventStatus, instance.status
    )
    Event.get_visibility_display = lambda instance: _event_choice_display(
        _EVENT_VISIBILITY_LABELS, EventVisibility, instance.visibility
    )


def _install_init_and_save():
    original_init = Event.__init__
    original_save = Event.save

    def compat_init(instance, *args, **kwargs):
        legacy_values = {name: kwargs.pop(name) for name in tuple(kwargs) if name in _LEGACY_FIELDS}
        original_init(instance, *args, **kwargs)
        instance.__dict__["_legacy_event_values"] = legacy_values
        instance.__dict__["_legacy_event_dirty"] = set(legacy_values)

    @transaction.atomic
    def compat_save(instance, *args, **kwargs):
        update_fields = kwargs.pop("update_fields", None)
        requested = set(update_fields or ())
        pending = _pending(instance)
        dirty = _dirty(instance)
        legacy_to_persist = dirty if update_fields is None else dirty & requested
        creating = instance._state.adding

        if not instance.activity_id:
            title = pending.get("title")
            start_at = pending.get("start_at")
            if not title:
                raise ValidationError({"title": "Le titre de l’événement est requis."})
            if start_at is None:
                raise ValidationError({"start_at": "Le début de l’événement est requis."})
            activity = Activity(
                space=pending.get("organization"),
                space_id=pending.get("organization_id"),
                created_by=pending.get("organizer"),
                created_by_id=pending.get("organizer_id"),
                title=title,
                short_description=pending.get("short_description", ""),
                description=pending.get("description", ""),
                status=pending.get("status", EventStatus.DRAFT),
                visibility=pending.get("visibility", EventVisibility.PUBLIC),
            )
            activity.save()
            occurrence = Occurrence.objects.create(
                activity=activity,
                start_at=start_at,
                end_at=pending.get("end_at"),
                timezone=pending.get("timezone", "Africa/Lubumbashi"),
                status=_occurrence_status_for_activity(activity.status),
            )
            instance.activity = activity
            legacy_to_persist = set()
        else:
            activity = instance.activity
            activity_updates = []
            for legacy, canonical in _ACTIVITY_FIELDS.items():
                if legacy not in legacy_to_persist:
                    continue
                value = pending.get(legacy, getattr(activity, canonical))
                setattr(activity, canonical, value)
                activity_updates.append(canonical)
            if activity_updates:
                activity.save(update_fields=[*dict.fromkeys(activity_updates), "updated_at"])

            occurrence_updates = []
            occurrence = instance.primary_occurrence
            for legacy, canonical in _OCCURRENCE_FIELDS.items():
                if legacy not in legacy_to_persist:
                    continue
                if occurrence is None:
                    if legacy != "start_at":
                        continue
                    occurrence = Occurrence(activity=activity, start_at=pending["start_at"])
                setattr(occurrence, canonical, pending.get(legacy))
                occurrence_updates.append(canonical)
            if "status" in legacy_to_persist and occurrence is not None:
                occurrence.status = _occurrence_status_for_activity(activity.status)
                occurrence_updates.append("status")
            if occurrence_updates:
                if occurrence._state.adding:
                    occurrence.save()
                else:
                    occurrence.save(update_fields=[*dict.fromkeys(occurrence_updates), "updated_at"])

        if "capacity" in (dirty if update_fields is None else dirty & requested):
            occurrence = instance.primary_occurrence
            if occurrence is None:
                raise ValidationError({"capacity": "Une Occurrence est requise pour définir la capacité."})
            CapacityPool.objects.update_or_create(
                activity=instance.activity,
                occurrence=occurrence,
                source_key=f"event:{instance.pk}:capacity",
                defaults={
                    "label": "Capacité événement",
                    "total_quantity": pending.get("capacity"),
                    "is_active": True,
                },
            )

        event_update_fields = None
        if update_fields is not None:
            event_update_fields = [field for field in update_fields if field not in _LEGACY_FIELDS]
            if not creating and not event_update_fields:
                dirty.difference_update(legacy_to_persist)
                return None
            kwargs["update_fields"] = event_update_fields

        result = original_save(instance, *args, **kwargs)
        dirty.difference_update(legacy_to_persist)
        return result

    Event.__init__ = compat_init
    Event.save = compat_save


def _install_queryset_adapter():
    original_select_related = EventQuerySet.select_related
    original_update = EventQuerySet.update

    def select_related(queryset, *fields):
        if fields == (None,):
            return original_select_related(queryset, None)
        mapped = []
        for field in fields:
            if field == "organization":
                mapped.append("activity__space")
            elif field == "organizer":
                mapped.append("activity__created_by")
            else:
                mapped.append(field)
        return original_select_related(queryset, *mapped)

    @transaction.atomic
    def update(queryset, **kwargs):
        activity_updates = {}
        occurrence_updates = {}
        capacity_marker = object()
        capacity = kwargs.pop("capacity", capacity_marker)
        for legacy, canonical in _ACTIVITY_FIELDS.items():
            if legacy in kwargs:
                activity_updates[canonical] = kwargs.pop(legacy)
        for legacy, canonical in _OCCURRENCE_FIELDS.items():
            if legacy in kwargs:
                occurrence_updates[canonical] = kwargs.pop(legacy)

        rows = list(queryset.values_list("pk", "activity_id").distinct())
        if not rows:
            return 0
        activity_ids = [activity_id for _, activity_id in rows]
        if activity_updates:
            Activity.objects.filter(pk__in=activity_ids).update(**activity_updates)
        if "status" in activity_updates:
            occurrence_updates.setdefault("status", _occurrence_status_for_activity(activity_updates["status"]))
        if occurrence_updates:
            for activity_id in activity_ids:
                occurrence = Occurrence.objects.filter(activity_id=activity_id).order_by("start_at", "id").first()
                if occurrence is not None:
                    Occurrence.objects.filter(pk=occurrence.pk).update(**occurrence_updates)
        if capacity is not capacity_marker:
            for event_id, activity_id in rows:
                occurrence = Occurrence.objects.filter(activity_id=activity_id).order_by("start_at", "id").first()
                if occurrence is not None:
                    CapacityPool.objects.update_or_create(
                        activity_id=activity_id,
                        occurrence=occurrence,
                        source_key=f"event:{event_id}:capacity",
                        defaults={
                            "label": "Capacité événement",
                            "total_quantity": capacity,
                            "is_active": True,
                        },
                    )
        if kwargs:
            original_update(queryset, **kwargs)
        return len(rows)

    EventQuerySet.select_related = select_related
    EventQuerySet.update = update


def install_event_legacy_compat():
    if getattr(Event, "_legacy_compat_installed", False):
        return
    _install_properties()
    _install_init_and_save()
    _install_queryset_adapter()
    Event._legacy_compat_installed = True
