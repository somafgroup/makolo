import importlib
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.apps import apps
from django.conf import settings
from django.core.management import BaseCommand, CommandError, call_command

from access.services import issue_access
from accounts.models import NotificationPreference, User, UserProfile
from activities.models import (
    Activity,
    ActivityStatus,
    Occurrence,
    OccurrencePlace,
    OccurrencePlaceRole,
    OccurrenceStatus,
)
from authorization.services import ensure_platform_admin_mandate
from commerce.models import Offer, OfferStatus, PaymentMode
from commerce.services import confirm_order as confirm_commerce_order
from commerce.services import create_order as create_commerce_order
from events.activity_bridge import sync_event_core
from events.models import Event, EventCategory, EventStatus, EventVenue, EventVisibility, VenueKind
from geography.models import Place
from journeys.models import JourneyStatus, WorkflowKind
from journeys.services import create_journey, submit_journey
from operations.models import IncidentCategory, IncidentSeverity, IncidentStatus, OperationsIncident
from organizations.models import Organization, OrganizationMembership, OrganizationRole, OrganizationVerificationStatus
from scanner.models import EventAccessGate, ScannerAssignment
from tickets.services import configure_ticket_type, create_order as create_ticket_order

E2E_PASSWORD = "Makolo-E2E-2026!"
TZ = ZoneInfo("Africa/Lubumbashi")


