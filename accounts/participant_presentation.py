from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ObjectDoesNotExist
from django.urls import reverse
from django.utils import timezone

from access.models import AccessStatus, CredentialStatus
from activities.models import OccurrencePlaceRole
from commerce.models import CommerceOrderStatus, PaymentMode
from journeys.models import JourneyStatus, RequestStatus, WorkflowKind


JOURNEY_STATUS_LABELS = {
    JourneyStatus.DRAFT: "À terminer",
    JourneyStatus.SUBMITTED: "Envoyée",
    JourneyStatus.PENDING_APPROVAL: "En attente de validation",
    JourneyStatus.APPROVED: "Approuvée",
    JourneyStatus.PENDING_PAYMENT: "Paiement requis",
    JourneyStatus.CONFIRMED: "Confirmée",
    JourneyStatus.FULFILLED: "Terminée",
    JourneyStatus.REJECTED: "Refusée",
    JourneyStatus.CANCELLED: "Annulée",
    JourneyStatus.EXPIRED: "Expirée",
}

ACCESS_STATUS_LABELS = {
    AccessStatus.PENDING: "En préparation",
    AccessStatus.VALID: "Valide",
    AccessStatus.USED: "Utilisé",
    AccessStatus.CANCELLED: "Annulé",
    AccessStatus.REVOKED: "Révoqué",
    AccessStatus.EXPIRED: "Expiré",
    AccessStatus.TRANSFERRED: "Transféré",
}

PAYMENT_MODE_LABELS = {
    PaymentMode.NONE: "Aucun paiement requis",
    PaymentMode.UPFRONT: "Paiement en ligne requis",
    PaymentMode.AFTER_APPROVAL: "Paiement après validation",
    PaymentMode.ON_SITE: "À payer sur place",
    PaymentMode.LATER: "Paiement prévu plus tard",
}


def event_for_activity(activity):
    try:
        return activity.event_vertical
    except (ObjectDoesNotExist, AttributeError):
        return None


def primary_occurrence(*, activity, occurrence=None):
    if occurrence is not None:
        return occurrence
    prefetched = getattr(activity, "_prefetched_objects_cache", {}).get("occurrences")
    if prefetched is not None:
        return prefetched[0] if prefetched else None
    return activity.occurrences.order_by("start_at", "id").first()


def primary_place(occurrence):
    if occurrence is None:
        return None
    prefetched = getattr(occurrence, "_prefetched_objects_cache", {}).get("place_links")
    if prefetched is not None:
        primary = [link for link in prefetched if link.role == OccurrencePlaceRole.PRIMARY]
        if primary:
            return primary[0].place
        return prefetched[0].place if prefetched else None
    link = (
        occurrence.place_links.select_related("place")
        .order_by("position", "role", "id")
        .first()
    )
    return link.place if link else None


def _local_datetime(value, timezone_name):
    if value is None:
        return None
    try:
        tz = ZoneInfo(timezone_name or "Africa/Lubumbashi")
    except ZoneInfoNotFoundError:
        tz = timezone.get_current_timezone()
    return timezone.localtime(value, tz)


def occurrence_presentation(*, activity, occurrence=None):
    occurrence = primary_occurrence(activity=activity, occurrence=occurrence)
    if occurrence is None:
        return {
            "object": None,
            "start": None,
            "end": None,
            "timezone": "",
            "place": None,
            "place_name": "",
            "address": "",
            "locality": "",
            "access_instructions": "",
            "online_url": "",
            "venue_kind": "",
            "is_past": False,
            "is_ongoing": False,
        }

    place = primary_place(occurrence)
    event = event_for_activity(activity)
    venue = getattr(event, "venue", None) if event else None
    start = _local_datetime(occurrence.start_at, occurrence.timezone)
    end = _local_datetime(occurrence.end_at, occurrence.timezone)
    now = timezone.now()
    return {
        "object": occurrence,
        "start": start,
        "end": end,
        "timezone": occurrence.timezone,
        "place": place,
        "place_name": getattr(place, "name", ""),
        "address": getattr(place, "address_line", ""),
        "locality": getattr(place, "locality", ""),
        "access_instructions": getattr(place, "access_instructions", ""),
        "online_url": getattr(venue, "online_url", "") if venue else "",
        "venue_kind": getattr(venue, "kind", "") if venue else "",
        "is_past": bool(occurrence.end_at and occurrence.end_at <= now),
        "is_ongoing": occurrence.start_at <= now and (
            occurrence.end_at is None or occurrence.end_at > now
        ),
    }


