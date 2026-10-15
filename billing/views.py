from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core import audit
from patients.models import Patient

from . import permissions, services
from .forms import ChargeItemForm, InvoiceForm, LineFormSet, PaymentForm, VoidForm
from .models import ChargeItem, Invoice


def _find_patient(card):
    """Find an active patient by card number (PAT000001), which is the patient's login ID."""
    return (
        Patient.objects.select_related("user")
        .filter(user__login_id__iexact=card, user__is_active=True)
        .first()
    )


def _errors(request, exc):
    messages.error(request, " ".join(exc.messages))


@login_required
def home(request):
    if request.user.role == "patient":
        return redirect("billing:mine")
    if permissions.can_open_staff_list(request.user):
        return redirect("billing:invoice_list")
    raise PermissionDenied


# ---------- patient ----------

@login_required
def mine(request):
    patient = permissions.patient_of(request.user)
    if patient is None:
        raise PermissionDenied
    invoices = Invoice.objects.filter(patient=patient)
    owing = sum((i.balance for i in invoices if i.status == Invoice.Status.OPEN), 0)
    return render(request, "billing/mine.html", {"invoices": invoices, "owing": owing})


# ---------- staff list ----------

@login_required
def invoice_list(request):
    user = request.user
    if not permissions.can_open_staff_list(user):
        raise PermissionDenied
    qs = permissions.visible_invoices(user)

    status = request.GET.get("status", "")
    if status in Invoice.Status.values:
        qs = qs.filter(status=status)
    else:
        status = ""

    q = request.GET.get("q", "").strip()[:30]
    if q:
        qs = qs.filter(Q(number__icontains=q) | Q(patient__user__login_id__icontains=q))

    rows = list(qs[:200])
    audit.log(user, "invoice_list_viewed", user, detail=f"Filter: {status} {q}".strip(), request=request)
    return render(request, "billing/list.html", {
        "rows": rows, "status": status, "q": q, "statuses": Invoice.Status.choices,
        "truncated": len(rows) == 200, "can_manage_prices": permissions.can_manage_prices(user),
    })


# ---------- new invoice (front desk) ----------

@login_required
def invoice_new(request):
    user = request.user
    if not permissions.is_cashier(user):
        raise PermissionDenied
    card = (request.POST.get("patient") or request.GET.get("patient") or "").strip()
    patient = _find_patient(card) if card else None
    if card and patient is None:
        messages.error(request, "No active patient found with that card number.")

    invoice_form = formset = None
    if patient is not None:
        if request.method == "POST":
            invoice_form = InvoiceForm(request.POST, patient=patient)
            formset = LineFormSet(request.POST, prefix="lines")
            if invoice_form.is_valid() and formset.is_valid():
                lines = [
                    (f.cleaned_data["item"], f.cleaned_data["quantity"])
                    for f in formset if f.cleaned_data.get("item")
                ]
                try:
                    invoice = services.create_invoice(
                        patient, lines, user, case=invoice_form.cleaned_data["case"],
                        note=invoice_form.cleaned_data["note"], request=request,
                    )
                except ValidationError as exc:
                    invoice_form.add_error(None, exc)
                else:
                    messages.success(request, "The invoice has been created.")
                    return redirect("billing:detail", pk=invoice.pk)
        else:
            invoice_form = InvoiceForm(patient=patient)
            formset = LineFormSet(prefix="lines")

    return render(request, "billing/new.html", {
        "patient": patient, "patient_card": card, "invoice_form": invoice_form, "formset": formset,
        "has_prices": ChargeItem.objects.filter(is_active=True).exists(),
    })


# ---------- one invoice ----------

def _get_visible(request, pk):
    invoice = get_object_or_404(
        Invoice.objects.select_related("patient__user", "case", "issued_by", "voided_by"), pk=pk
    )
    if not permissions.can_view(request.user, invoice):
        raise Http404  # do not reveal that it exists
    return invoice


@login_required
def detail(request, pk):
    invoice = _get_visible(request, pk)
    user = request.user
    if not permissions.is_own_patient(user, invoice):
        audit.log(user, "invoice_viewed", invoice, patient=invoice.patient, request=request)
    return render(request, "billing/detail.html", {
        "invoice": invoice,
        "lines": invoice.lines.all(),
        "payments": invoice.payments.select_related("received_by"),
        "by_patient": permissions.is_own_patient(user, invoice),
        "can_pay": permissions.can_record_payment(user, invoice),
        "can_void": permissions.can_void(user, invoice),
        "payment_form": PaymentForm(initial={"amount": invoice.balance}),
        "void_form": VoidForm(),
    })


@login_required
@require_POST
def pay(request, pk):
    invoice = _get_visible(request, pk)
    form = PaymentForm(request.POST)
    if form.is_valid():
        cd = form.cleaned_data
        try:
            payment = services.record_payment(
                invoice, cd["amount"], cd["method"], cd["reference"], request.user, note=cd["note"], request=request
            )
        except ValidationError as exc:
            _errors(request, exc)
        else:
            messages.success(request, f"Payment recorded. Receipt {payment.receipt_number}.")
    else:
        messages.error(request, "Check the amount and the payment method.")
    return redirect("billing:detail", pk=invoice.pk)


@login_required
@require_POST
def void(request, pk):
    invoice = _get_visible(request, pk)
    form = VoidForm(request.POST)
    if form.is_valid():
        try:
            services.void_invoice(invoice, request.user, form.cleaned_data["reason"], request=request)
        except ValidationError as exc:
            _errors(request, exc)
        else:
            messages.success(request, "The invoice has been voided.")
    else:
        messages.error(request, "Give a reason (up to 300 characters) for voiding the invoice.")
    return redirect("billing:detail", pk=invoice.pk)


@login_required
def invoice_print(request, pk):
    invoice = _get_visible(request, pk)
    audit.log(request.user, "invoice_printed", invoice, patient=invoice.patient, request=request)
    return render(request, "billing/print.html", {
        "invoice": invoice,
        "lines": invoice.lines.all(),
        "payments": invoice.payments.select_related("received_by"),
        "hospital_name": getattr(settings, "HOSPITAL_NAME", "Hospital"),
    })


# ---------- price list ----------

@login_required
def items(request):
    user = request.user
    if not permissions.is_cashier(user):
        raise PermissionDenied
    return render(request, "billing/prices.html", {
        "items": ChargeItem.objects.all(), "can_manage_prices": permissions.can_manage_prices(user),
    })


@login_required
def item_form(request, pk=None):
    user = request.user
    if not permissions.can_manage_prices(user):
        raise PermissionDenied
    item = get_object_or_404(ChargeItem, pk=pk) if pk else None
    form = ChargeItemForm(request.POST or None, instance=item)
    if request.method == "POST" and form.is_valid():
        try:
            services.save_item(form.save(commit=False), user, request=request)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "The price list has been updated.")
            return redirect("billing:items")
    return render(request, "billing/price_form.html", {"form": form, "item": item})
