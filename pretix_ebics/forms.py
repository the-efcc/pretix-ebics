from __future__ import annotations

from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import EBICSConnection


class EBICSConnectionForm(forms.ModelForm):
    # fintech cannot store private keys with a passphrase shorter than 8 characters.
    passphrase = forms.CharField(
        label=_("Passphrase"),
        min_length=8,
        max_length=190,
        widget=forms.PasswordInput(render_value=True),
    )

    class Meta:
        model = EBICSConnection
        fields = [
            "name",
            "bank_name",
            "host_id",
            "partner_id",
            "user_id",
            "ebics_url",
            "ebics_version",
            "currency",
            "passphrase",
            "active",
        ]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if self.instance.keys_created:
            # The stored keys are encrypted with it: a new one would lock them for good.
            passphrase = self.fields["passphrase"]
            passphrase.disabled = True
            passphrase.widget.render_value = False
            passphrase.help_text = _(
                "The passphrase cannot be changed once the keys have been generated."
            )

    def clean_ebics_url(self) -> str:
        url = self.cleaned_data["ebics_url"]
        if not url.startswith("https://"):
            raise forms.ValidationError(_("The EBICS URL must start with https://"))
        return url
