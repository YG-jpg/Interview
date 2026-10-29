from django.urls import path

from . import views

urlpatterns = [
    path("register/", views.register),
    path("events/", views.event_list),
    path("events/<int:pk>/", views.event_detail),
    path("events/<int:pk>/waitlist/", views.event_waitlist),
    path("bookings/", views.booking_list),
    path("bookings/<int:pk>/", views.booking_detail),
    path("bookings/<int:pk>/confirm/", views.booking_confirm),
    path("bookings/<int:pk>/qr/", views.booking_qr),
]
