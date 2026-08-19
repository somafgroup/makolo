from django import forms
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist

from events.permissions import user_can_manage_event

from .models import PaymentMethod, PaymentProvider


class PaymentStartForm(forms.Form):
    provider = forms.ChoiceField(choices=PaymentProvider.choices)
    method = forms.ChoiceField(choices=PaymentMethod.choices)
    payer_name = forms.CharField(max_length=180, required=False)
    payer_email = forms.EmailField(required=False)
    payer_phone = forms.CharField(max_length=40, required=False)

    def __init__(self, *args, order=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.order = order
        self.user = user

        legacy_order = None
        event = getattr(order, "event", None) if order is not None else None
        if order is not None and event is None:
            try:
                legacy_order = order.ticket_order
            except (AttributeError, ObjectDoesNotExist):
                legacy_order = None
            event = getattr(legacy_order, "event", None)

        provider_choices = []
        if getattr(settings, "PAYMENTS_SANDBOX_ENABLED", False):
            provider_choices.append((PaymentProvider.SANDBOX, PaymentProvider.SANDBOX.label))
        if user and event is not None and user_can_manage_event(user, event):
            provider_choices.append((PaymentProvider.MANUAL, PaymentProvider.MANUAL.label))
        elif user and event is None and getattr(user, "is_staff", False):
            provider_choices.append((PaymentProvider.MANUAL, PaymentProvider.MANUAL.label))
        self.fields["provider"].choices = provider_choices

        if legacy_order is None and order is not None and hasattr(order, "customer_name"):
            legacy_order = order
        if legacy_order is not None:
            self.fields["payer_name"].initial = legacy_order.customer_name
            self.fields["payer_email"].initial = legacy_order.customer_email
        elif order is not None:
            buyer = getattr(order, "buyer", None)
            self.fields["payer_name"].initial = (
                getattr(buyer, "full_name", "") or getattr(buyer, "username", "")
            )
            self.fields["payer_email"].initial = getattr(buyer, "email", "")


class ManualPaymentCompleteForm(forms.Form):
    provider_reference = forms.CharField(max_length=160, required=False)


class RefundForm(forms.Form):
    reason = forms.CharField(
        max_length=500,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
