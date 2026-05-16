from collections.abc import Callable
from collections.abc import Mapping
from dataclasses import dataclass
import functools
import logging
from typing import Final, cast, overload

from celery import shared_task
from celery.contrib.django.task import DjangoTask
from django.core.files.storage import default_storage
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Prefetch
from django.template.loader import render_to_string
from easy_thumbnails.files import generate_all_aliases
from easy_thumbnails.models import Source
from easy_thumbnails.models import Thumbnail

from .models import Order
from .models import OrderItem
from .models import OrderState
from .models import User
from .models import retry_transaction
from .templates import OrderContext
from .templates import VerifyContext
from .templates import get_order_user_context
from .templates import get_shops_and_context

logger = logging.getLogger(__name__)


class DjangoTaskT[**P, T](DjangoTask):
    """Typed Celery Django task protocol used by local task wrappers."""

    def delay(self, *args: P.args, **kwargs: P.kwargs) -> T: ...
    def delay_on_commit(self, *args: P.args, **kwargs: P.kwargs) -> None: ...


type DjangoTaskDecorator[**P, T] = Callable[
    [Callable[P, T]], DjangoTaskT[P, T]
]


@overload
def shared_task_wrapper[**P, T](
    func: Callable[P, T],
    /,
    **kwargs: object,
) -> DjangoTaskT[P, T]: ...


@overload
def shared_task_wrapper[**P, T](
    **kwargs: object,
) -> DjangoTaskDecorator[P, T]: ...


def shared_task_wrapper[**P, T](
    func: Callable[P, T] | None = None,
    /,
    **kwargs: object,
) -> DjangoTaskT[P, T] | DjangoTaskDecorator[P, T]:
    """Helper decorator for correct celery task typing."""

    def decorator(func: Callable[P, T]) -> DjangoTaskT[P, T]:
        """Wrap a function as a typed shared task.

        Args:
            func (Callable[P, T]): Function to register as a Celery task.

        Returns:
            DjangoTaskT[P, T]: Registered Celery task object.
        """
        real_decorator = shared_task(**kwargs) if kwargs else shared_task
        real_decorator = functools.wraps(func)(real_decorator)
        return real_decorator(func)

    return decorator if func is None else decorator(func)


@shared_task_wrapper
def generate_user_avatar_thumbnails(user_id: int, avatar_name: str) -> None:
    """Generate thumbnails for a user's current avatar.

    Args:
        user_id (int): User primary key.
        avatar_name (str): Avatar name expected when the task runs.
    """
    user = User.objects.get(pk=user_id)
    if not user.avatar:
        return

    if user.avatar.name != avatar_name:
        logger.info(
            'Skipping thumbnail generation for user %s: '
            'avatar changed from %r to %r',
            user_id,
            avatar_name,
            user.avatar.name,
        )
        return

    generate_all_aliases(user.avatar, include_global=False)
    User.objects.filter(pk=user_id, avatar=avatar_name).update(
        avatar_thumbnails_ready=True
    )


@shared_task_wrapper
def delete_avatar_with_thumbnails(avatar_name: str) -> None:
    """Delete an avatar file and its generated thumbnails.

    Args:
        avatar_name (str): Stored avatar file name to delete.
    """
    if not avatar_name:
        return

    sources = Source.objects.filter(name=avatar_name)
    thumbnails = Thumbnail.objects.filter(source__in=sources)

    file_names: list[str] = list(thumbnails.values_list('name', flat=True))
    file_names.append(avatar_name)

    for file_name in file_names:
        try:
            if default_storage.exists(file_name):
                default_storage.delete(file_name)
        except Exception:
            logger.exception('Failed to delete file %r', file_name)

    thumbnails_count, _ = thumbnails.delete()
    sources_count, _ = sources.delete()

    logger.info(
        'Deleted avatar %r with %s thumbnails and %s sources',
        avatar_name,
        thumbnails_count,
        sources_count,
    )


@shared_task_wrapper
def send_user_verification_mail(
    email: str,
    verify_context: VerifyContext,
) -> None:
    """Send a verification email to a user.

    Args:
        email (str): Recipient email address.
        verify_context (VerifyContext): Verification template context.
    """
    render_and_send_mail(EMAIL_VERIFICATION_TEMPLATES, verify_context, email)


@shared_task_wrapper
def send_password_reset_mail(
    email: str,
    verify_context: VerifyContext,
) -> None:
    """Send a password reset email to a user.

    Args:
        email (str): Recipient email address.
        verify_context (VerifyContext): Password reset template context.
    """
    render_and_send_mail(PASSWORD_RESET_TEMPLATES, verify_context, email)


@shared_task_wrapper
@retry_transaction
@transaction.atomic
def notify_order_state(
    order_id: object,
    order_context: OrderContext,
) -> None:
    """Send all notifications for the current order state.

    Args:
        order_id (object): Primary key of the order to notify about.
        order_context (OrderContext): Shared order notification context.
    """
    items = OrderItem.objects.select_related(
        'shop_offer',
        'shop_offer__product',
    )
    order = (
        Order.objects.select_for_update()
        .select_related('user')
        .prefetch_related(Prefetch('items', items))
        .get(pk=order_id)
    )
    send_user_order_mail(order, order_context)
    send_shops_order_mail(order, order_context)


