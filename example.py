from collections.abc import Callable
from collections.abc import Iterable
from collections.abc import Mapping
from dataclasses import Field
from dataclasses import dataclass
from dataclasses import field
from dataclasses import fields
import enum
import functools
import json
from pathlib import Path
import random
import re
from typing import Any, ClassVar, Protocol, cast

from faker import Faker
import httpx

SERVER_ADDRESS = 'http://127.0.0.1:8000'
USER_EMAIL = 'test_user@example.com'
USER_PASSWORD = '123'

API_ROOT = f'{SERVER_ADDRESS}/api/v1'
FAKER_LOCALE = 'ru_RU'
FAKER_PHONE_TEMPLATE = '+79#########'
APARTMENT_TEMPLATE = '%##'
SHOP_DATA_DIR = Path(__file__).parent / 'shop_data'
SHOP_DATA_NAME_REGEX = re.compile(r'shop([^.]+)\.ya?ml')
USER_COUNT = 3
CONTACTS_COUNT = 10
FILL_BASKET_SIZE = 10


class PersonSex(enum.StrEnum):
    """Enumeration of person sexes for name generation."""

    MALE = enum.auto()
    FEMALE = enum.auto()


class PersonGenerator:
    """Generator for personal data with fixed sex."""

    def __init__(
        self,
        faker: Faker,
        sex: PersonSex | None = None,
    ) -> None:
        """Create a name generator for the given person sex.

        Args:
            faker (Faker): Faker instance for name generation.
            sex (PersonSex | None): Optional sex to generate names for.
        """
        self.faker = faker
        if sex is None:
            sex = random.choice(list(PersonSex))
        match sex:
            case PersonSex.MALE:
                self.first_name = faker.first_name_male
                self.middle_name = faker.middle_name_male
                self.last_name = faker.last_name_male
                self.job = faker.job_male
            case PersonSex.FEMALE:
                self.first_name = faker.first_name_female
                self.middle_name = faker.middle_name_female
                self.last_name = faker.last_name_female
                self.job = faker.job_female
            case _:
                raise NotImplementedError

    def first_name(self) -> str:
        """Return a generated first name."""
        raise NotImplementedError

    def middle_name(self) -> str:
        """Return a generated middle name."""
        raise NotImplementedError

    def last_name(self) -> str:
        """Return a generated last name."""
        raise NotImplementedError

    def job(self) -> str:
        """Return a generated job title."""
        raise NotImplementedError


class PersonGeneratorFactory:
    """Factory for creating PersonGenerator instances."""

    def __init__(self, faker: Faker) -> None:
        """Initialize a factory for generating PersonGenerator instances."""
        self.faker = faker

    def __call__(self, sex: PersonSex | None = None) -> PersonGenerator:
        """Create a PersonGenerator for the requested sex."""
        return PersonGenerator(self.faker, sex)


class NumberGenerator:
    """Generator for formatted numbers using faker templates."""

    def __init__(self, faker: Faker, template: str) -> None:
        """Initialize a number generator from a faker template."""
        self.faker = faker
        self.template = template

    def __call__(self) -> str:
        """Generate a string based on the configured template."""
        return self.faker.numerify(self.template)


faker = Faker(FAKER_LOCALE)
person_gen_factory = PersonGeneratorFactory(faker)
phone_gen = NumberGenerator(faker, FAKER_PHONE_TEMPLATE)
apartment_gen = NumberGenerator(faker, APARTMENT_TEMPLATE)


class Dataclass(Protocol):
    """Protocol for dataclass-like classes."""

    __dataclass_fields__: ClassVar[dict[str, Field[Any]]]


_MISSING = cast(Any, object())
"""A sentinel to detect whether the field value was omitted."""


