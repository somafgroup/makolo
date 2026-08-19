from django.utils import timezone

from .models import DeliveryStatus, Notification, NotificationDelivery


def get_notifications_for_user(user):
    if not getattr(user, "is_authenticated", False):
        return Notification.objects.none()
    return (
        Notification.objects.filter(recipient=user)
        .select_related(
            "activity",
            "journey",
            "access",
            "commerce_order",
            "commerce_order__journey",
        )
        .prefetch_related("deliveries")
    )


def get_unread_notifications_count(user) -> int:
    if not getattr(user, "is_authenticated", False):
        return 0
    return Notification.objects.filter(recipient=user, read_at__isnull=True).count()


def get_due_deliveries(*, limit: int = 100):
    return (
        NotificationDelivery.objects.filter(
            status=DeliveryStatus.QUEUED,
            scheduled_for__lte=timezone.now(),
        )
        .select_related("notification", "notification__recipient")
        .order_by("scheduled_for", "created_at")[:limit]
    )
