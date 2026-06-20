from __future__ import annotations

import logging
from typing import Any

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, DeleteView, ListView, UpdateView, View
from django_scopes import scopes_disabled
from pretix.control.permissions import OrganizerPermissionRequiredMixin
from pretix.control.views.organizer import OrganizerDetailViewMixin

from . import ebics
from .forms import EBICSConnectionForm
from .models import EBICSConnection
from .services import import_for_connection

logger = logging.getLogger(__name__)

PERMISSION = "organizer.settings.general:write"

# action name (an ebics.<name> callable) -> success message
KEY_ACTIONS = {
    "create_keys": _("EBICS keys have been generated."),
    "send_ini": _("The signature key has been sent to the bank (INI)."),
    "send_hia": _("The authentication and encryption keys have been sent (HIA)."),
    "activate_bank_keys": _("The bank keys have been downloaded and activated."),
}


class EBICSBaseMixin(OrganizerDetailViewMixin, OrganizerPermissionRequiredMixin):
    permission = PERMISSION

    def get_queryset(self):
        with scopes_disabled():
            return EBICSConnection.objects.filter(organizer=self.request.organizer)

    @property
    def list_url(self) -> str:
        return reverse(
            "plugins:pretix_ebics:list",
            kwargs={"organizer": self.request.organizer.slug},
        )


class ConnectionListView(EBICSBaseMixin, ListView):
    model = EBICSConnection
    template_name = "pretix_ebics/index.html"
    context_object_name = "connections"


class ConnectionCreateView(EBICSBaseMixin, CreateView):
    model = EBICSConnection
    form_class = EBICSConnectionForm
    template_name = "pretix_ebics/form.html"

    def form_valid(self, form: EBICSConnectionForm) -> HttpResponse:
        form.instance.organizer = self.request.organizer
        messages.success(self.request, _("The connection has been created."))
        return super().form_valid(form)

    def get_success_url(self) -> str:
        return self.list_url


class ConnectionUpdateView(EBICSBaseMixin, UpdateView):
    model = EBICSConnection
    form_class = EBICSConnectionForm
    template_name = "pretix_ebics/form.html"
    context_object_name = "connection"

    def get_object(self, queryset: Any = None) -> EBICSConnection:
        return get_object_or_404(self.get_queryset(), pk=self.kwargs["pk"])

    def form_valid(self, form: EBICSConnectionForm) -> HttpResponse:
        messages.success(self.request, _("Your changes have been saved."))
        return super().form_valid(form)

    def get_success_url(self) -> str:
        return self.list_url


class ConnectionDeleteView(EBICSBaseMixin, DeleteView):
    model = EBICSConnection
    template_name = "pretix_ebics/delete.html"
    context_object_name = "connection"

    def get_object(self, queryset: Any = None) -> EBICSConnection:
        return get_object_or_404(self.get_queryset(), pk=self.kwargs["pk"])

    def get_success_url(self) -> str:
        messages.success(self.request, _("The connection has been deleted."))
        return self.list_url


class ConnectionActionView(EBICSBaseMixin, View):
    def post(self, request: Any, *args: Any, **kwargs: Any) -> HttpResponse:
        conn = get_object_or_404(self.get_queryset(), pk=kwargs["pk"])
        action = request.POST.get("action", "")
        try:
            if action in KEY_ACTIONS:
                getattr(ebics, action)(conn)
                conn.save()
                messages.success(request, KEY_ACTIONS[action])
            elif action == "import_now":
                result = import_for_connection(conn)
                messages.success(
                    request,
                    _("Imported {n} transaction(s).").format(n=result.num_transactions),
                )
            else:
                messages.error(request, _("Unknown action."))
        except Exception as e:
            logger.exception("EBICS action %s failed for connection %s", action, conn.pk)
            messages.error(request, _("The operation failed: {error}").format(error=str(e)))
        return redirect(self.list_url)


class IniLetterView(EBICSBaseMixin, View):
    def get(self, request: Any, *args: Any, **kwargs: Any) -> HttpResponse:
        conn = get_object_or_404(self.get_queryset(), pk=kwargs["pk"])
        try:
            pdf = ebics.ini_letter_pdf(conn)
            conn.save(update_fields=["keyring_data"])
        except Exception as e:
            logger.exception("INI letter generation failed for connection %s", conn.pk)
            messages.error(
                request,
                _("Could not generate the INI letter: {error}").format(error=str(e)),
            )
            return redirect(self.list_url)
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="ini-letter-{conn.pk}.pdf"'
        return response
