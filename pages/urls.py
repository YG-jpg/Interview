from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("", views.event_list, name="event_list"),
    path("events/<int:pk>/", views.event_detail, name="event_detail"),
    path("events/<int:pk>/book/", views.book_event, name="book_event"),
    path("bookings/", views.my_bookings, name="my_bookings"),
    path("bookings/<int:pk>/cancel/", views.cancel_booking_view, name="cancel_booking"),
    path("register/", views.register, name="register"),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
]
