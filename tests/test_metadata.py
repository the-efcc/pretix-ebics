from pretix_ebics import __version__
from pretix_ebics.apps import PluginApp


def test_version_is_a_string():
    assert isinstance(__version__, str)
    assert __version__


def test_plugin_metadata():
    meta = PluginApp.PretixPluginMeta
    assert PluginApp.name == "pretix_ebics"
    assert str(meta.name) == "EBICS"
    assert meta.category == "INTEGRATION"
    assert str(meta.version) == __version__
