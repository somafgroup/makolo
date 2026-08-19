import uuid

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView, ListView

from accounts.participant_selectors import participant_orders
from commerce.models import CommerceOrderStatus, PaymentMode
from journeys.models import WorkflowKind
from tickets.models import TicketOrderStatus
from tickets.selectors import get_orders_visible_to

from .forms import ManualPaymentCompleteForm, PaymentStartForm, RefundForm
from .models import PaymentProvider
from .permissions import user_can_manage_payment
from .selectors import get_payments_visible_to
from .services import (
    cancel_payment,
    complete_manual_payment,
    complete_sandbox_payment,
    initiate_commerce_payment,
    initiate_payment,
    refund_payment,
)


ONLINE_PAYMENT_MODES = {PaymentMode.UPFRONT, PaymentMode.AFTER_APPROVAL}


def _journey_for_payment(payment):
    if payment.commerce_order_id:
        return payment.commerce_order.journey
    if payment.order_id:
        return getattr(payment.order, "journey", None)
    return None


def _payment_success_message(payment):
    journey = _journey_for_payment(payment)
    if journey is None:
        return "Paiement confirmé."
    try:
        journey.activity.event_vertical
        return "Paiement confirmé. Votre billet est disponible."
    except ObjectDoesNotExist:
        pass
    if journey.workflow == WorkflowKind.REGISTRATION:
        return "Paiement confirmé. Votre inscription est confirmée."
    if journey.workflow == WorkflowKind.RESERVATION:
        return "Paiement confirmé. Votre réservation est confirmée."
    if journey.workflow == WorkflowKind.INVITATION:
        return "Paiement confirmé. Votre invitation est confirmée."
    return "Paiement confirmé. Votre démarche est confirmée."


class PaymentListView(LoginRequiredMixin, ListView):
    template_name = "payments/payment_list.html"
    context_object_name = "payments"
    paginate_by = 20
    login_url = "core:login"

    def get_queryset(self):
        return get_payments_visible_to(self.request.user)


