from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView
from django.db.models import Q
from django.shortcuts import redirect
from django.utils import timezone
from django.views.generic import TemplateView

from access.models import AccessStatus
from accounts.participant_views import participant_home_context
from events.models import Event, EventStatus
from events.selectors import get_public_discoverable_events
from organizations.models import Organization, OrganizationVerificationStatus
from payments.models import PaymentStatus
from payments.selectors import get_payments_visible_to
from tickets.models import TicketOrderStatus, TicketStatus
from tickets.selectors import get_orders_visible_to, get_tickets_visible_to

from .capabilities import get_web_capabilities
from .web_throttling import (
    RATE_LIMIT_MESSAGE,
    allow_web_request,
    client_rate_identity,
    value_rate_identity,
)


class RateLimitedLoginView(LoginView):
    template_name = "auth/login.html"
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        username = request.POST.get("username", "")
        account_allowed = allow_web_request(
            request,
            scope="login-account",
            limit=10,
            window_seconds=60,
            identities=[value_rate_identity("account", username)],
        )
        ip_allowed = allow_web_request(
            request,
            scope="login-ip",
            limit=60,
            window_seconds=60,
            identities=[client_rate_identity(request)],
        )
        if not account_allowed or not ip_allowed:
            form = self.get_form()
            form.add_error(None, RATE_LIMIT_MESSAGE)
            response = self.form_invalid(form)
            response.status_code = 429
            return response
        return super().post(request, *args, **kwargs)


class PublicHomeView(TemplateView):
    template_name = "core/public_home.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("core:dashboard")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["featured_events"] = get_public_discoverable_events().order_by("start_at")[:6]
        context["public_organizations"] = (
            Organization.objects.filter(public_profile=True)
            .exclude(verification_status=OrganizationVerificationStatus.SUSPENDED)
            .order_by("name")[:6]
        )
        return context


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "base/dashboard.html"
    login_url = "core:login"

    def _organization_events(self, user):
        queryset = Event.objects.select_related(
            "activity",
            "activity__created_by",
            "activity__space",
            "category",
            "venue",
            "venue__place",
        )
        if user.is_staff:
            return queryset
        return queryset.filter(
            Q(activity__created_by=user)
            | Q(
                activity__space__memberships__user=user,
                activity__space__memberships__is_active=True,
            )
        ).distinct()

    def get_event_queryset(self):
        """Compatibility seam for dashboard authorization tests and callers."""
        return self._organization_events(self.request.user)

    @staticmethod
    def _valid_ticket_filter():
        return Q(access__status=AccessStatus.VALID) | Q(
            access__isnull=True,
            status=TicketStatus.VALID,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        capabilities = get_web_capabilities(user)
        now = timezone.now()

        if user.is_staff:
            dashboard_mode = "staff"
        elif capabilities["has_organizer_tools"]:
            dashboard_mode = "organizer"
        else:
            dashboard_mode = "participant"

        context.update(
            {
                "dashboard_mode": dashboard_mode,
                "web_capabilities": capabilities,
            }
        )

        if dashboard_mode == "participant":
            context.update(participant_home_context(user))
            return context

        events = self.get_event_queryset()
        tickets = get_tickets_visible_to(user)
        orders = get_orders_visible_to(user)
        payments = get_payments_visible_to(user)

        context.update(
            {
                "events_count": events.count(),
                "published_events_count": events.filter(activity__status=EventStatus.PUBLISHED).count(),
                "upcoming_events_count": events.filter(activity__occurrences__start_at__gt=now).distinct().count(),
                "upcoming_events": events.filter(
                    activity__occurrences__start_at__gt=now
                ).order_by("activity__occurrences__start_at").distinct()[:5],
                "tickets_count": tickets.count(),
                "valid_tickets_count": tickets.filter(self._valid_ticket_filter()).count(),
                "pending_orders_count": orders.filter(status=TicketOrderStatus.PENDING).count(),
                "confirmed_orders_count": orders.filter(status=TicketOrderStatus.CONFIRMED).count(),
                "payments_count": payments.count(),
                "pending_payments_count": payments.filter(status=PaymentStatus.PENDING).count(),
                "succeeded_payments_count": payments.filter(status=PaymentStatus.SUCCEEDED).count(),
                "refunded_payments_count": payments.filter(status=PaymentStatus.REFUNDED).count(),
                "can_create_event": capabilities["can_manage_events"],
            }
        )
        return context
