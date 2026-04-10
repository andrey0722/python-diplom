from django.urls import path

from api.views import EmailConfirmView
from api.views import SendEmailVerificationView
from api.views import UserInfoView
from api.views import UserLoginView
from api.views import UserRegisterView

urlpatterns = [
    path('user/register', UserRegisterView.as_view()),
    path('user/register/verify', SendEmailVerificationView.as_view()),
    path(
        'user/register/confirm',
        EmailConfirmView.as_view(),
        name='email-confirm',
    ),
    path('user/login', UserLoginView.as_view()),
    path('user/details', UserInfoView.as_view()),
]
