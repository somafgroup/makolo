from django.db.models import Case, IntegerField, Prefetch, Q, Value, When
from django.utils import timezone

from access.models import Access, AccessCredential, AccessStatus
from activities.models import Occurrence, OccurrencePlace, OccurrenceStatus
from commerce.models import CommerceOrder, CommerceOrderItem
from journeys.models import Journey, JourneyRequest, JourneyStatus, JourneyTransition


ACTIONABLE_JOURNEY_STATUSES = [
    JourneyStatus.PENDING_PAYMENT,
    JourneyStatus.DRAFT,
    JourneyStatus.PENDING_APPROVAL,
    JourneyStatus.SUBMITTED,
    JourneyStatus.APPROVED,
]
ACTIVE_JOURNEY_STATUSES = [
    JourneyStatus.DRAFT,
    JourneyStatus.SUBMITTED,
    JourneyStatus.PENDING_APPROVAL,
    JourneyStatus.APPROVED,
    JourneyStatus.PENDING_PAYMENT,
    JourneyStatus.CONFIRMED,
]
HISTORY_JOURNEY_STATUSES = [
    JourneyStatus.FULFILLED,
    JourneyStatus.REJECTED,
    JourneyStatus.CANCELLED,
    JourneyStatus.EXPIRED,
]
ACTIVE_ACCESS_STATUSES = [AccessStatus.PENDING, AccessStatus.VALID]
HISTORY_ACCESS_STATUSES = [
    AccessStatus.USED,
    AccessStatus.CANCELLED,
    AccessStatus.REVOKED,
    AccessStatus.EXPIRED,
    AccessStatus.TRANSFERRED,
]


def _participant_user(profile):
    """Accept the authenticated User used by the canonical core or its UserProfile wrapper."""
    user = getattr(profile, "user", profile)
    if not getattr(user, "is_authenticated", False):
        return None
    return user


def _place_links_queryset():
    return OccurrencePlace.objects.select_related("place").order_by("position", "role", "id")


def _occurrences_queryset():
    return Occurrence.objects.prefetch_related(
        Prefetch("place_links", queryset=_place_links_queryset())
    ).order_by("start_at", "id")


def _credentials_queryset():
    return AccessCredential.objects.order_by("-version", "-issued_at", "id")


def _access_queryset():
    return (
        Access.objects.select_related(
            "beneficiary",
            "activity",
            "activity__space",
            "activity__event_vertical",
            "activity__event_vertical__venue",
            "activity__event_vertical__venue__place",
            "occurrence",
            "journey",
        )
        .prefetch_related(
            Prefetch("credentials", queryset=_credentials_queryset()),
            Prefetch("occurrence__place_links", queryset=_place_links_queryset()),
            Prefetch("activity__occurrences", queryset=_occurrences_queryset()),
        )
    )


def participant_journeys(profile):
    """Canonical Journeys owned by the participant as beneficiary.

    Initiating a Journey for another person never grants access to that person's
    participant surface. Administrative visibility belongs to contextual
    authority views, not this selector.
    """
    user = _participant_user(profile)
    if user is None:
        return Journey.objects.none()

    order_items = CommerceOrderItem.objects.select_related("offer").order_by("created_at", "id")
    own_orders = (
        CommerceOrder.objects.filter(buyer=user)
        .select_related("buyer", "payee_space")
        .prefetch_related(Prefetch("items", queryset=order_items), "payments")
        .order_by("-created_at", "id")
    )
    return (
        Journey.objects.filter(beneficiary=user)
        .select_related(
            "beneficiary",
            "initiated_by",
            "activity",
            "activity__space",
            "activity__event_vertical",
            "activity__event_vertical__venue",
            "activity__event_vertical__venue__place",
            "occurrence",
        )
        .prefetch_related(
            Prefetch("activity__occurrences", queryset=_occurrences_queryset()),
            Prefetch("occurrence__place_links", queryset=_place_links_queryset()),
            Prefetch("requests", queryset=JourneyRequest.objects.order_by("created_at", "id")),
            Prefetch("transitions", queryset=JourneyTransition.objects.order_by("created_at", "id")),
            Prefetch("commerce_orders", queryset=own_orders),
            Prefetch("accesses", queryset=_access_queryset().filter(beneficiary=user)),
        )
        .order_by("-created_at", "id")
    )


