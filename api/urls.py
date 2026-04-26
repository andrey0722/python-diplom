from django.urls import path

from .views import BasketView
from .views import CategoryListView
from .views import EmailConfirmView
from .views import PasswordResetConfirmView
from .views import SendEmailVerificationView
from .views import SendPasswordResetView
from .views import ShopListView
from .views import ShopOfferListView
from .views import ShopStateView
from .views import ShopUpdateView
from .views import UserContactsView
from .views import UserInfoView
from .views import UserLoginView
from .views import UserOrderView
from .views import UserRegisterView

urlpatterns = [
    path('user/register', UserRegisterView.as_view()),
    path('user/register/verify', SendEmailVerificationView.as_view()),
    path(
        'user/register/confirm',
        EmailConfirmView.as_view(),
        name='email-confirm',
    ),
    path('user/password_reset', SendPasswordResetView.as_view()),
    path(
        'user/password_reset/confirm',
        PasswordResetConfirmView.as_view(),
        name='password-reset-confirm',
    ),
    path('user/login', UserLoginView.as_view()),
    path('user/details', UserInfoView.as_view()),
    path('user/contact', UserContactsView.as_view()),
    path('partner/update', ShopUpdateView.as_view()),
    path('partner/state', ShopStateView.as_view()),
    path('shops', ShopListView.as_view()),
    path('categories', CategoryListView.as_view()),
    path('products', ShopOfferListView.as_view()),
    path('basket', BasketView.as_view()),
    path('order', UserOrderView.as_view()),
]