def journey_noun(journey):
    event = event_for_activity(journey.activity)
    if journey.workflow == WorkflowKind.INVITATION:
        return "Invitation"
    if journey.workflow == WorkflowKind.RESERVATION:
        return "Réservation"
    if journey.workflow == WorkflowKind.REGISTRATION:
        return "Inscription"
    if journey.workflow == WorkflowKind.ORDER_APPROVAL:
        return "Demande"
    if journey.workflow == WorkflowKind.PURCHASE and event is not None:
        return "Achat de billet"
    if journey.workflow == WorkflowKind.PURCHASE:
        return "Achat"
    return "Démarche"


def access_noun(access):
    if event_for_activity(access.activity) is not None:
        return "Billet"
    workflow = getattr(access.journey, "workflow", "") if access.journey_id else ""
    if workflow == WorkflowKind.REGISTRATION:
        return "Confirmation"
    if workflow == WorkflowKind.INVITATION:
        return "Invitation"
    if workflow == WorkflowKind.RESERVATION:
        return "Réservation"
    return "Accès"


def _prefetched_objects(instance, related_name):
    cached = getattr(instance, "_prefetched_objects_cache", {}).get(related_name)
    return list(cached) if cached is not None else None


def journey_orders(journey):
    cached = _prefetched_objects(journey, "commerce_orders")
    if cached is not None:
        return cached
    return list(journey.commerce_orders.prefetch_related("payments", "items__offer").order_by("-created_at", "id"))


def journey_accesses(journey):
    cached = _prefetched_objects(journey, "accesses")
    if cached is not None:
        return cached
    return list(
        journey.accesses.select_related("activity", "occurrence", "journey")
        .prefetch_related("credentials")
        .order_by("-created_at", "id")
    )


def primary_order(journey):
    orders = journey_orders(journey)
    return orders[0] if orders else None


def primary_access(journey):
    accesses = journey_accesses(journey)
    priority = {
        AccessStatus.VALID: 0,
        AccessStatus.PENDING: 1,
        AccessStatus.USED: 2,
        AccessStatus.TRANSFERRED: 3,
        AccessStatus.CANCELLED: 4,
        AccessStatus.REVOKED: 5,
        AccessStatus.EXPIRED: 6,
    }
    return sorted(accesses, key=lambda row: (priority.get(row.status, 9), -row.created_at.timestamp()))[0] if accesses else None


def active_credential(access):
    credentials = _prefetched_objects(access, "credentials")
    if credentials is None:
        credentials = list(access.credentials.order_by("-version", "-issued_at", "id"))
    return next((row for row in credentials if row.status == CredentialStatus.ACTIVE), None)


def payment_mode_label(order):
    if order is None:
        return ""
    return PAYMENT_MODE_LABELS.get(order.payment_mode, order.get_payment_mode_display())


def journey_status_label(journey):
    order = primary_order(journey)
    if journey.status == JourneyStatus.PENDING_PAYMENT and order is not None:
        if order.payment_mode == PaymentMode.ON_SITE:
            return "À payer sur place"
        if order.payment_mode == PaymentMode.LATER:
            return "Paiement prévu plus tard"
        if order.payment_mode == PaymentMode.NONE or order.total <= 0:
            return "Confirmation en cours"
    return JOURNEY_STATUS_LABELS.get(journey.status, journey.get_status_display())


