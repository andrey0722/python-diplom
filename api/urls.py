from django.urls import path

from api.views import UserRegisterView

urlpatterns = [
    path('user/register', UserRegisterView.as_view()),
]
