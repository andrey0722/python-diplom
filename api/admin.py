from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _

from .models import Contact
from .models import Token
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Django admin configuration for User model."""

    list_display = (
        'email',
        'full_name',
        'last_login',
        'date_joined',
        'is_active',
        'is_staff',
    )
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        (
            _('Personal info'),
            {
                'fields': (
                    'first_name',
                    'last_name',
                    'company',
                    'position',
                ),
            },
        ),
        (
            _('Permissions'),
            {
                'fields': (
                    'is_active',
                    'is_staff',
                    'is_superuser',
                    'groups',
                    'user_permissions',
                ),
            },
        ),
        (_('Important dates'), {'fields': ('last_login', 'date_joined')}),
    )
    ordering = ('email',)


@admin.register(Token)
class TokenAdmin(admin.ModelAdmin):
    """Admin configuration for Token model."""

    list_display = ('key', 'user', 'created')
    list_filter = ('created',)
    fields = ('user',)
    search_fields = (f'user__{User.USERNAME_FIELD}',)
    search_help_text = _('User')
    ordering = (f'user__{User.USERNAME_FIELD}',)


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    """Admin configuration for Contact model."""

    list_display = (
        'address',
        'user',
        'contact_person',
        'contact_email',
        'phone',
    )
    list_filter = ('city', 'user')
    search_fields = (
        f'user__{User.USERNAME_FIELD}',
        'email',
        'phone',
        'first_name',
        'middle_name',
        'last_name',
        'city',
        'street',
        'house',
        'structure',
        'building',
        'apartment',
    )
    fieldsets = (
        (None, {'fields': ('user',)}),
        (
            _('Contacts'),
            {
                'fields': ('phone', 'email'),
            },
        ),
        (
            _('Personal info'),
            {
                'fields': ('first_name', 'middle_name', 'last_name'),
            },
        ),
        (
            _('Address'),
            {
                'fields': (
                    'city',
                    'street',
                    'house',
                    'structure',
                    'building',
                    'apartment',
                ),
            },
        ),
    )