class DataclassBase:
    """Base class for dataclass-like behavior with field filtering."""

    @staticmethod
    @functools.cache
    def get_field_names(target_cls: type[Dataclass]) -> set[str]:
        """Return all dataclass field names for the target class."""
        return {field.name for field in fields(target_cls)}

    def filter_fields(self, target_cls: type[Dataclass]) -> dict[str, Any]:
        """Filter instance data to fields defined on the target dataclass."""
        return {
            field: value
            for field in self.get_field_names(target_cls)
            if (value := getattr(self, field)) is not None
        }

    def generate_field(self, attr: str, factory: Callable[[], object]) -> None:
        """Generate a missing field value using the provided factory.

        Args:
            attr (str): The attribute name.
            factory (Callable[[], object]): The factory to generate the value.
        """
        value = getattr(self, attr)
        if value is _MISSING:
            value = factory()
            setattr(self, attr, value)


@dataclass
class UserData(DataclassBase):
    """Dataclass for user registration data."""

    email: str = field(default_factory=faker.safe_email)
    password: str = field(default_factory=faker.password)

    first_name: str | None = _MISSING
    last_name: str | None = _MISSING
    company: str | None = field(default_factory=faker.company)
    position: str | None = _MISSING

    def __post_init__(self) -> None:
        """Populate missing user data fields after initialization."""
        # Use the same gender for generating the missing fields
        person_gen = person_gen_factory()
        self.generate_field('first_name', person_gen.first_name)
        self.generate_field('last_name', person_gen.last_name)
        self.generate_field('position', person_gen.job)


@dataclass
class ContactData(DataclassBase):
    """Dataclass for contact information data."""

    email: str | None = field(default_factory=faker.safe_email)
    phone: str = field(default_factory=phone_gen)

    first_name: str | None = _MISSING
    middle_name: str | None = _MISSING
    last_name: str | None = _MISSING

    city: str | None = field(default_factory=faker.city)
    street: str | None = field(default_factory=faker.street_name)
    house: str | None = field(default_factory=faker.building_number)
    structure: str | None = None
    building: str | None = None
    apartment: str | None = field(default_factory=apartment_gen)

    def __post_init__(self) -> None:
        """Fill missing contact name fields after initialization."""
        # Use the same gender for generating the missing fields
        person_gen = person_gen_factory()
        self.generate_field('first_name', person_gen.first_name)
        self.generate_field('middle_name', person_gen.middle_name)
        self.generate_field('last_name', person_gen.last_name)

    @classmethod
    def create_empty(cls):
        """Create a contact record without contact person info."""
        return cls(
            email=None,
            first_name=None,
            middle_name=None,
            last_name=None,
        )


def auth_header(user_token: str) -> dict[str, str]:
    """Build an authorization header for token-based API calls.

    Args:
        user_token (str): The user's authentication token.

    Returns:
        dict[str, str]: The authorization header dictionary.
    """
    return {'Authorization': f'Token {user_token}'}


def get_validation_error_codes(data: dict[str, Any], field: str) -> set[str]:
    """Extract validation error codes from a DRF error response.

    Args:
        data (dict[str, Any]): The error response payload.
        field (str): The field to inspect for errors.

    Returns:
        set[str]: The set of error codes found for the field.
    """
    errors: list[dict[str, str]] = data.get(field, [])
    return {error['code'] for error in errors}


def validation_codes_equal(data: dict[str, Any], field: str, *codes: str):
    """Compare expected validation codes against actual field errors."""
    expected_codes = set(codes)
    found_codes = get_validation_error_codes(data, field)
    return found_codes == expected_codes


def fail_if_error(response: httpx.Response) -> None:
    """Raise HTTP errors with the response body added to the message.

    Args:
        response (httpx.Response): The response to validate.

    Raises:
        HTTPStatusError: If the response status is not successful.
    """
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        message: str = e.args[0]
        try:
            data = response.json()
        except json.JSONDecodeError:
            data = response.text
        else:
            data = json.dumps(data, indent=4)
        e.args = (f'{message}\n\n{data}',)
        raise


def register_user(session: httpx.Client, user: UserData) -> bool:
    """Register a new user via the API if they do not already exist.

    Returns:
        bool: True if the user was created, False if the user already exists.
    """
    data = user.filter_fields(UserData)
    response = session.post(f'{API_ROOT}/user/register', data=data)
    if not response.is_success:
        if response.status_code == httpx.codes.BAD_REQUEST:
            json: dict[str, Any] = response.json()
            if validation_codes_equal(json, 'email', 'unique'):
                # User already exists => no registration needed
                return False
        fail_if_error(response)
    return True


