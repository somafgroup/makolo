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
ACTIVE_ACCESS_STATUSES = [AccessStatus.PENDING, AccessStatus.VALID, AccessStatus.USED]


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
    """Canonical participant Journeys, independent from TicketOrder projections."""
    if not getattr(profile, "is_authenticated", False):
        return Journey.objects.none()

    order_items = CommerceOrderItem.objects.select_related("offer").order_by("created_at", "id")
    orders = (
        CommerceOrder.objects.select_related("buyer", "payee_space")
        .prefetch_related(Prefetch("items", queryset=order_items), "payments")
        .order_by("-created_at", "id")
    )
    return (
        Journey.objects.filter(Q(beneficiary=profile) | Q(initiated_by=profile))
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
            Prefetch("commerce_orders", queryset=orders),
            Prefetch("accesses", queryset=_access_queryset()),
        )
        .distinct()
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


def participant_accesses(profile):
    """Canonical participant Access rights, including history and transfers."""
    if not getattr(profile, "is_authenticated", False):
        return Access.objects.none()
    return (
        _access_queryset()
        .filter(beneficiary=profile)
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


def participant_upcoming_accesses(profile, *, now=None):
    now = now or timezone.now()
    return (
        participant_accesses(profile)
        .filter(status__in=[AccessStatus.PENDING, AccessStatus.VALID])
        .filter(
            Q(occurrence__isnull=True)
            | Q(occurrence__end_at__gte=now)
            | Q(occurrence__end_at__isnull=True)
        )
        .order_by("occurrence__start_at", "-created_at")
    )


def participant_orders(profile):
    """Canonical Commerce orders visible to their participant owner."""
    if not getattr(profile, "is_authenticated", False):
        return CommerceOrder.objects.none()
    items = CommerceOrderItem.objects.select_related("offer").order_by("created_at", "id")
    return (
        CommerceOrder.objects.filter(
            Q(buyer=profile)
            | Q(journey__beneficiary=profile)
            | Q(journey__initiated_by=profile)
        )
        .select_related("buyer", "journey", "journey__activity", "journey__occurrence")
        .prefetch_related(Prefetch("items", queryset=items), "payments")
        .distinct()
        .order_by("-created_at", "id")
    )


def participant_upcoming_occurrences(profile, *, now=None):
    """Upcoming Occurrences reached through Journey or Access, never Event dates."""
    now = now or timezone.now()
    return (
        Occurrence.objects.filter(
            Q(
                access_rights__beneficiary=profile,
                access_rights__status__in=[AccessStatus.PENDING, AccessStatus.VALID],
            )
            | Q(
                journeys__beneficiary=profile,
                journeys__status__in=ACTIONABLE_JOURNEY_STATUSES + [JourneyStatus.CONFIRMED],
            )
            | Q(
                journeys__initiated_by=profile,
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
