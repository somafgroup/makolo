from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.generic import ListView

from accounts.models import NotificationPreference
from accounts.participant_presentation import notification_participant_url

from .forms import NotificationPreferenceForm
from .selectors import get_notifications_for_user


class NotificationListView(LoginRequiredMixin, ListView):
    template_name = "notifications/notification_list.html"
    context_object_name = "notifications"
    paginate_by = 30
    login_url = "core:login"

    def get_queryset(self):
        queryset = get_notifications_for_user(self.request.user)
        if self.request.GET.get("filter") == "unread":
            queryset = queryset.filter(read_at__isnull=True)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_filter"] = self.request.GET.get("filter", "all")
        context["unread_count"] = get_notifications_for_user(self.request.user).filter(
            read_at__isnull=True
        ).count()
        return context


class NotificationOpenView(LoginRequiredMixin, View):
    login_url = "core:login"

    def get(self, request, pk):
        notification = get_object_or_404(get_notifications_for_user(request.user), pk=pk)
        notification.mark_read()
        participant_url = notification_participant_url(notification)
        if participant_url:
            return redirect(participant_url)
        if notification.action_url.startswith("/") and not notification.action_url.startswith("//"):
            return redirect(notification.action_url)
        return redirect("notifications:list")


class NotificationMarkReadView(LoginRequiredMixin, View):
    login_url = "core:login"

    def post(self, request, pk):
        notification = get_object_or_404(get_notifications_for_user(request.user), pk=pk)
        notification.mark_read()
        return redirect(request.POST.get("next") or "notifications:list")


class NotificationMarkAllReadView(LoginRequiredMixin, View):
    login_url = "core:login"

    def post(self, request):
        now = timezone.now()
        get_notifications_for_user(request.user).filter(read_at__isnull=True).update(
            read_at=now,
            updated_at=now,
        )
        messages.success(request, "Toutes les notifications ont été marquées comme lues.")
        return redirect("notifications:list")


class NotificationPreferenceView(LoginRequiredMixin, View):
    template_name = "notifications/preferences.html"
    login_url = "core:login"

    def get_object(self, request):
        preference, _ = NotificationPreference.objects.get_or_create(user=request.user)
        return preference

    def get(self, request):
        form = NotificationPreferenceForm(instance=self.get_object(request))
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        preference = self.get_object(request)
        form = NotificationPreferenceForm(request.POST, instance=preference)
        if form.is_valid():
            form.save()
            messages.success(request, "Préférences de notification enregistrées.")
            return redirect("notifications:preferences")
        return render(request, self.template_name, {"form": form}, status=400)
