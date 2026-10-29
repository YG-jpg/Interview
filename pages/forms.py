from django import forms


class BookingForm(forms.Form):
    """Формата за резервация на страницата на събитието."""
    # Брой билети - цяло число, поне 1. Django отказва текст и отрицателни числа.
    tickets = forms.IntegerField(min_value=1, initial=1)
    # нов uuid при всяко зареждане на страницата, така че двойно изпращане на
    # формата (двоен клик) резервира само веднъж
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput, required=False)
