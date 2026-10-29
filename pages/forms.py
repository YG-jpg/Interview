from django import forms


class BookingForm(forms.Form):
    tickets = forms.IntegerField(min_value=1, initial=1)
    # new uuid on every page load, so a double submit books only once
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput, required=False)
