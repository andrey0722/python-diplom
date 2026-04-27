from collections.abc import Iterable
from typing import Any, cast

from django import forms

from .exceptions import InvalidOrderStateTransitionError
from .models import AnyUser
from .models import Contact
from .models import Order
from .models import OrderState
from .models import User
from .services import get_allowed_state_transitions
from .services import validate_order_state_transition


class BasketAdminForm(forms.ModelForm):
    """Admin form for creating and editing basket orders."""

    class Meta:
        model = Order
        fields = ('user', 'contact', 'state')
        widgets = {
            'contact': forms.HiddenInput,
            'state': forms.HiddenInput,
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize defaults for newly created basket orders.

        Args:
            *args (Any): Positional form arguments.
            **kwargs (Any): Keyword form arguments.
        """
        super().__init__(*args, **kwargs)

        if self.instance.pk is None:
            # Creating new instance
            self.fields['contact'].initial = None
            self.fields['state'].initial = OrderState.BASKET
            self._filter_user_choices()

    def _filter_user_choices(self) -> None:
        """Limit users to those without an existing basket."""
        field = cast(forms.ModelChoiceField, self.fields['user'])
        field.empty_label = None
        field.queryset = User.objects.exclude(orders__state=OrderState.BASKET)


class OrderAdminForm(forms.ModelForm):
    """Admin form for editing placed orders."""

    class Meta:
        model = Order
        fields = ('user', 'contact', 'state')

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize order-specific contact and state choices.

        Args:
            *args (Any): Positional form arguments.
            **kwargs (Any): Keyword form arguments.
        """
        super().__init__(*args, **kwargs)

        order: Order = self.instance
        if order.pk is not None:
            # Changing existing instance
            self._filter_contact_choices(order.user_id)
            self._filter_state_choices(order.state)

    def clean_state(self) -> OrderState:
        """Validate that the submitted order state transition is allowed.

        Returns:
            OrderState: The validated target order state.

        Raises:
            ValidationError: If the requested state transition is invalid.
        """
        new = self.cleaned_data['state']

        order_id = self.instance.pk
        if order_id is None:
            # The instance is not saved yet
            return new

        old = Order.objects.only('state').get(pk=order_id).state
        try:
            validate_order_state_transition(old, new)
        except InvalidOrderStateTransitionError as e:
            raise forms.ValidationError(str(e), code=e.code) from e
        return new

    def _filter_contact_choices(self, user_id: object) -> None:
        """Limit contact choices to contacts owned by the order user.

        Args:
            user_id (object): The user primary key used for filtering.
        """
        field = cast(forms.ModelChoiceField, self.fields['contact'])
        field.empty_label = None
        field.queryset = Contact.objects.filter(user_id=user_id)

    def _filter_state_choices(self, state: OrderState) -> None:
        """Limit state choices to allowed transitions from the current state.

        Args:
            state (OrderState): The current order state.
        """
        visible = get_allowed_state_transitions(state)
        field = cast(forms.TypedChoiceField, self.fields['state'])
        choices = cast(Iterable[tuple[object, object]], field.choices)
        field.choices = [
            (value, label) for value, label in choices if value in visible
        ]


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