class Command(BaseCommand):
    help = "Reset and prepare deterministic browser fixtures for DJANGO_ENV=e2e."

    def handle(self, *args, **options):
        if not getattr(settings, "IS_E2E", False):
            raise CommandError("prepare_e2e est réservé à DJANGO_ENV=e2e.")
        call_command("flush", interactive=False, verbosity=0)

        authority_seed = importlib.import_module("authorization.migrations.0002_seed_roles_and_backfill")
        authority_seed.seed_and_backfill(apps, None)
        group_authority_seed = importlib.import_module("authorization.migrations.0003_group_scope")
        group_authority_seed.seed_group_authority(apps, None)
        geography_authority_seed = importlib.import_module("authorization.migrations.0004_space_places_permissions")
        geography_authority_seed.seed_space_place_permissions(apps, None)
        activity_permission_seed = importlib.import_module("authorization.migrations.0006_activity_permissions")
        activity_permission_seed.migrate_activity_permissions(apps, None)
        activity_role_seed = importlib.import_module("authorization.migrations.0007_activity_roles")
        activity_role_seed.migrate_activity_roles(apps, None)

        users = {
            key: self._user(email, username, **flags)
            for key, email, username, flags in [
                ("participant", "participant@e2e.makolo.test", "e2e-participant", {}),
                ("empty", "empty.participant@e2e.makolo.test", "e2e-empty", {}),
                ("visual", "visual.participant@e2e.makolo.test", "e2e-visual", {}),
                ("profile", "profile.user@e2e.makolo.test", "e2e-profile", {}),
                ("reset", "reset.user@e2e.makolo.test", "e2e-reset", {}),
                ("password", "password.user@e2e.makolo.test", "e2e-password", {}),
                ("delete", "delete.me@e2e.makolo.test", "e2e-delete", {}),
                ("sole_owner", "sole.owner@e2e.makolo.test", "e2e-sole-owner", {}),
                ("owner", "owner@e2e.makolo.test", "e2e-owner", {"is_organizer": True}),
                ("event_manager", "event.manager@e2e.makolo.test", "e2e-event-manager", {}),
                ("finance", "finance@e2e.makolo.test", "e2e-finance", {}),
                ("marketing", "marketing@e2e.makolo.test", "e2e-marketing", {}),
                ("scanner", "scanner@e2e.makolo.test", "e2e-scanner", {"is_scanner_agent": True}),
                ("multi", "multi.role@e2e.makolo.test", "e2e-multi", {}),
                ("new_organizer", "new.organizer@e2e.makolo.test", "e2e-new-organizer", {"is_organizer": True}),
                ("staff", "staff@e2e.makolo.test", "e2e-staff", {"is_staff": True}),
            ]
        }
        ensure_platform_admin_mandate(profile=users["staff"], source="e2e-fixture")

        main_org = Organization.objects.create(name="Makolo E2E Events", description="Organisation déterministe pour les parcours navigateur Makolo.", city="Lubumbashi", country="RDC", public_profile=True, verification_status=OrganizationVerificationStatus.VERIFIED, created_by=users["owner"])
        self._membership(main_org, users["owner"], OrganizationRole.OWNER)
        self._membership(main_org, users["event_manager"], OrganizationRole.EVENT_MANAGER)
        self._membership(main_org, users["finance"], OrganizationRole.FINANCE)
        self._membership(main_org, users["marketing"], OrganizationRole.MARKETING)
        self._membership(main_org, users["multi"], OrganizationRole.EVENT_MANAGER)

        finance_org = Organization.objects.create(name="Makolo E2E Finance", public_profile=False, verification_status=OrganizationVerificationStatus.VERIFIED, created_by=users["owner"])
        self._membership(finance_org, users["owner"], OrganizationRole.OWNER)
        self._membership(finance_org, users["multi"], OrganizationRole.FINANCE)
        empty_org = Organization.objects.create(name="Makolo E2E Nouvelle Organisation", description="Organisation sans événement pour tester les états vides.", public_profile=True, verification_status=OrganizationVerificationStatus.VERIFIED, created_by=users["new_organizer"])
        self._membership(empty_org, users["new_organizer"], OrganizationRole.OWNER)
        sole_org = Organization.objects.create(name="Makolo E2E Propriétaire Unique", public_profile=False, verification_status=OrganizationVerificationStatus.VERIFIED, created_by=users["sole_owner"])
        self._membership(sole_org, users["sole_owner"], OrganizationRole.OWNER)

        category = EventCategory.objects.create(name="Culture E2E", description="Catégorie stable pour les tests Playwright.")
        venue_place = Place.objects.create(name="Centre Makolo E2E", address_line="1 avenue des Tests", locality="Lubumbashi", country_code="CD", timezone="Africa/Lubumbashi", created_by=users["owner"])
        venue = EventVenue.objects.create(name="Centre Makolo E2E", kind=VenueKind.PHYSICAL, place=venue_place, address="1 avenue des Tests", city="Lubumbashi", country="RDC")

        paid_event = Event.objects.create(
            organizer=users["owner"], organization=main_org, category=category, venue=venue,
            title="Festival Makolo E2E", short_description="Le parcours critique de billetterie Makolo.",
            description="Événement public stable destiné aux tests de découverte, paiement et contrôle d’accès.",
            status=EventStatus.PUBLISHED, visibility=EventVisibility.PUBLIC,
            start_at=self._dt(2030, 6, 15, 18, 0), end_at=self._dt(2030, 6, 15, 23, 0),
            registration_start_at=self._dt(2026, 1, 1, 0, 0), registration_end_at=self._dt(2030, 6, 15, 17, 0),
            timezone="Africa/Lubumbashi", capacity=200, published_at=self._dt(2026, 1, 1, 0, 0), metadata={"source": "makolo-e2e"},
        )
        sync_event_core(paid_event)
        paid_type = configure_ticket_type(
            actor=users["owner"], event=paid_event, name="Pass standard E2E",
            description="Billet payant du scénario de bout en bout.", price="12.00", currency="USD",
            quantity_total=100, min_per_order=1, max_per_order=4, is_active=True, is_public=True,
        )

        visual_event = Event.objects.create(
            organizer=users["owner"], organization=main_org, category=category, venue=venue,
            title="Atelier Makolo Visuel", short_description="Événement stable pour les captures de régression visuelle.",
            description="Un événement gratuit avec un billet déterministe pour les snapshots.", status=EventStatus.PUBLISHED,
            visibility=EventVisibility.PUBLIC, start_at=self._dt(2030, 7, 10, 9, 0), end_at=self._dt(2030, 7, 10, 12, 0),
            registration_start_at=self._dt(2026, 1, 1, 0, 0), registration_end_at=self._dt(2030, 7, 10, 8, 0),
            timezone="Africa/Lubumbashi", capacity=80, published_at=self._dt(2026, 1, 1, 0, 0), metadata={"source": "makolo-e2e"},
        )
        sync_event_core(visual_event)
        visual_type = configure_ticket_type(
            actor=users["owner"], event=visual_event, name="Invitation E2E", price="0.00", currency="USD",
            quantity_total=40, min_per_order=1, max_per_order=2, is_active=True, is_public=True,
        )
        create_ticket_order(buyer=users["visual"], event=visual_event, customer_name="Visual Participant", customer_email=users["visual"].email, selections=[(visual_type, 1)])

        sold_out_event = Event.objects.create(
            organizer=users["owner"], organization=main_org, category=category, venue=venue,
            title="Capacité Makolo E2E", slug="capacite-makolo-e2e", short_description="Événement à une seule place pour valider le sold-out canonique.",
            description="Fixture Capacity déterministe pour vérifier la consommation et l’indisponibilité après réservation.",
            status=EventStatus.PUBLISHED, visibility=EventVisibility.UNLISTED,
            start_at=self._dt(2030, 8, 5, 10, 0), end_at=self._dt(2030, 8, 5, 12, 0),
            registration_start_at=self._dt(2026, 1, 1, 0, 0), registration_end_at=self._dt(2030, 8, 5, 9, 0),
            timezone="Africa/Lubumbashi", capacity=1, published_at=self._dt(2026, 1, 1, 0, 0), metadata={"source": "makolo-e2e", "purpose": "capacity"},
        )
        sync_event_core(sold_out_event)
        configure_ticket_type(
            actor=users["owner"], event=sold_out_event, name="Place unique E2E",
            description="Une seule place gratuite.", price="0.00", currency="USD",
            quantity_total=1, min_per_order=1, max_per_order=1, is_active=True, is_public=True,
        )

        # Canonical non-Event registration: Activity -> Occurrence -> Journey -> Access.
        non_event_place = Place.objects.create(
            name="Maison Makolo E2E",
            address_line="24 boulevard Canonique",
            locality="Kinshasa",
            country_code="CD",
            timezone="Africa/Lubumbashi",
            access_instructions="Présentez votre confirmation à l’accueil.",
            created_by=users["owner"],
        )
        non_event_activity = Activity.objects.create(
            space=main_org,
            created_by=users["owner"],
            title="Atelier citoyen Makolo E2E",
            short_description="Inscription gratuite sans Event, Ticket ni TicketOrder.",
            status=ActivityStatus.PUBLISHED,
        )
        non_event_occurrence = Occurrence.objects.create(
            activity=non_event_activity,
            label="Session Kinshasa",
            start_at=self._dt(2030, 6, 20, 14, 0),
            end_at=self._dt(2030, 6, 20, 16, 0),
            timezone="Africa/Lubumbashi",
            status=OccurrenceStatus.SCHEDULED,
        )
        OccurrencePlace.objects.create(
            occurrence=non_event_occurrence,
            place=non_event_place,
            role=OccurrencePlaceRole.PRIMARY,
        )
        registration = create_journey(
            initiated_by=users["participant"],
            beneficiary=users["participant"],
            activity=non_event_activity,
            occurrence=non_event_occurrence,
            workflow=WorkflowKind.REGISTRATION,
        )
        submit_journey(journey=registration, actor=users["participant"])
        free_offer = Offer.objects.create(
            activity=non_event_activity,
            occurrence=non_event_occurrence,
            name="Inscription gratuite",
            unit_price=Decimal("0.00"),
            currency="USD",
            payment_mode=PaymentMode.NONE,
            status=OfferStatus.ACTIVE,
            source_key="e2e:non-event-registration",
        )
        free_order = create_commerce_order(
            journey=registration,
            buyer=users["participant"],
            selections=[(free_offer, 1)],
            source_key="e2e:non-event-registration-order",
        )
        confirm_commerce_order(order=free_order, actor=users["participant"])
        non_event_access = issue_access(
            beneficiary=users["participant"],
            activity=non_event_activity,
            occurrence=non_event_occurrence,
            journey=registration,
            source_key="e2e:non-event-registration-access",
        )

        # Canonical on-site reservation: Commerce exists, provider Payment does not.
        reservation_activity = Activity.objects.create(
            space=main_org,
            created_by=users["owner"],
            title="Réservation Makolo E2E",
            status=ActivityStatus.PUBLISHED,
        )
        reservation_occurrence = Occurrence.objects.create(
            activity=reservation_activity,
            start_at=self._dt(2030, 7, 2, 10, 0),
            end_at=self._dt(2030, 7, 2, 11, 30),
            timezone="Africa/Lubumbashi",
            status=OccurrenceStatus.SCHEDULED,
        )
        OccurrencePlace.objects.create(
            occurrence=reservation_occurrence,
            place=venue_place,
            role=OccurrencePlaceRole.PRIMARY,
        )
        reservation = create_journey(
            initiated_by=users["profile"], beneficiary=users["profile"],
            activity=reservation_activity, occurrence=reservation_occurrence,
            workflow=WorkflowKind.RESERVATION,
        )
        submit_journey(journey=reservation, actor=users["profile"])
        onsite_offer = Offer.objects.create(
            activity=reservation_activity,
            occurrence=reservation_occurrence,
            name="Réservation sur place",
            unit_price=Decimal("5.00"),
            currency="USD",
            payment_mode=PaymentMode.ON_SITE,
            status=OfferStatus.ACTIVE,
            source_key="e2e:on-site-reservation",
        )
        onsite_order = create_commerce_order(
            journey=reservation,
            buyer=users["profile"],
            selections=[(onsite_offer, 1)],
            source_key="e2e:on-site-reservation-order",
        )
        confirm_commerce_order(order=onsite_order, actor=users["profile"])
        issue_access(
            beneficiary=users["profile"], activity=reservation_activity,
            occurrence=reservation_occurrence, journey=reservation,
            source_key="e2e:on-site-reservation-access",
        )

        # Invitation awaits the participant's response; Access is issued on acceptance.
        invitation_activity = Activity.objects.create(
            space=main_org,
            created_by=users["owner"],
            title="Invitation Makolo E2E",
            status=ActivityStatus.PUBLISHED,
        )
        invitation_occurrence = Occurrence.objects.create(
            activity=invitation_activity,
            start_at=self._dt(2030, 7, 5, 17, 0),
            end_at=self._dt(2030, 7, 5, 19, 0),
            timezone="Africa/Lubumbashi",
            status=OccurrenceStatus.SCHEDULED,
        )
        OccurrencePlace.objects.create(
            occurrence=invitation_occurrence,
            place=venue_place,
            role=OccurrencePlaceRole.PRIMARY,
        )
        create_journey(
            initiated_by=users["owner"],
            beneficiary=users["participant"],
            activity=invitation_activity,
            occurrence=invitation_occurrence,
            workflow=WorkflowKind.INVITATION,
            status=JourneyStatus.APPROVED,
        )

        gate = EventAccessGate.objects.create(event=paid_event, name="Entrée E2E", description="Porte du scénario QR end-to-end.", priority=1, created_by=users["owner"])
        ScannerAssignment.objects.create(event=paid_event, agent=users["scanner"], assigned_by=users["owner"], access_gate=gate, label="Contrôle E2E", is_active=True)
        OperationsIncident.objects.create(title="Incident démo E2E à ignorer", category=IncidentCategory.PAYMENT, severity=IncidentSeverity.CRITICAL, status=IncidentStatus.OPEN, description="Incident marqué démo qui ne doit pas dégrader le health réel.", opened_by=users["staff"], metadata={"seed": "makolo-demo", "source": "e2e"})
        OperationsIncident.objects.create(title="Incident réel E2E visible", category=IncidentCategory.ACCESS, severity=IncidentSeverity.CRITICAL, status=IncidentStatus.OPEN, description="Incident opérationnel réel attendu dans le navigateur staff.", opened_by=users["staff"], event=paid_event, organization=main_org, metadata={"source": "makolo-e2e"})

        self.stdout.write(self.style.SUCCESS("Makolo E2E fixtures prepared."))
        self.stdout.write(f"Password: {E2E_PASSWORD}")
        self.stdout.write(f"Paid event: {paid_event.slug}")
        self.stdout.write(f"Paid ticket type: {paid_type.pk}")
        self.stdout.write(f"Non-Event activity: {non_event_activity.slug}")
        self.stdout.write(f"Non-Event access: {non_event_access.pk}")

    def _user(self, email, username, **flags):
        user = User.objects.create_user(email=email, username=username, password=E2E_PASSWORD, first_name=username.replace("e2e-", "").replace("-", " ").title(), **flags)
        UserProfile.objects.get_or_create(user=user)
        NotificationPreference.objects.get_or_create(user=user)
        return user

    def _membership(self, organization, user, role):
        return OrganizationMembership.objects.create(organization=organization, user=user, role=role, is_active=True)

    def _dt(self, year, month, day, hour, minute):
        return datetime(year, month, day, hour, minute, tzinfo=TZ)
