from io import BytesIO

import qrcode
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.views import View
from django.views.generic import TemplateView

from access.models import AccessStatus

from .participant_presentation import (
    access_presentation,
    active_credential,
    journey_presentation,
)
from .participant_selectors import participant_accesses, participant_journeys


class ParticipantJourneyListView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/journey_list.html"
    login_url = "core:login"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        rows = [journey_presentation(journey) for journey in participant_journeys(self.request.user)]
        context["active_journeys"] = [row for row in rows if not row["object"].is_terminal]
        context["journey_history"] = [row for row in rows if row["object"].is_terminal]
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


class ParticipantAccessListView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/access_list.html"
    login_url = "core:login"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        rows = [access_presentation(access) for access in participant_accesses(self.request.user)]
        context["active_accesses"] = [
            row for row in rows if row["object"].status in {AccessStatus.PENDING, AccessStatus.VALID}
        ]
        context["access_history"] = [
            row for row in rows if row["object"].status not in {AccessStatus.PENDING, AccessStatus.VALID}
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