def verify_email(session: httpx.Client, email: str) -> None:
    """Trigger email verification flow for a registered user.

    Args:
        session (httpx.Client): HTTP client to use for requests.
        email (str): Email address to verify.
    """
    # First request the email verification
    data = {'email': email}
    response = session.post(f'{API_ROOT}/user/register/verify', data=data)
    fail_if_error(response)
    json: dict[str, Any] = response.json()

    # We might have the token itself in the response
    try:
        verify_token = json['token']
    except KeyError as e:
        raise RuntimeError(
            f'Automatic verification works only in `DEBUG` server mode. '
            f'Please verify the user {email} manually.'
        ) from e

    # Got the token, now can verify
    data['token'] = verify_token
    response = session.post(f'{API_ROOT}/user/register/confirm', data=data)
    fail_if_error(response)


def login_user(session: httpx.Client, email: str, password: str) -> str:
    """Authenticate a user and return an API token."""
    data = {'email': email, 'password': password}
    response = session.post(f'{API_ROOT}/user/login', data=data)
    fail_if_error(response)
    json: dict[str, Any] = response.json()
    return json['token']


def get_contacts(
    session: httpx.Client,
    user_token: str,
) -> list[dict[str, Any]]:
    """Retrieve the authenticated user's contact list."""
    headers = auth_header(user_token)
    response = session.get(f'{API_ROOT}/user/contact', headers=headers)
    fail_if_error(response)
    return response.json()


def create_contact(
    session: httpx.Client,
    user_token: str,
    contact: ContactData,
) -> dict[str, Any]:
    """Create a new contact for the authenticated user."""
    data = contact.filter_fields(ContactData)
    headers = auth_header(user_token)
    response = session.post(
        f'{API_ROOT}/user/contact',
        data=data,
        headers=headers,
    )
    fail_if_error(response)
    return response.json()


