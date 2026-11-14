from __future__ import annotations

import logging
from typing import Any

from django.contrib import messages
from django.http import Http404, HttpResponse
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

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        # pretix checks this for a plugin's shop URLs, but not for its control URLs.
        if "pretix_ebics" not in request.organizer.get_plugins():
            raise Http404
        return super().dispatch(request, *args, **kwargs)

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
            # The button is hidden for these, but a page left open still has it.
            elif action == "import_now" and conn.is_ready:
                result = import_for_connection(conn)
                if result is None:
                    messages.warning(
                        request,
                        _(
                            "An import for this connection was started a moment ago. "
                            "Please try again in a few minutes."
                        ),
                    )
                else:
                    # The count includes the overlap days, which banktransfer skips again.
                    message = _(
                        "Fetched {n} transaction(s) from the bank. "
                        "New ones are now being matched to orders."
                    ).format(n=result.num_transactions)
                    if result.num_refunds:
                        message += " " + _("{n} refund(s) were marked as done.").format(
                            n=result.num_refunds
                        )
                    messages.success(request, message)
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
            # In the admin's language ("de-informal" -> "de"), not the server's.
            pdf = ebics.ini_letter_pdf(conn, lang=request.LANGUAGE_CODE[:2])
        except Exception as e:
            logger.exception("INI letter generation failed for connection %s", conn.pk)
            messages.error(
                request,
                _("Could not generate the INI letter: {error}").format(error=str(e)),
            )
            return redirect(self.list_url)
        # Inline by default so the key hashes can be read off the letter and pasted
        # into a bank portal; ?download=1 forces a file download instead.
        disposition = "attachment" if request.GET.get("download") else "inline"
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'{disposition}; filename="ini-letter-{conn.pk}.pdf"'
        return response
