from typing import Any, cast

from django import forms

from .models import AnyUser
from .models import Contact


class UserContactSelectForm(forms.Form):
    """Form for selecting a user's contact."""

    contact = forms.ModelChoiceField(queryset=Contact.objects.none())

    def __init__(
        self,
        *args: Any,
        user: AnyUser | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the form with user-specific contact queryset.

        Args:
            *args (Any): Positional arguments for the form.
            user (AnyUser | None): The user to filter contacts for.
            **kwargs (Any): Keyword arguments for the form.
        """
        super().__init__(*args, **kwargs)
        if user is not None:
            queryset = Contact.objects.filter(user=user)
            field = cast(forms.ModelChoiceField, self.fields['contact'])
            field.queryset = queryset
