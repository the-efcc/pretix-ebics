from __future__ import annotations

from django import forms

from .models import EBICSConnection


class EBICSConnectionForm(forms.ModelForm):
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
        widgets = {
            "passphrase": forms.PasswordInput(render_value=True),
        }