def access_status_label(access):
    noun = access_noun(access)
    if access.status == AccessStatus.VALID:
        if noun == "Billet":
            return "Billet valide"
        if noun == "Confirmation":
            return "Inscription confirmée"
        if noun == "Invitation":
            return "Invitation confirmée"
        if noun == "Réservation":
            return "Réservation confirmée"
    if access.status == AccessStatus.USED and noun == "Billet":
        return "Billet utilisé"
    return ACCESS_STATUS_LABELS.get(access.status, access.get_status_display())


def payment_presentation(journey):
    order = primary_order(journey)
    if order is None or order.payment_mode == PaymentMode.NONE:
        return None
    payments = _prefetched_objects(order, "payments")
    if payments is None:
        payments = list(order.payments.order_by("-created_at", "id"))
    latest = payments[0] if payments else None
    return {
        "order": order,
        "amount": order.total,
        "currency": order.currency,
        "mode": order.payment_mode,
        "mode_label": payment_mode_label(order),
        "latest": latest,
        "failed": bool(latest and latest.status == "failed"),
        "succeeded": bool(latest and latest.status == "succeeded"),
        "action_url": reverse("payments:commerce-start", kwargs={"order_pk": order.pk})
        if order.status == CommerceOrderStatus.PENDING
        and order.total > 0
        and order.payment_mode in {PaymentMode.UPFRONT, PaymentMode.AFTER_APPROVAL}
        else "",
    }


def next_participant_action(journey):
    detail_url = reverse("account:journey-detail", kwargs={"pk": journey.pk})
    access = primary_access(journey)
    order = primary_order(journey)

    if journey.status == JourneyStatus.DRAFT:
        return {
            "label": "Continuer",
            "url": detail_url,
            "description": "Cette démarche n’est pas encore terminée.",
            "actionable": True,
        }
    if journey.status in {JourneyStatus.SUBMITTED, JourneyStatus.PENDING_APPROVAL}:
        return {
            "label": "En attente de validation",
            "url": detail_url,
            "description": "Aucune action n’est requise pour le moment.",
            "actionable": False,
        }
    if journey.status == JourneyStatus.APPROVED:
        return {
            "label": "Validation reçue",
            "url": detail_url,
            "description": "Votre demande a été approuvée.",
            "actionable": False,
        }
    if journey.status == JourneyStatus.PENDING_PAYMENT:
        if order is not None and order.payment_mode == PaymentMode.ON_SITE:
            return {
                "label": "À payer sur place",
                "url": detail_url,
                "description": "Aucun paiement en ligne n’est attendu.",
                "actionable": False,
            }
        if order is not None and order.payment_mode == PaymentMode.LATER:
            return {
                "label": "Voir les modalités",
                "url": detail_url,
                "description": "Le paiement est prévu ultérieurement.",
                "actionable": True,
            }
        if order is not None and order.total > 0:
            return {
                "label": "Payer",
                "url": reverse("payments:commerce-start", kwargs={"order_pk": order.pk}),
                "description": f"{order.total} {order.currency} à régler.",
                "actionable": True,
            }
        return {
            "label": "Voir la démarche",
            "url": detail_url,
            "description": "La confirmation est en cours.",
            "actionable": False,
        }
    if journey.status in {JourneyStatus.CONFIRMED, JourneyStatus.FULFILLED} and access is not None:
        return {
            "label": f"Voir {access_noun(access).lower()}",
            "url": reverse("account:access-detail", kwargs={"pk": access.pk}),
            "description": access_status_label(access),
            "actionable": True,
        }
    return {
        "label": "Voir la démarche",
        "url": detail_url,
        "description": journey_status_label(journey),
        "actionable": False,
    }


def _timeline_label(journey, status):
    noun = journey_noun(journey)
    if status == JourneyStatus.DRAFT:
        return f"{noun} commencée"
    if status == JourneyStatus.SUBMITTED:
        return f"{noun} envoyée"
    if status == JourneyStatus.PENDING_APPROVAL:
        return "Validation en attente"
    if status == JourneyStatus.APPROVED:
        return "Validation reçue"
    if status == JourneyStatus.PENDING_PAYMENT:
        order = primary_order(journey)
        if order and order.payment_mode == PaymentMode.ON_SITE:
            return "Paiement prévu sur place"
        if order and order.payment_mode == PaymentMode.LATER:
            return "Paiement prévu plus tard"
        return "Paiement requis"
    if status == JourneyStatus.CONFIRMED:
        return f"{noun} confirmée"
    if status == JourneyStatus.FULFILLED:
        return f"{noun} terminée"
    return JOURNEY_STATUS_LABELS.get(status, status)


