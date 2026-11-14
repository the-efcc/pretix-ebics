import inspect
from decimal import Decimal

import pytest
from django.utils import translation
from django.utils.timezone import now
from django_scopes import scopes_disabled
from pretix.base.models import Event, Order, Organizer


@pytest.hookimpl(hookwrapper=True)
def pytest_fixture_setup(fixturedef, request):
    if inspect.isgeneratorfunction(fixturedef.func):
        yield
    else:
        with scopes_disabled():
            yield


@pytest.fixture(autouse=True)
def reset_locale():
    translation.activate("en")


@pytest.fixture(autouse=True)
def disable_scopes():
    with scopes_disabled():
        yield


@pytest.fixture
def organizer():
    return Organizer.objects.create(name="Dummy", slug="dummy", plugins="pretix_ebics")


@pytest.fixture
def order(organizer):
    """A canceled order: banktransfer's own import refuses outgoing transfers for these."""
    event = Event.objects.create(
        organizer=organizer, name="Demo", slug="demo", date_from=now(), currency="EUR"
    )
    return Order.objects.create(
        code="ABC12",
        event=event,
        status=Order.STATUS_CANCELED,
        datetime=now(),
        expires=now(),
        total=Decimal("23.00"),
        sales_channel=organizer.sales_channels.get(identifier="web"),
    )
