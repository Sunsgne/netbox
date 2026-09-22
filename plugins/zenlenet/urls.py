from django.urls import path

from . import views

urlpatterns = [
    path('odoo/', views.odoo_home, name='odoo'),
]
