from rest_framework.permissions import BasePermission

from events.permissions import user_can_manage_event_finance
from tickets.permissions import user_can_access_order


def user_can_access_payment(user, payment) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if payment.order_id:
        return user_can_access_order(user, payment.order)
    if payment.commerce_order_id:
        return bool(
            payment.commerce_order.buyer_id == user.pk
            or payment.initiated_by_id == user.pk
            or getattr(user, "is_staff", False)
        )
    return False


def user_can_manage_payment(user, payment) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if payment.order_id:
        return user_can_manage_event_finance(user, payment.order.event)
    return bool(getattr(user, "is_staff", False))


class CanAccessPayment(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        return user_can_access_payment(request.user, obj)


class CanManagePayment(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        return user_can_manage_payment(request.user, obj)
