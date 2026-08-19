from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from access.services import issue_access
from journeys.models import Journey, JourneyStatus, WorkflowKind
from journeys.services import cancel_journey, confirm_journey


def _owned_invitation(journey, actor):
    if not getattr(actor, "is_authenticated", False):
        raise PermissionDenied("Une authentification est requise.")
    current = (
        Journey.objects.select_related("activity", "occurrence", "beneficiary")
        .get(pk=journey.pk)
    )
    if current.beneficiary_id != actor.pk:
        raise PermissionDenied("Cette invitation appartient à une autre personne.")
    if current.workflow != WorkflowKind.INVITATION:
        raise ValidationError("Cette démarche n’est pas une invitation.")
    return current


@transaction.atomic
def accept_participant_invitation(*, journey, actor):
    """Accept an authority-approved invitation and issue its canonical Access.

    The participant surface does not invent a new state: approval remains the
    authority decision, confirmation records the beneficiary response, and
    Access remains the resulting right.
    """
    journey = _owned_invitation(journey, actor)
    if journey.status == JourneyStatus.CONFIRMED:
        confirmed = journey
    elif journey.status == JourneyStatus.APPROVED:
        confirmed = confirm_journey(
            journey=journey,
            actor=actor,
            reason="participant_invitation_accepted",
        )
    else:
        raise ValidationError("Cette invitation ne peut pas être acceptée maintenant.")

    access = issue_access(
        beneficiary=actor,
        activity=confirmed.activity,
        occurrence=confirmed.occurrence,
        journey=confirmed,
        source_key="participant-invitation",
    )
    return confirmed, access


@transaction.atomic
def decline_participant_invitation(*, journey, actor):
    journey = _owned_invitation(journey, actor)
    if journey.status == JourneyStatus.CANCELLED:
        return journey
    if journey.status not in {
        JourneyStatus.DRAFT,
        JourneyStatus.SUBMITTED,
        JourneyStatus.PENDING_APPROVAL,
        JourneyStatus.APPROVED,
    }:
        raise ValidationError("Cette invitation ne peut plus être refusée.")
    return cancel_journey(
        journey=journey,
        actor=actor,
        reason="participant_invitation_declined",
    )
