from typing import Never, NoReturn, override

from django.db.models import QuerySet
from rest_framework.generics import GenericAPIView
from rest_framework.generics import get_object_or_404

from .exceptions import MissingIdsError
from .serializers import ItemsSerializer
from .services import validate_view


class GetQuerySetByAuthUserMixin(GenericAPIView):
    """Mixin to filter queryset by the authenticated user.

    Overrides the get_queryset method to automatically filter all results
    by the current request user.
    """

    @override
    def get_queryset(self) -> Never:  # Avoid 'incompatible override' error
        """Get queryset filtered for the authenticated user.

        Returns:
            QuerySet: Queryset filtered by the current user.
        """
        return super().get_queryset().filter(user=self.request.user)


class GetObjectByAuthUserMixin(GenericAPIView):
    """Mixin to retrieve object that belongs to the authenticated user.

    Overrides the get_object method to ensure the retrieved object belongs
    to the current request user.
    """

    @override
    def get_object(self) -> NoReturn:  # Avoid 'incompatible override' error
        """Get object for the authenticated user.

        Returns:
            object: The object belonging to the current user.
        """
        obj = get_object_or_404(self.get_queryset(), user=self.request.user)
        self.check_object_permissions(self.request, obj)
        return obj


class FilterByIdsListMixin(GenericAPIView):
    """Mixin to filter querysets by a list of IDs from request data.

    Provides methods to extract an ID list from request data and filter
    the queryset by those IDs, raising an error if any IDs are not found.
    """

    def filter_by_ids(self, queryset: QuerySet | None = None) -> QuerySet:
        """Filter queryset to only include items with specified IDs.

        Extracts the ID list from request data and returns items matching
        those IDs. Raises an error if any requested IDs are not found.

        Args:
            queryset (QuerySet | None): The queryset to filter, or None to use
                the result of get_queryset().

        Returns:
            QuerySet: Filtered queryset containing only the requested items.

        Raises:
            MissingIdsError: If any requested IDs are not found.
        """
        if queryset is None:
            queryset = self.get_queryset()
        item_ids = self._get_item_ids()
        queryset = queryset.filter(id__in=item_ids)
        count = queryset.count()
        if count != len(item_ids):
            found_ids = set(queryset.values_list('id', flat=True))
            raise MissingIdsError(item_ids - found_ids)
        return queryset

    def _get_item_ids(self) -> set[int]:
        """Read a list of item IDs from request data.

        Returns:
            set[int]: A set of parsed item IDs.
        """
        data = validate_view(ItemsSerializer, self)
        return set(data['items'])
