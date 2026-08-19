from django.db.models import Q

from authorization.constants import PermissionCode
from authorization.services import space_ids_with_permission

from .models import Payment, PaymentEvent, Refund


def _space_filter(prefix: str, space_ids) -> Q:
    if not space_ids:
        return Q(pk__isnull=True)
    return Q(**{f"{prefix}activity__space_id__in": space_ids})


def get_payments_visible_to(user):
    queryset = Payment.objects.select_related(
        "order",
        "order__event",
        "order__event__activity",
        "order__event__activity__created_by",
        "order__event__activity__space",
        "order__buyer",
        "commerce_order",
        "commerce_order__buyer",
        "commerce_order__payee_space",
        "commerce_order__journey",
        "commerce_order__journey__beneficiary",
        "commerce_order__journey__activity",
        "commerce_order__journey__activity__space",
        "initiated_by",
    ).prefetch_related("refunds")
    if not getattr(user, "is_authenticated", False):
        return queryset.none()

    space_ids = space_ids_with_permission(user, PermissionCode.FINANCE_VIEW)
    if space_ids is None:
        return queryset

    event_context = _space_filter("order__event__", space_ids)
    commerce_context = Q(commerce_order__payee_space_id__in=space_ids) | Q(
        commerce_order__journey__activity__space_id__in=space_ids
    )
    return queryset.filter(
        Q(order__buyer=user)
        | Q(commerce_order__buyer=user)
        | Q(initiated_by=user)
        | event_context
        | commerce_context
        | Q(order__event__activity__space__isnull=True, order__event__activity__created_by=user)
    ).distinct()


def get_refunds_visible_to(user):
    payment_ids = get_payments_visible_to(user).values("pk")
    return Refund.objects.select_related(
        "payment",
        "payment__order",
        "payment__order__event",
        "payment__commerce_order",
        "requested_by",
    ).filter(payment_id__in=payment_ids)


def get_payment_events_visible_to(user):
    queryset = PaymentEvent.objects.select_related(
        "payment",
        "payment__order",
        "payment__order__event",
        "payment__order__event__activity",
        "payment__order__event__activity__created_by",
        "payment__order__event__activity__space",
        "payment__commerce_order",
        "payment__commerce_order__payee_space",
        "payment__commerce_order__journey__activity__space",
    )
    if not getattr(user, "is_authenticated", False):
        return queryset.none()

    space_ids = space_ids_with_permission(user, PermissionCode.FINANCE_VIEW)
    if space_ids is None:
        return queryset
    event_context = _space_filter("payment__order__event__", space_ids)
    commerce_context = Q(payment__commerce_order__payee_space_id__in=space_ids) | Q(
        payment__commerce_order__journey__activity__space_id__in=space_ids
    )
    return queryset.filter(
        event_context
        | commerce_context
        | Q(
            payment__order__event__activity__space__isnull=True,
            payment__order__event__activity__created_by=user,
        )
    ).distinct()
