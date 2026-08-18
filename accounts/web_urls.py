from django.urls import path

from .participant_views import (
    ParticipantAccessDetailView,
    ParticipantAccessListView,
    ParticipantAccessQrView,
    ParticipantJourneyDetailView,
    ParticipantJourneyListView,
)
from .web_views import (
    AccountDeleteView,
    AccountPasswordChangeView,
    AccountProfileView,
    AccountRegistrationView,
    PasswordForgotView,
    PasswordResetConfirmView,
)


app_name = "account"

urlpatterns = [
    path("register/", AccountRegistrationView.as_view(), name="register"),
    path("profile/", AccountProfileView.as_view(), name="profile"),
    path("journeys/", ParticipantJourneyListView.as_view(), name="journey-list"),
    path("journeys/<uuid:pk>/", ParticipantJourneyDetailView.as_view(), name="journey-detail"),
    path("accesses/", ParticipantAccessListView.as_view(), name="access-list"),
    path("accesses/<uuid:pk>/", ParticipantAccessDetailView.as_view(), name="access-detail"),
    path("accesses/<uuid:pk>/qr.png", ParticipantAccessQrView.as_view(), name="access-qr"),
    path("password/", AccountPasswordChangeView.as_view(), name="password-change"),
    path("password/forgot/", PasswordForgotView.as_view(), name="password-forgot"),
    path(
        "password/reset/<str:uid>/<str:token>/",
        PasswordResetConfirmView.as_view(),
        name="password-reset-confirm",
    ),
    path("delete/", AccountDeleteView.as_view(), name="delete"),
]
