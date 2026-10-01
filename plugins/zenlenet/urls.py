from django.urls import path

from . import views

urlpatterns = [
    path('obss/', views.obss_home, name='obss'),
]
