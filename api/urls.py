from django.urls import path

from api.views import UserInfoView
from api.views import UserLoginView
from api.views import UserRegisterView

urlpatterns = [
    path('user/register', UserRegisterView.as_view()),
    path('user/login', UserLoginView.as_view()),
    path('user/details', UserInfoView.as_view()),
]