@dataclass(frozen=True, slots=True)
class EmailTemplateSet:
    """Template paths used to render one email message."""

    subject: str
    text: str
    html: str | None = None


EMAIL_VERIFICATION_TEMPLATES: Final = EmailTemplateSet(
    subject='api/email_verification_subject.txt',
    text='api/email_verification_email.txt',
    html='api/email_verification_email.html',
)


PASSWORD_RESET_TEMPLATES: Final = EmailTemplateSet(
    subject='api/password_reset_subject.txt',
    text='api/password_reset_email.txt',
    html='api/password_reset_email.html',
)


ORDER_CREATED_TEMPLATES: Final = EmailTemplateSet(
    subject='api/order_created_subject.txt',
    text='api/order_created_email.txt',
    html='api/order_created_email.html',
)


ORDER_CANCELLED_TEMPLATES: Final = EmailTemplateSet(
    subject='api/order_cancelled_subject.txt',
    text='api/order_cancelled_email.txt',
    html='api/order_cancelled_email.html',
)


ORDER_STATE_CHANGE_TEMPLATES: Final = EmailTemplateSet(
    subject='api/order_state_change_subject.txt',
    text='api/order_state_change_email.txt',
    html='api/order_state_change_email.html',
)


@functools.cache
def get_user_order_templates(state: OrderState) -> EmailTemplateSet | None:
    """Return user notification templates for the order state.

    Args:
        state (OrderState): The current order state.

    Returns:
        EmailTemplateSet | None: Matching templates, or None when no
            user notification is needed.
    """
    if state == OrderState.NEW:
        return ORDER_CREATED_TEMPLATES
    if state == OrderState.CANCELLED:
        return ORDER_CANCELLED_TEMPLATES
    if state in OrderState.active():
        return ORDER_STATE_CHANGE_TEMPLATES
    return None


def send_user_order_mail(order: Order, order_context: OrderContext) -> None:
    """Send an order state email to the customer when needed.

    Args:
        order (Order): Order whose customer may be notified.
        order_context (OrderContext): Shared order notification context.
    """
    templates = get_user_order_templates(order.state)
    if templates is None:
        # No need to notify the user
        return

    user = cast(User, order.user)
    email = cast(str, user.email)
    context = get_order_user_context(order, order_context)
    render_and_send_mail(templates, context, email)


ORDER_PLACED_SHOP_ADMIN_TEMPLATES: Final = EmailTemplateSet(
    subject='api/order_placed_shop_admin_subject.txt',
    text='api/order_placed_shop_admin_email.txt',
    html='api/order_placed_shop_admin_email.html',
)


ORDER_CANCELLED_SHOP_ADMIN_TEMPLATES: Final = EmailTemplateSet(
    subject='api/order_cancelled_shop_admin_subject.txt',
    text='api/order_cancelled_shop_admin_email.txt',
    html='api/order_cancelled_shop_admin_email.html',
)


@functools.cache
def get_shop_order_templates(state: OrderState) -> EmailTemplateSet | None:
    """Return shop admin notification templates for the order state.

    Args:
        state (OrderState): The current order state.

    Returns:
        EmailTemplateSet | None: Matching templates, or None when shop
            admins do not need a notification.
    """
    if state == OrderState.NEW:
        return ORDER_PLACED_SHOP_ADMIN_TEMPLATES
    if state == OrderState.CANCELLED:
        return ORDER_CANCELLED_SHOP_ADMIN_TEMPLATES
    return None


def send_shops_order_mail(order: Order, order_context: OrderContext) -> None:
    """Send order state emails to shop admins when needed.

    Args:
        order (Order): Order whose shops may be notified.
        order_context (OrderContext): Shared order notification context.
    """
    templates = get_shop_order_templates(order.state)
    if templates is None:
        # No need to notify any admins
        return

    for shop, context in get_shops_and_context(order, order_context):
        admin = cast(User, shop.user)
        email = cast(str, admin.email)
        render_and_send_mail(templates, context, email)


def render_and_send_mail(
    templates: EmailTemplateSet,
    context: Mapping[str, object],
    to_email: str,
    from_email: str | None = None,
) -> None:
    """Send a django.core.mail.EmailMultiAlternatives to `to_email`.

    Args:
        templates (EmailTemplateSet): Templates for email message rendering.
        context (dict[str, Any]): Template context data.
        to_email (str): Recipient email address.
        from_email (str | None): Optional sender email address.
    """
    context = dict(context)
    context['email'] = to_email

    subject = render_to_string(templates.subject, context)
    # Email subject *must not* contain newlines
    subject = ''.join(subject.splitlines())

    text = render_to_string(templates.text, context)
    html = templates.html and render_to_string(templates.html, context)

    try:
        send_mail(
            subject=subject,
            message=text,
            from_email=from_email,
            recipient_list=[to_email],
            html_message=html,
        )
    except Exception:
        logger.exception('Failed to send email to user %s', to_email)
