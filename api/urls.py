from django.urls import path

from .views import EmailConfirmView
from .views import SendEmailVerificationView
from .views import UserContactsView
from .views import UserInfoView
from .views import UserLoginView
from .views import UserRegisterView

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
    path('user/contact', UserContactsView.as_view()),
]
