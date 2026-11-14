import inspect

import pytest
from django.utils import translation
from django_scopes import scopes_disabled
from pretix.base.models import Organizer


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
