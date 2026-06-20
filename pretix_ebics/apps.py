from __future__ import annotations

from django.utils.translation import gettext_lazy as _
from typing_extensions import override

from . import __version__

try:
    from pretix.base.plugins import PLUGIN_LEVEL_ORGANIZER, PluginConfig
except ImportError:
    raise RuntimeError("Please use pretix 2026.3 or above to run this plugin!") from None


class PluginApp(PluginConfig):
    default = True
    name = "pretix_ebics"
    verbose_name = "EBICS"

    class PretixPluginMeta:
        name = _("EBICS")
        author = "Sweenu"
        description = _("Automatically import bank transfers over EBICS into pretix")
        visible = True
        version = __version__
        category = "INTEGRATION"
        compatibility = "pretix>=2026.3.0"
        level = PLUGIN_LEVEL_ORGANIZER

    @override
    def ready(self) -> None:
        from . import signals  # noqa: F401