def participant_actionable_journeys(profile):
    """Journeys requiring action or carrying an important waiting state."""
    return (
        participant_journeys(profile)
        .filter(status__in=ACTIONABLE_JOURNEY_STATUSES)
        .annotate(
            participant_priority=Case(
                When(status=JourneyStatus.PENDING_PAYMENT, then=Value(0)),
                When(status=JourneyStatus.DRAFT, then=Value(1)),
                When(status=JourneyStatus.PENDING_APPROVAL, then=Value(2)),
                When(status=JourneyStatus.SUBMITTED, then=Value(3)),
                When(status=JourneyStatus.APPROVED, then=Value(4)),
                default=Value(9),
                output_field=IntegerField(),
            )
        )
        .order_by("participant_priority", "occurrence__start_at", "-created_at")
    )


def participant_active_journeys(profile):
    return participant_journeys(profile).filter(status__in=ACTIVE_JOURNEY_STATUSES)


def participant_history_journeys(profile):
    return participant_journeys(profile).filter(status__in=HISTORY_JOURNEY_STATUSES)


def participant_accesses(profile):
    """Canonical Access rights owned by the participant, including history."""
    user = _participant_user(profile)
    if user is None:
        return Access.objects.none()
    return (
        _access_queryset()
        .filter(beneficiary=user)
        .annotate(
            participant_priority=Case(
                When(status=AccessStatus.VALID, then=Value(0)),
                When(status=AccessStatus.PENDING, then=Value(1)),
                When(status=AccessStatus.USED, then=Value(2)),
                default=Value(9),
                output_field=IntegerField(),
            )
        )
        .order_by("participant_priority", "occurrence__start_at", "-created_at")
    )


def participant_active_accesses(profile):
    return participant_accesses(profile).filter(status__in=ACTIVE_ACCESS_STATUSES)


def participant_upcoming_accesses(profile, *, now=None):
    now = now or timezone.now()
    return (
        participant_active_accesses(profile)
        .filter(
            Q(occurrence__isnull=True)
            | Q(occurrence__end_at__gte=now)
            | Q(occurrence__end_at__isnull=True, occurrence__start_at__gte=now)
        )
        .order_by("occurrence__start_at", "-created_at")
    )


def participant_access_history(profile):
    return participant_accesses(profile).filter(status__in=HISTORY_ACCESS_STATUSES)


def participant_orders(profile):
    """Commerce orders owned by this participant as buyer.

    A Journey beneficiary does not automatically gain visibility over a third
    party payer's financial order.
    """
    user = _participant_user(profile)
    if user is None:
        return CommerceOrder.objects.none()
    items = CommerceOrderItem.objects.select_related("offer").order_by("created_at", "id")
    return (
        CommerceOrder.objects.filter(buyer=user)
        .select_related("buyer", "journey", "journey__activity", "journey__occurrence")
        .prefetch_related(Prefetch("items", queryset=items), "payments")
        .order_by("-created_at", "id")
    )


def participant_upcoming_occurrences(profile, *, now=None):
    """Upcoming Occurrences reached through the participant's Journey or Access."""
    user = _participant_user(profile)
    if user is None:
        return Occurrence.objects.none()
    now = now or timezone.now()
    return (
        Occurrence.objects.filter(
            Q(
                access_rights__beneficiary=user,
                access_rights__status__in=ACTIVE_ACCESS_STATUSES,
            )
            | Q(
                journeys__beneficiary=user,
                journeys__status__in=ACTIONABLE_JOURNEY_STATUSES + [JourneyStatus.CONFIRMED],
            ),
            status__in=[OccurrenceStatus.SCHEDULED, OccurrenceStatus.DRAFT],
        )
        .filter(Q(end_at__gte=now) | Q(end_at__isnull=True, start_at__gte=now))
        .select_related("activity", "activity__space", "activity__event_vertical")
        .prefetch_related(Prefetch("place_links", queryset=_place_links_queryset()))
        .distinct()
        .order_by("start_at", "id")
    )