class PaymentDetailView(LoginRequiredMixin, DetailView):
    template_name = "payments/payment_detail.html"
    context_object_name = "payment"
    login_url = "core:login"

    def get_queryset(self):
        return get_payments_visible_to(self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["can_manage_payment"] = user_can_manage_payment(self.request.user, self.object)
        context["sandbox_enabled"] = self.object.provider == PaymentProvider.SANDBOX
        context["refund_form"] = RefundForm()
        context["manual_form"] = ManualPaymentCompleteForm()
        journey = _journey_for_payment(self.object)
        context["participant_journey"] = journey
        context["participant_journey_url"] = (
            reverse("account:journey-detail", kwargs={"pk": journey.pk})
            if journey and journey.beneficiary_id == self.request.user.pk
            else ""
        )
        return context


class PaymentStartView(LoginRequiredMixin, View):
    """Compatibility endpoint for current Event TicketOrder consumers."""

    template_name = "payments/payment_start.html"
    login_url = "core:login"

    def _order(self, request, order_pk):
        return get_object_or_404(get_orders_visible_to(request.user), pk=order_pk)

    def _context(self, request, order, form, idempotency_key):
        journey = getattr(order, "journey", None)
        return {
            "order": order,
            "form": form,
            "idempotency_key": idempotency_key,
            "participant_journey_url": reverse("account:journey-detail", kwargs={"pk": journey.pk})
            if journey and journey.beneficiary_id == request.user.pk
            else "",
        }

    def get(self, request, order_pk):
        order = self._order(request, order_pk)
        if order.status != TicketOrderStatus.PENDING or order.total_amount <= 0:
            raise Http404("Cette commande n’est pas en attente d’un paiement.")
        form = PaymentStartForm(order=order, user=request.user)
        return render(request, self.template_name, self._context(request, order, form, uuid.uuid4().hex))

    def post(self, request, order_pk):
        order = self._order(request, order_pk)
        form = PaymentStartForm(request.POST, order=order, user=request.user)
        if form.is_valid():
            try:
                payment = initiate_payment(
                    order=order,
                    actor=request.user,
                    provider=form.cleaned_data["provider"],
                    method=form.cleaned_data["method"],
                    payer_name=form.cleaned_data.get("payer_name", ""),
                    payer_email=form.cleaned_data.get("payer_email", ""),
                    payer_phone=form.cleaned_data.get("payer_phone", ""),
                    idempotency_key=request.POST.get("idempotency_key") or None,
                )
            except (PermissionDenied, ValidationError) as exc:
                messages.error(request, "; ".join(getattr(exc, "messages", [str(exc)])))
            else:
                messages.success(request, "Paiement initialisé.")
                return redirect("payments:detail", pk=payment.pk)
        return render(
            request,
            self.template_name,
            self._context(
                request,
                order,
                form,
                request.POST.get("idempotency_key") or uuid.uuid4().hex,
            ),
            status=400,
        )


class CommercePaymentStartView(LoginRequiredMixin, View):
    """Participant checkout entry point sourced exclusively from CommerceOrder."""

    template_name = "payments/payment_start.html"
    login_url = "core:login"

    def _order(self, request, order_pk):
        return get_object_or_404(participant_orders(request.user), pk=order_pk)

    @staticmethod
    def _legacy_event_order(order):
        try:
            return order.ticket_order
        except (AttributeError, ObjectDoesNotExist):
            return None

    @staticmethod
    def _validate_payable(order):
        if (
            order.status != CommerceOrderStatus.PENDING
            or order.total <= 0
            or order.payment_mode not in ONLINE_PAYMENT_MODES
        ):
            raise Http404("Cette démarche ne nécessite pas de paiement en ligne maintenant.")

    def _context(self, request, order, form, idempotency_key):
        return {
            "order": order,
            "form": form,
            "idempotency_key": idempotency_key,
            "participant_journey_url": reverse(
                "account:journey-detail", kwargs={"pk": order.journey_id}
            ),
            "is_commerce_order": True,
        }

    def get(self, request, order_pk):
        order = self._order(request, order_pk)
        self._validate_payable(order)
        form = PaymentStartForm(order=order, user=request.user)
        return render(request, self.template_name, self._context(request, order, form, uuid.uuid4().hex))

    def post(self, request, order_pk):
        order = self._order(request, order_pk)
        self._validate_payable(order)
        form = PaymentStartForm(request.POST, order=order, user=request.user)
        if form.is_valid():
            values = {
                "actor": request.user,
                "provider": form.cleaned_data["provider"],
                "method": form.cleaned_data["method"],
                "payer_name": form.cleaned_data.get("payer_name", ""),
                "payer_email": form.cleaned_data.get("payer_email", ""),
                "payer_phone": form.cleaned_data.get("payer_phone", ""),
                "idempotency_key": request.POST.get("idempotency_key") or None,
            }
            try:
                legacy_order = self._legacy_event_order(order)
                if legacy_order is not None:
                    # Current Event issuance still consumes TicketOrder on payment
                    # completion. The participant surface itself remains Commerce-first.
                    payment = initiate_payment(order=legacy_order, **values)
                else:
                    payment = initiate_commerce_payment(commerce_order=order, **values)
            except (PermissionDenied, ValidationError) as exc:
                messages.error(request, "; ".join(getattr(exc, "messages", [str(exc)])))
            else:
                messages.success(request, "Paiement initialisé.")
                return redirect("payments:detail", pk=payment.pk)
        return render(
            request,
            self.template_name,
            self._context(
                request,
                order,
                form,
                request.POST.get("idempotency_key") or uuid.uuid4().hex,
            ),
            status=400,
        )


class SandboxPaymentCompleteView(LoginRequiredMixin, View):
    login_url = "core:login"

    def post(self, request, pk):
        payment = get_object_or_404(get_payments_visible_to(request.user), pk=pk)
        try:
            payment = complete_sandbox_payment(payment=payment, actor=request.user)
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, "; ".join(getattr(exc, "messages", [str(exc)])))
        else:
            messages.success(request, _payment_success_message(payment))
        return redirect("payments:detail", pk=payment.pk)


class ManualPaymentCompleteView(LoginRequiredMixin, View):
    login_url = "core:login"

    def post(self, request, pk):
        payment = get_object_or_404(get_payments_visible_to(request.user), pk=pk)
        form = ManualPaymentCompleteForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Référence de paiement invalide.")
            return redirect("payments:detail", pk=payment.pk)
        try:
            payment = complete_manual_payment(
                payment=payment,
                actor=request.user,
                provider_reference=form.cleaned_data.get("provider_reference", ""),
            )
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, "; ".join(getattr(exc, "messages", [str(exc)])))
        else:
            messages.success(request, _payment_success_message(payment))
        return redirect("payments:detail", pk=payment.pk)


class PaymentCancelView(LoginRequiredMixin, View):
    login_url = "core:login"

    def post(self, request, pk):
        payment = get_object_or_404(get_payments_visible_to(request.user), pk=pk)
        try:
            cancel_payment(payment=payment, actor=request.user)
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, "; ".join(getattr(exc, "messages", [str(exc)])))
        else:
            messages.success(request, "Tentative de paiement annulée.")
        return redirect("payments:detail", pk=payment.pk)


class PaymentRefundView(LoginRequiredMixin, View):
    login_url = "core:login"

    def post(self, request, pk):
        payment = get_object_or_404(get_payments_visible_to(request.user), pk=pk)
        form = RefundForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Motif de remboursement invalide.")
            return redirect("payments:detail", pk=payment.pk)
        try:
            refund_payment(
                payment=payment,
                actor=request.user,
                reason=form.cleaned_data.get("reason", ""),
                idempotency_key=request.POST.get("idempotency_key") or None,
            )
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, "; ".join(getattr(exc, "messages", [str(exc)])))
        else:
            messages.success(request, "Paiement remboursé.")
        return redirect("payments:detail", pk=payment.pk)
