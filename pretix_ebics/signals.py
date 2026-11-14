from __future__ import annotations

import logging
from typing import Any

from django.dispatch import receiver
from django.urls import resolve, reverse
from django.utils.translation import gettext_lazy as _
from django_scopes import scopes_disabled
from pretix.base.signals import periodic_task
from pretix.control.signals import nav_organizer
from pretix.helpers.periodic import minimum_interval

from .models import EBICSConnection
from .services import import_for_connection

logger = logging.getLogger(__name__)


# The periodic cronjob fires as often as every minute; statements change once a day.
# The throttle needs Redis or memcached: without one, every cron run imports.
@receiver(periodic_task, dispatch_uid="pretix_ebics_periodic_import")
@scopes_disabled()
@minimum_interval(minutes_after_success=60)
def run_ebics_imports(sender: Any, **kwargs: Any) -> None:
    connections = EBICSConnection.objects.filter(
        active=True, bank_keys_activated=True
    ).select_related("organizer")
    for conn in connections:
        # The plugin may have been disabled for the organizer since the setup.
        if "pretix_ebics" not in conn.organizer.get_plugins():
            continue
        try:
            import_for_connection(conn)
        except Exception:
            logger.exception("EBICS import failed for connection %s", conn.pk)


@receiver(nav_organizer, dispatch_uid="pretix_ebics_nav_organizer")
def ebics_nav_organizer(
    sender: Any, request: Any, organizer: Any, **kwargs: Any
) -> list[dict[str, Any]]:
    if not request.user.has_organizer_permission(
        organizer, "organizer.settings.general:write", request=request
    ):
        return []
    url = resolve(request.path_info)
    return [
        {
            "label": _("EBICS"),
            "url": reverse("plugins:pretix_ebics:list", kwargs={"organizer": organizer.slug}),
            "active": url.namespace == "plugins:pretix_ebics",
            "icon": "bank",
        }
    ]
