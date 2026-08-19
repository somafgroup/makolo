from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from access.models import AccessStatus
from access.services import issue_access
from activities.models import (
    Activity,
    ActivityStatus,
    Occurrence,
    OccurrencePlace,
    OccurrencePlaceRole,
    OccurrenceStatus,
)
from commerce.models import Offer, OfferStatus, PaymentMode
from commerce.services import confirm_order, create_order
from events.models import Event, EventStatus, EventVisibility
from geography.models import Place
from journeys.models import JourneyStatus, WorkflowKind
from journeys.services import (
    create_journey,
    create_request,
    reject_request,
    submit_journey,
)
from notifications.models import Notification, NotificationCategory, NotificationKind
from payments.models import Payment, PaymentStatus
from tickets.models import Ticket, TicketOrder

from .participant_presentation import access_presentation, journey_presentation
from .participant_selectors import (
    participant_accesses,
    participant_journeys,
    participant_orders,
)


User = get_user_model()


@override_settings(PAYMENTS_SANDBOX_ENABLED=True)
class ParticipantExperienceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="participant-canonical",
            email="participant-canonical@example.com",
            password="Participant-2026!",
        )
        self.other = User.objects.create_user(
            username="participant-other",
            email="participant-other@example.com",
            password="Participant-2026!",
        )
        self.decider = User.objects.create_superuser(
            username="participant-decider",
            email="participant-decider@example.com",
            password="Participant-2026!",
        )
        self.client.force_login(self.user)

    def _activity(self, title, *, owner=None, days=3):
        owner = owner or self.user
        activity = Activity.objects.create(
            created_by=owner,
            title=title,
            status=ActivityStatus.PUBLISHED,
        )
        occurrence = Occurrence.objects.create(
            activity=activity,
            start_at=timezone.now() + timedelta(days=days),
            end_at=timezone.now() + timedelta(days=days, hours=2),
            status=OccurrenceStatus.SCHEDULED,
            timezone="Africa/Lubumbashi",
        )
        place = Place.objects.create(
            name=f"Lieu {title}",
            address_line="10 avenue Makolo",
            locality="Kinshasa",
            country_code="CD",
            timezone="Africa/Lubumbashi",
            access_instructions="Entrée principale.",
            created_by=owner,
        )
        OccurrencePlace.objects.create(
            occurrence=occurrence,
            place=place,
            role=OccurrencePlaceRole.PRIMARY,
        )
        return activity, occurrence, place

    def _offer(self, activity, occurrence, *, name="Accès", price="0.00", mode=PaymentMode.NONE):
        return Offer.objects.create(
            activity=activity,
            occurrence=occurrence,
            name=name,
            unit_price=Decimal(price),
            currency="USD",
            payment_mode=mode,
            status=OfferStatus.ACTIVE,
        )

    def _free_registration(self, *, user=None, title="Atelier sans Event"):
        user = user or self.user
        activity, occurrence, place = self._activity(title, owner=user)
        journey = create_journey(
            initiated_by=user,
            beneficiary=user,
            activity=activity,
            occurrence=occurrence,
            workflow=WorkflowKind.REGISTRATION,
        )
        submit_journey(journey=journey, actor=user)
        offer = self._offer(activity, occurrence, name="Inscription gratuite")
        order = create_order(journey=journey, buyer=user, selections=[(offer, 1)])
        confirm_order(order=order, actor=user)
        journey.refresh_from_db()
        access = issue_access(
            beneficiary=user,
            activity=activity,
            occurrence=occurrence,
            journey=journey,
            source_key="registration",
        )
        return activity, occurrence, place, journey, order, access

    def test_non_event_registration_works_without_ticket_or_ticket_order(self):
        activity, occurrence, place, journey, order, access = self._free_registration()

        self.assertFalse(Event.objects.filter(activity=activity).exists())
        self.assertEqual(Ticket.objects.count(), 0)
        self.assertEqual(TicketOrder.objects.count(), 0)
        self.assertEqual(Payment.objects.count(), 0)
        self.assertEqual(order.total, Decimal("0.00"))
        self.assertEqual(journey.status, JourneyStatus.CONFIRMED)

        home = self.client.get(reverse("account:home"))
        self.assertEqual(home.status_code, 200)
        self.assertContains(home, activity.title)
        self.assertContains(home, "Kinshasa")

        journey_response = self.client.get(reverse("account:journey-detail", args=[journey.pk]))
        self.assertEqual(journey_response.status_code, 200)
        self.assertContains(journey_response, "Inscription")
        self.assertContains(journey_response, "Confirmée")
        self.assertContains(journey_response, place.name)
        self.assertNotContains(journey_response, "Type de billet")

        access_response = self.client.get(reverse("account:access-detail", args=[access.pk]))
        self.assertEqual(access_response.status_code, 200)
        self.assertContains(access_response, "Confirmation")
        self.assertContains(access_response, "Inscription confirmée")
        self.assertContains(access_response, place.address_line)

        qr_response = self.client.get(reverse("account:access-qr", args=[access.pk]))
        self.assertEqual(qr_response.status_code, 200)
        self.assertEqual(qr_response["Content-Type"], "image/png")
        self.assertEqual(qr_response["Cache-Control"], "private, no-store")

    def test_pending_and_rejected_requests_hide_internal_decision_comment(self):
        activity, occurrence, _ = self._activity("Inscription avec validation")
        journey = create_journey(
            initiated_by=self.user,
            beneficiary=self.user,
            activity=activity,
            occurrence=occurrence,
            workflow=WorkflowKind.REGISTRATION,
        )
        submit_journey(journey=journey, actor=self.user)
        request = create_request(journey=journey, requester=self.user, message="Merci")

        pending = self.client.get(reverse("account:journey-detail", args=[journey.pk]))
        self.assertContains(pending, "En attente de validation")

        reject_request(request=request, actor=self.decider, comment="ADMIN ONLY: risque interne")
        journey.refresh_from_db()
        rejected = self.client.get(reverse("account:journey-detail", args=[journey.pk]))
        self.assertContains(rejected, "Demande refusée")
        self.assertNotContains(rejected, "ADMIN ONLY")
        self.assertNotContains(rejected, "risque interne")

    def test_participant_selectors_and_urls_enforce_ownership(self):
        _, _, _, own_journey, own_order, own_access = self._free_registration(title="Mon atelier")
        _, _, _, other_journey, other_order, other_access = self._free_registration(
            user=self.other,
            title="Atelier privé",
        )

        self.assertEqual(list(participant_journeys(self.user)), [own_journey])
        self.assertEqual(list(participant_accesses(self.user)), [own_access])
        self.assertEqual(list(participant_orders(self.user)), [own_order])

        self.assertEqual(
            self.client.get(reverse("account:journey-detail", args=[other_journey.pk])).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse("account:access-detail", args=[other_access.pk])).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse("payments:commerce-start", args=[other_order.pk])).status_code,
            404,
        )

    def test_event_access_is_contextualized_as_ticket_without_ticket_model(self):
        start = timezone.now() + timedelta(days=5)
        event = Event.objects.create(
            organizer=self.user,
            title="Event canonique sans Ticket",
            status=EventStatus.PUBLISHED,
            visibility=EventVisibility.PUBLIC,
            start_at=start,
            end_at=start + timedelta(hours=3),
            timezone="Africa/Lubumbashi",
            published_at=timezone.now(),
        )
        journey = create_journey(
            initiated_by=self.user,
            beneficiary=self.user,
            activity=event.activity,
            occurrence=event.primary_occurrence,
            workflow=WorkflowKind.PURCHASE,
        )
        offer = self._offer(
            event.activity,
            event.primary_occurrence,
            name="Pass canonique",
            price="0.00",
            mode=PaymentMode.NONE,
        )
        order = create_order(journey=journey, buyer=self.user, selections=[(offer, 1)])
        confirm_order(order=order, actor=self.user)
        access = issue_access(
            beneficiary=self.user,
            activity=event.activity,
            occurrence=event.primary_occurrence,
            journey=journey,
            source_key="event-canonical",
        )

        self.assertEqual(Ticket.objects.count(), 0)
        self.assertEqual(TicketOrder.objects.count(), 0)
        presentation = access_presentation(access)
        self.assertEqual(presentation["noun"], "Billet")
        self.assertEqual(presentation["offer_label"], "Pass canonique")
        response = self.client.get(reverse("account:access-detail", args=[access.pk]))
        self.assertContains(response, "Billet")
        self.assertContains(response, "Type de billet")
        self.assertContains(response, "Pass canonique")

    def test_on_site_reservation_is_not_presented_as_unpaid(self):
        activity, occurrence, _ = self._activity("Réservation sur place")
        journey = create_journey(
            initiated_by=self.user,
            beneficiary=self.user,
            activity=activity,
            occurrence=occurrence,
            workflow=WorkflowKind.RESERVATION,
        )
        submit_journey(journey=journey, actor=self.user)
        offer = self._offer(
            activity,
            occurrence,
            name="Réservation",
            price="15.00",
            mode=PaymentMode.ON_SITE,
        )
        order = create_order(journey=journey, buyer=self.user, selections=[(offer, 1)])
        confirm_order(order=order, actor=self.user)
        issue_access(
            beneficiary=self.user,
            activity=activity,
            occurrence=occurrence,
            journey=journey,
            source_key="reservation",
        )

        response = self.client.get(reverse("account:journey-detail", args=[journey.pk]))
        self.assertContains(response, "À payer sur place")
        self.assertNotContains(response, "Impayé")
        self.assertEqual(Payment.objects.count(), 0)

    def test_invitation_can_be_accepted_by_beneficiary_and_issues_access(self):
        activity, occurrence, _ = self._activity("Invitation canonique")
        invitation = create_journey(
            initiated_by=self.decider,
            beneficiary=self.user,
            activity=activity,
            occurrence=occurrence,
            workflow=WorkflowKind.INVITATION,
            status=JourneyStatus.APPROVED,
        )
        detail = self.client.get(reverse("account:journey-detail", args=[invitation.pk]))
        self.assertContains(detail, "Invitation à accepter")
        self.assertContains(detail, "Accepter l’invitation")

        response = self.client.post(reverse("account:invitation-accept", args=[invitation.pk]))
        self.assertEqual(response.status_code, 302)
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, JourneyStatus.CONFIRMED)
        access = invitation.accesses.get(beneficiary=self.user)
        self.assertEqual(access.status, AccessStatus.VALID)
        self.assertEqual(response.url, reverse("account:access-detail", args=[access.pk]))

    def test_notification_open_prefers_canonical_journey_destination(self):
        _, _, _, journey, _, _ = self._free_registration(title="Destination notification")
        notification = Notification.objects.create(
            recipient=self.user,
            kind=NotificationKind.SYSTEM,
            category=NotificationCategory.SYSTEM,
            title="Mise à jour",
            message="Votre démarche a changé.",
            action_url="/events/ancienne-destination/",
            journey=journey,
        )
        response = self.client.get(reverse("notifications:open", args=[notification.pk]))
        self.assertRedirects(
            response,
            reverse("account:journey-detail", args=[journey.pk]),
            fetch_redirect_response=False,
        )
        notification.refresh_from_db()
        self.assertIsNotNone(notification.read_at)

    def test_status_and_next_action_labels_are_centralized_and_french(self):
        activity, occurrence, _ = self._activity("Achat à payer")
        journey = create_journey(
            initiated_by=self.user,
            beneficiary=self.user,
            activity=activity,
            occurrence=occurrence,
            workflow=WorkflowKind.PURCHASE,
        )
        offer = self._offer(
            activity,
            occurrence,
            name="Participation",
            price="10.00",
            mode=PaymentMode.UPFRONT,
        )
        order = create_order(journey=journey, buyer=self.user, selections=[(offer, 1)])
        journey.refresh_from_db()
        presentation = journey_presentation(participant_journeys(self.user).get(pk=journey.pk))
        self.assertEqual(presentation["status_label"], "Paiement requis")
        self.assertEqual(presentation["next_action"]["label"], "Payer")
        self.assertEqual(
            presentation["next_action"]["url"],
            reverse("payments:commerce-start", args=[order.pk]),
        )

    def test_non_event_commerce_payment_uses_canonical_payment_service(self):
        activity, occurrence, _ = self._activity("Achat Commerce")
        journey = create_journey(
            initiated_by=self.user,
            beneficiary=self.user,
            activity=activity,
            occurrence=occurrence,
            workflow=WorkflowKind.PURCHASE,
        )
        offer = self._offer(
            activity,
            occurrence,
            name="Accès payant",
            price="12.00",
            mode=PaymentMode.UPFRONT,
        )
        order = create_order(journey=journey, buyer=self.user, selections=[(offer, 1)])

        start = self.client.get(reverse("payments:commerce-start", args=[order.pk]))
        self.assertEqual(start.status_code, 200)
        self.assertContains(start, "12.00 USD")
        response = self.client.post(
            reverse("payments:commerce-start", args=[order.pk]),
            {
                "provider": "sandbox",
                "method": "card",
                "payer_name": "Participant",
                "payer_email": self.user.email,
                "payer_phone": "",
                "idempotency_key": "participant-commerce-payment",
            },
        )
        self.assertEqual(response.status_code, 302)
        payment = Payment.objects.get()
        self.assertIsNone(payment.order_id)
        self.assertEqual(payment.commerce_order_id, order.pk)

        complete = self.client.post(reverse("payments:sandbox-complete", args=[payment.pk]), follow=True)
        self.assertEqual(complete.status_code, 200)
        self.assertContains(complete, "Paiement confirmé.")
        payment.refresh_from_db()
        journey.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.SUCCEEDED)
        self.assertEqual(journey.status, JourneyStatus.CONFIRMED)
