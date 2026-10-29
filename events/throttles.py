from rest_framework.throttling import UserRateThrottle


class BookingRateThrottle(UserRateThrottle):
    """Limit how many bookings one user can make per minute. GET is not limited."""
    scope = "bookings"

    def allow_request(self, request, view):
        if request.method != "POST":
            return True
        return super().allow_request(request, view)
