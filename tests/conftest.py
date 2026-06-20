import inspect

import pytest
from django.test import RequestFactory
from django.utils import translation
from django.utils.timezone import now
from django_scopes import scopes_disabled
from pretix.base.models import Event, Organizer


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
def no_messages(monkeypatch):
    monkeypatch.setattr("django.contrib.messages.api.add_message", lambda *args, **kwargs: None)


@pytest.fixture(autouse=True)
def disable_scopes():
    with scopes_disabled():
        yield


@pytest.fixture
def rf():
    return RequestFactory()


@pytest.fixture
def organizer():
    return Organizer.objects.create(name="Dummy", slug="dummy")


@pytest.fixture
def event(organizer):
    return Event.objects.create(
        organizer=organizer,
        name="Dummy",
        slug="dummy",
        date_from=now(),
        live=True,
        plugins="pretix_ebics",
    )