def journey_timeline(journey):
    transitions = _prefetched_objects(journey, "transitions")
    if transitions is None:
        transitions = list(journey.transitions.order_by("created_at", "id"))
    statuses = [JourneyStatus.DRAFT]
    statuses.extend(row.to_status for row in transitions)
    statuses.append(journey.status)
    deduped = []
    for status in statuses:
        if status not in deduped:
            deduped.append(status)
    steps = [
        {
            "status": status,
            "label": _timeline_label(journey, status),
            "current": status == journey.status,
            "complete": status != journey.status or journey.status in {JourneyStatus.CONFIRMED, JourneyStatus.FULFILLED},
        }
        for status in deduped
    ]
    access = primary_access(journey)
    if access is not None:
        steps.append(
            {
                "status": f"access:{access.status}",
                "label": access_status_label(access),
                "current": journey.status in {JourneyStatus.CONFIRMED, JourneyStatus.FULFILLED},
                "complete": access.status in {AccessStatus.VALID, AccessStatus.USED},
            }
        )
    return steps


def request_presentation(journey):
    requests = _prefetched_objects(journey, "requests")
    if requests is None:
        requests = list(journey.requests.order_by("created_at", "id"))
    request = requests[-1] if requests else None
    if request is None:
        return None
    if request.status == RequestStatus.PENDING:
        return {"status": request.status, "label": "En attente de validation", "message": "Makolo attend la décision de la personne ou de l’équipe responsable."}
    if request.status == RequestStatus.REJECTED:
        return {"status": request.status, "label": "Demande refusée", "message": "Cette demande n’a pas été acceptée."}
    if request.status == RequestStatus.APPROVED:
        return {"status": request.status, "label": "Demande approuvée", "message": "La validation a été reçue."}
    return {"status": request.status, "label": request.get_status_display(), "message": ""}


def journey_presentation(journey):
    occurrence = occurrence_presentation(activity=journey.activity, occurrence=journey.occurrence)
    return {
        "object": journey,
        "noun": journey_noun(journey),
        "title": journey.activity.title,
        "status_label": journey_status_label(journey),
        "occurrence": occurrence,
        "next_action": next_participant_action(journey),
        "payment": payment_presentation(journey),
        "request": request_presentation(journey),
        "access": primary_access(journey),
        "timeline": journey_timeline(journey),
        "detail_url": reverse("account:journey-detail", kwargs={"pk": journey.pk}),
    }


def access_presentation(access):
    occurrence = occurrence_presentation(activity=access.activity, occurrence=access.occurrence)
    credential = active_credential(access)
    noun = access_noun(access)
    legacy_ticket = None
    try:
        legacy_ticket = access.ticket
    except (ObjectDoesNotExist, AttributeError):
        pass
    return {
        "object": access,
        "noun": noun,
        "title": access.activity.title,
        "status_label": access_status_label(access),
        "occurrence": occurrence,
        "credential": credential,
        "legacy_ticket": legacy_ticket,
        "detail_url": reverse("account:access-detail", kwargs={"pk": access.pk}),
        "qr_url": reverse("account:access-qr", kwargs={"pk": access.pk}) if credential else "",
    }


def notification_participant_url(notification):
    if notification.access_id:
        return reverse("account:access-detail", kwargs={"pk": notification.access_id})
    if notification.journey_id:
        return reverse("account:journey-detail", kwargs={"pk": notification.journey_id})
    if notification.commerce_order_id and notification.commerce_order.journey_id:
        return reverse(
            "account:journey-detail",
            kwargs={"pk": notification.commerce_order.journey_id},
        )
    return ""
