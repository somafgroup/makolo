from io import BytesIO

import qrcode
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from access.models import AccessStatus
from notifications.selectors import get_notifications_for_user

from .participant_presentation import (
    access_presentation,
    active_credential,
    journey_presentation,
    notification_participant_url,
    occurrence_presentation,
)
from .participant_selectors import (
    participant_access_history,
    participant_accesses,
    participant_actionable_journeys,
    participant_active_accesses,
    participant_active_journeys,
    participant_history_journeys,
    participant_journeys,
    participant_upcoming_occurrences,
)
from .participant_services import (
    accept_participant_invitation,
    decline_participant_invitation,
)


def participant_home_context(user):
    actionable = [
        journey_presentation(journey)
        for journey in participant_actionable_journeys(user)[:5]
    ]
    upcoming = [
        occurrence_presentation(activity=occurrence.activity, occurrence=occurrence)
        for occurrence in participant_upcoming_occurrences(user)[:4]
    ]
    accesses = [
        access_presentation(access)
        for access in participant_active_accesses(user)[:4]
    ]
    recent = [
        journey_presentation(journey)
        for journey in participant_active_journeys(user).order_by("-updated_at", "id")[:5]
    ]
    history = [
        journey_presentation(journey)
        for journey in participant_history_journeys(user)[:4]
    ]
    notifications = list(
        get_notifications_for_user(user)
        .select_related("journey", "access", "commerce_order", "commerce_order__journey")[:5]
    )
    notification_rows = [
        {
            "object": notification,
            "participant_url": notification_participant_url(notification),
            "open_url": reverse("notifications:open", kwargs={"pk": notification.pk}),
        }
        for notification in notifications
    ]
    return {
        "participant_actionables": actionable,
        "participant_upcoming": upcoming,
        "participant_accesses": accesses,
        "participant_recent": recent,
        "participant_history": history,
        "participant_notifications": notification_rows,
        "participant_has_content": bool(actionable or upcoming or accesses or recent or history),
    }


class ParticipantHomeView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/home.html"
    login_url = "core:login"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(participant_home_context(self.request.user))
        return context


class ParticipantJourneyListView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/journey_list.html"
    login_url = "core:login"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_journeys"] = [
            journey_presentation(journey)
            for journey in participant_active_journeys(self.request.user)
        ]
        context["journey_history"] = [
            journey_presentation(journey)
            for journey in participant_history_journeys(self.request.user)
        ]
        return context


class ParticipantJourneyDetailView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/journey_detail.html"
    login_url = "core:login"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        journey = get_object_or_404(participant_journeys(self.request.user), pk=kwargs["pk"])
        context["journey"] = journey
        context["presentation"] = journey_presentation(journey)
        return context


class ParticipantInvitationAcceptView(LoginRequiredMixin, View):
    login_url = "core:login"

    def post(self, request, pk):
        journey = get_object_or_404(participant_journeys(request.user), pk=pk)
        try:
            journey, access = accept_participant_invitation(journey=journey, actor=request.user)
        except PermissionDenied:
            raise
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
            return redirect("account:journey-detail", pk=journey.pk)
        messages.success(request, "Invitation acceptée. Votre accès est disponible.")
        return redirect("account:access-detail", pk=access.pk)


class ParticipantInvitationDeclineView(LoginRequiredMixin, View):
    login_url = "core:login"

    def post(self, request, pk):
        journey = get_object_or_404(participant_journeys(request.user), pk=pk)
        try:
            decline_participant_invitation(journey=journey, actor=request.user)
        except PermissionDenied:
            raise
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            messages.success(request, "Invitation refusée.")
        return redirect("account:journey-detail", pk=journey.pk)


class ParticipantAccessListView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/access_list.html"
    login_url = "core:login"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_accesses"] = [
            access_presentation(access)
            for access in participant_active_accesses(self.request.user)
        ]
        context["access_history"] = [
            access_presentation(access)
            for access in participant_access_history(self.request.user)
        ]
        return context


class ParticipantAccessDetailView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/access_detail.html"
    login_url = "core:login"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        access = get_object_or_404(participant_accesses(self.request.user), pk=kwargs["pk"])
        context["access"] = access
        context["presentation"] = access_presentation(access)
        return context


class ParticipantAccessQrView(LoginRequiredMixin, View):
    """Render the current canonical credential without exposing its signed payload."""

    login_url = "core:login"

    def get(self, request, pk):
        access = get_object_or_404(participant_accesses(request.user), pk=pk)
        if access.status != AccessStatus.VALID:
            raise Http404("Cet accès ne possède pas de QR utilisable.")
        credential = active_credential(access)
        if credential is None:
            raise Http404("Aucun QR actif n’est disponible pour cet accès.")

        from access.services import render_access_credential

        image = qrcode.make(render_access_credential(credential))
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        response = HttpResponse(buffer.getvalue(), content_type="image/png")
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response