def get_products(
    session: httpx.Client,
    user_token: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch publicly available product listings, optionally authenticated."""
    headers = user_token and auth_header(user_token) or None
    response = session.get(f'{API_ROOT}/products', headers=headers)
    fail_if_error(response)
    return response.json()


def get_basket(
    session: httpx.Client,
    user_token: str,
) -> dict[str, Any] | None:
    """Fetch the current user's basket if it exists."""
    headers = auth_header(user_token)
    response = session.get(f'{API_ROOT}/basket', headers=headers)
    if response.status_code == httpx.codes.NOT_FOUND:
        return None
    fail_if_error(response)
    return response.json()


def add_to_basket(
    session: httpx.Client,
    user_token: str,
    items: Iterable[Mapping[str, object]],
) -> dict[str, Any]:
    """Add items to the authenticated user's basket."""
    data = {'items': json.dumps(items)}
    headers = auth_header(user_token)
    response = session.post(f'{API_ROOT}/basket', data=data, headers=headers)
    fail_if_error(response)
    return response.json()


def delete_from_basket(
    session: httpx.Client,
    user_token: str,
    items: Iterable[int],
) -> None:
    """Delete specified items from the authenticated user's basket."""
    data = {'items': ','.join(map(str, items))}
    headers = auth_header(user_token)
    response = session.request(
        'DELETE',
        f'{API_ROOT}/basket',
        data=data,
        headers=headers,
    )
    fail_if_error(response)


def place_order(
    session: httpx.Client,
    user_token: str,
    order_id: object,
    contact_id: object,
) -> dict[str, Any]:
    """Place an order from the user's current basket."""
    data = {'id': order_id, 'contact': contact_id}
    headers = auth_header(user_token)
    response = session.post(f'{API_ROOT}/order', data=data, headers=headers)
    fail_if_error(response)
    return response.json()


def update_shop_pricing(
    session: httpx.Client,
    user_token: str,
    url: str,
) -> None:
    """Request shop pricing update from the partner API endpoint."""
    data = {'url': url}
    headers = auth_header(user_token)
    response = session.post(
        f'{API_ROOT}/partner/update',
        data=data,
        headers=headers,
    )
    fail_if_error(response)


def login(session: httpx.Client, user: UserData) -> str:
    """Authenticate the given test user and return an API token."""
    return login_user(session, user.email, user.password)


def create_user(session: httpx.Client, user: UserData) -> str:
    """Register and verify a user, then return their auth token."""
    if register_user(session, user):
        verify_email(session, user.email)
    return login(session, user)


def create_shop(session: httpx.Client, shop: UserData, shop_url: str) -> str:
    """Create a shop account and upload its pricing data."""
    token = create_user(session, shop)
    update_shop_pricing(session, token, shop_url)
    return token


def create_shop_template(
    session: httpx.Client,
    name: object,
    password: str,
    file: Path,
) -> str:
    """Build a shop payload from a local YAML file and create the shop."""
    shop = UserData(
        email=f'shop{name}@example.com',
        password=password,
        company=f'Shop {name}',
        position=f'Shop {name} admin',
    )
    shop_url = file.as_uri()
    return create_shop(session, shop, shop_url)


def create_default_shops(session: httpx.Client) -> list[str]:
    """Create default shops from the YAML files in the shop_data directory."""
    tokens = []
    for file in SHOP_DATA_DIR.iterdir():
        match = SHOP_DATA_NAME_REGEX.match(file.name)
        if name := match and match.group(1):
            token = create_shop_template(session, name, USER_PASSWORD, file)
            tokens.append(token)
    return tokens


def create_default_contacts(
    session: httpx.Client,
    user_token: str,
) -> list[dict[str, Any]]:
    """Create a set of default contacts for a user."""
    if CONTACTS_COUNT < 1:
        return []
    empty = ContactData.create_empty()
    contacts = [empty] + [ContactData() for _ in range(CONTACTS_COUNT - 1)]
    return [
        create_contact(session, user_token, contact) for contact in contacts
    ]


def create_default_users(
    session: httpx.Client,
    test_user: UserData,
) -> list[str]:
    """Create several default test users and their contacts."""
    tokens = []
    if USER_COUNT < 1:
        return tokens
    users = [test_user] + [UserData() for _ in range(USER_COUNT - 1)]
    for user in users:
        user_token = create_user(session, user)
        tokens.append(user_token)
        create_default_contacts(session, user_token)
    return tokens


def empty_basket(session: httpx.Client, user_token: str) -> None:
    """Remove all items from the authenticated user's basket."""
    if basket := get_basket(session, user_token):
        items = [item['id'] for item in basket['items']]
        delete_from_basket(session, user_token, items)


def fill_basket(session: httpx.Client, user_token: str) -> dict[str, Any]:
    """Fill the user's basket with a random selection of available offers."""
    offers = get_products(session, user_token)
    offers = random.sample(offers, min(FILL_BASKET_SIZE, len(offers)))
    items = [
        {
            'product_info': offer['id'],
            'quantity': random.randint(1, offer['quantity']),
        }
        for offer in offers
    ]
    return add_to_basket(session, user_token, items)


def create_all(session: httpx.Client, test_user: UserData):
    """Create default shops and users for end-to-end tests."""
    create_default_shops(session)
    create_default_users(session, test_user)


def make_order(session: httpx.Client, test_user: UserData):
    """Simulate a full order flow for a test user."""
    user_token = login(session, test_user)

    contacts = get_contacts(session, user_token)
    contact = random.choice(contacts)

    empty_basket(session, user_token)
    basket = fill_basket(session, user_token)
    place_order(session, user_token, basket['id'], contact['id'])


def main():
    """Run the example script to create users, shops, and place an order."""
    with httpx.Client(timeout=None) as session:
        test_user = UserData(email=USER_EMAIL, password=USER_PASSWORD)
        create_all(session, test_user)
        make_order(session, test_user)


if __name__ == '__main__':
    main()
