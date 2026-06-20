from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _
from django_scopes import ScopedManager
from typing_extensions import override


class EBICSConnection(models.Model):
    """An EBICS connection to a single bank account, owned by one organizer.

    The connection also carries the EBICS key material: ``keyring_data`` holds the
    JSON keyring produced by the ``fintech`` library, in which the private keys are
    encrypted with ``passphrase``. The pretix database is the trust boundary.
    """

    EBICS_VERSION_H004 = "H004"
    EBICS_VERSION_H005 = "H005"
    EBICS_VERSION_CHOICES = (
        (EBICS_VERSION_H004, _("EBICS 2.5 (H004)")),
        (EBICS_VERSION_H005, _("EBICS 3.0 (H005)")),
    )

    organizer = models.ForeignKey(
        "pretixbase.Organizer",
        related_name="ebics_connections",
        on_delete=models.CASCADE,
    )
    name = models.CharField(max_length=190, verbose_name=_("Name"))
    bank_name = models.CharField(max_length=190, blank=True, verbose_name=_("Bank name"))

    host_id = models.CharField(max_length=190, verbose_name=_("Host ID"))
    partner_id = models.CharField(max_length=190, verbose_name=_("Partner ID"))
    user_id = models.CharField(max_length=190, verbose_name=_("User ID"))
    ebics_url = models.URLField(verbose_name=_("EBICS URL"))
    ebics_version = models.CharField(
        max_length=4,
        choices=EBICS_VERSION_CHOICES,
        default=EBICS_VERSION_H004,
        verbose_name=_("EBICS version"),
    )
    currency = models.CharField(max_length=10, default="EUR", verbose_name=_("Currency"))
    active = models.BooleanField(default=True, verbose_name=_("Active"))

    # Key-exchange progress (see the key-exchange flow in AGENTS.md).
    keys_created = models.BooleanField(default=False)
    ini_sent = models.BooleanField(default=False)
    hia_sent = models.BooleanField(default=False)
    bank_keys_activated = models.BooleanField(default=False)

    # Secrets. Private keys inside keyring_data are encrypted with passphrase.
    keyring_data = models.TextField(blank=True, default="")
    passphrase = models.CharField(max_length=190, blank=True, default="")

    last_imported_date = models.DateField(null=True, blank=True)
    created = models.DateTimeField(auto_now_add=True)

    objects = ScopedManager(organizer="organizer")

    class Meta:
        ordering = ("name", "pk")

    @override
    def __str__(self) -> str:
        return f"{self.name} ({self.organizer.slug})"

    @property
    def keys_sent(self) -> bool:
        """Whether both public-key transfers (INI and HIA) have been sent."""
        return bool(self.ini_sent and self.hia_sent)

    @property
    def is_ready(self) -> bool:
        """Whether the connection is fully set up and may be used for imports."""
        return bool(self.active and self.bank_keys_activated)
