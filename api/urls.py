from django.urls import path
from drf_spectacular.views import SpectacularAPIView
from drf_spectacular.views import SpectacularRedocView
from drf_spectacular.views import SpectacularSwaggerView

from .views import BasketView
from .views import CategoryListView
from .views import EmailConfirmView
from .views import PasswordResetConfirmView
from .views import SendEmailVerificationView
from .views import SendPasswordResetView
from .views import ShopListView
from .views import ShopOfferListView
from .views import ShopOrdersListView
from .views import ShopOrderView
from .views import ShopStateView
from .views import ShopUpdateView
from .views import SocialLoginErrorView
from .views import SocialLoginSuccessView
from .views import UserContactsView
from .views import UserInfoView
from .views import UserLoginView
from .views import UserOrdersListView
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
    path('user/login/social/success', SocialLoginSuccessView.as_view()),
    path('user/login/social/error', SocialLoginErrorView.as_view()),
    path('user/details', UserInfoView.as_view()),
    path('user/contact', UserContactsView.as_view()),
    path('partner/update', ShopUpdateView.as_view()),
    path('partner/state', ShopStateView.as_view()),
    path('partner/orders', ShopOrdersListView.as_view()),
    path('partner/orders/<pk>', ShopOrderView.as_view(), name='shop-order'),
    path('shops', ShopListView.as_view()),
    path('categories', CategoryListView.as_view()),
    path('products', ShopOfferListView.as_view()),
    path('basket', BasketView.as_view()),
    path('order', UserOrdersListView.as_view()),
    path('order/<pk>', UserOrderView.as_view(), name='order'),
    # API schema
    path('schema/', SpectacularAPIView.as_view(), name='schema'),
    path(
        'schema/swagger-ui/',
        SpectacularSwaggerView.as_view(url_name='schema'),
        name='swagger-ui',
    ),
    path(
        'schema/redoc/',
        SpectacularRedocView.as_view(url_name='schema'),
        name='redoc',
    ),
]
