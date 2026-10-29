from django import forms


class BookingForm(forms.Form):
    """The small form on the event page: how many tickets to book."""

    tickets = forms.IntegerField(min_value=1, initial=1)
