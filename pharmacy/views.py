from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import CreateView, FormView, ListView, UpdateView

from cases import permissions as case_perms
from cases.models import Case
from core import audit

from . import permissions as perms
from . import services
from .forms import (
    AdjustStockForm, CloseForm, DispenseForm, DrugForm, PrescriptionFormSet,
    PrescriptionNoteForm, ReasonForm, ReceiveStockForm,
)
from .models import Drug, Prescription, StockBatch

PRESCRIPTION_QS = Prescription.objects.select_related(
    "case__department", "patient__user", "prescribed_by", "closed_by",
).prefetch_related("items__drug")


class PharmacyAreaMixin(LoginRequiredMixin):
    """Pharmacy staff, the head of the pharmacy, and admin roles only."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not perms.in_pharmacy_area(request.user):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class StockManagerMixin(LoginRequiredMixin):
    """Senior pharmacy staff, the head of the pharmacy, and admin roles."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not perms.can_manage_stock(request.user):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class FormPageMixin:
    template_name = "pharmacy/form.html"
    page_title = ""
    submit_label = "Save"
    cancel_url = None

    def get_cancel_url(self):
        return self.cancel_url or reverse("pharmacy:drugs")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title=self.page_title, submit_label=self.submit_label,
                       cancel_url=self.get_cancel_url())
        return context


# ---- Worklist ---------------------------------------------------------------------------

class WorklistView(PharmacyAreaMixin, ListView):
    template_name = "pharmacy/worklist.html"
    context_object_name = "prescriptions"
    paginate_by = 25

    def get_queryset(self):
        status = self.request.GET.get("status", "open")
        qs = PRESCRIPTION_QS
        if status == "open":
            qs = qs.filter(status__in=Prescription.OPEN_STATUSES)
        elif status in dict(Prescription.Status.choices):
            qs = qs.filter(status=status)
        else:
            status = "open"
            qs = qs.filter(status__in=Prescription.OPEN_STATUSES)
        self.status = status
        # Oldest first for the work queue, newest first when looking back
        return qs.order_by("prescribed_at") if status == "open" else qs.order_by("-prescribed_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(status=self.status, statuses=Prescription.Status.choices,
                       can_manage=perms.can_manage_stock(self.request.user))
        return context


# ---- Drug catalogue -----------------------------------------------------------------------

class DrugListView(PharmacyAreaMixin, View):
    def get(self, request):
        return render(request, "pharmacy/drug_list.html", {
            "drugs": services.drug_stock(),
            "can_manage": perms.can_manage_stock(request.user),
            "can_receive": perms.can_receive_stock(request.user),
        })


class DrugCreateView(StockManagerMixin, FormPageMixin, CreateView):
    form_class = DrugForm
    page_title = "New drug"

    def form_valid(self, form):
        response = super().form_valid(form)
        audit.log(self.request.user, "drug_created", self.object, detail=str(self.object),
                  request=self.request)
        messages.success(self.request, "Drug added to the catalogue.")
        return response

    def get_success_url(self):
        return reverse("pharmacy:drugs")


class DrugUpdateView(StockManagerMixin, FormPageMixin, UpdateView):
    form_class = DrugForm
    queryset = Drug.objects.all()

    @property
    def page_title(self):
        return f"Edit {self.object}"

    def form_valid(self, form):
        response = super().form_valid(form)
        audit.log(self.request.user, "drug_updated", self.object, detail=str(self.object),
                  request=self.request)
        messages.success(self.request, "Drug updated.")
        return response

    def get_success_url(self):
        return reverse("pharmacy:drugs")


# ---- Stock ------------------------------------------------------------------------------------

class StockView(PharmacyAreaMixin, ListView):
    template_name = "pharmacy/stock.html"
    context_object_name = "batches"
    paginate_by = 50

    def get_queryset(self):
        self.show_all = self.request.GET.get("show") == "all"
        qs = StockBatch.objects.select_related("drug").order_by("expiry_date", "id")
        return qs if self.show_all else qs.filter(quantity_remaining__gt=0)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            show_all=self.show_all,
            expiring=services.expiring_batches(),
            expired=services.expired_batches(),
            warning_days=services.EXPIRY_WARNING_DAYS,
            can_manage=perms.can_manage_stock(self.request.user),
            can_receive=perms.can_receive_stock(self.request.user),
        )
        return context


class ReceiveStockView(PharmacyAreaMixin, FormPageMixin, FormView):
    form_class = ReceiveStockForm
    page_title = "Receive stock"
    submit_label = "Add to stock"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not perms.can_receive_stock(request.user):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_cancel_url(self):
        return reverse("pharmacy:stock")

    def form_valid(self, form):
        data = form.cleaned_data
        try:
            services.receive_stock(data["drug"], data["batch_number"], data["expiry_date"],
                                   data["quantity"], self.request.user, data["notes"],
                                   request=self.request)
        except ValidationError as error:
            form.add_error(None, error)
            return self.form_invalid(form)
        messages.success(self.request, "Stock received.")
        return redirect("pharmacy:stock")


class AdjustStockView(StockManagerMixin, FormPageMixin, FormView):
    form_class = AdjustStockForm
    submit_label = "Save adjustment"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        self.batch = get_object_or_404(StockBatch.objects.select_related("drug"), pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    @property
    def page_title(self):
        return f"Adjust {self.batch} ({self.batch.quantity_remaining} remaining)"

    def get_cancel_url(self):
        return reverse("pharmacy:stock")

    def form_valid(self, form):
        data = form.cleaned_data
        try:
            services.adjust_stock(self.batch, data["change"], data["reason"], data["note"],
                                  self.request.user, request=self.request)
        except ValidationError as error:
            form.add_error(None, error)
            return self.form_invalid(form)
        messages.success(self.request, "Stock adjusted.")
        return redirect("pharmacy:stock")


# ---- Prescribing (assigned doctor or department head) -------------------------------------------

class PrescribeView(LoginRequiredMixin, View):
    template_name = "pharmacy/prescribe.html"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        self.case = get_object_or_404(
            Case.objects.select_related("patient__user", "department"), pk=kwargs["case_pk"]
        )
        if not case_perms.can_view(request.user, self.case):
            raise Http404
        if not perms.can_prescribe(request.user, self.case):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def page(self, request, formset, note_form, allergy_warning=""):
        return render(request, self.template_name, {
            "case": self.case,
            "formset": formset,
            "note_form": note_form,
            "allergy_warning": allergy_warning,
            "allergies": self.case.patient.allergies.all(),
            "no_drugs": not Drug.objects.filter(is_active=True).exists(),
        })

    def get(self, request, case_pk):
        return self.page(request, PrescriptionFormSet(), PrescriptionNoteForm())

    def post(self, request, case_pk):
        formset = PrescriptionFormSet(request.POST)
        note_form = PrescriptionNoteForm(request.POST)
        if formset.is_valid() and note_form.is_valid():
            items = [form.cleaned_data for form in formset.forms if form.cleaned_data]
            try:
                services.prescribe(
                    self.case, items, request.user, note_form.cleaned_data["note"],
                    acknowledged=note_form.cleaned_data["acknowledge_allergy"], request=request,
                )
            except services.AllergyWarning as error:
                return self.page(request, formset, note_form, allergy_warning=" ".join(error.messages))
            except ValidationError as error:
                note_form.add_error(None, error)
            else:
                messages.success(request, "Prescription sent to the pharmacy.")
                return redirect("cases:detail", pk=self.case.pk)
        return self.page(request, formset, note_form)


# ---- A single prescription ------------------------------------------------------------------------

def get_prescription_for(user, pk):
    prescription = get_object_or_404(PRESCRIPTION_QS, pk=pk)
    if not perms.can_view(user, prescription):
        raise Http404  # do not reveal that it exists
    return prescription


class PrescriptionDetailView(LoginRequiredMixin, View):
    def get(self, request, pk):
        prescription = get_prescription_for(request.user, pk)
        user = request.user
        if not user.is_patient:  # staff access to a prescription is audited
            audit.log(user, "prescription_viewed", prescription, patient=prescription.patient,
                      request=request)
        if user.is_patient:
            back_url = reverse("pharmacy:mine")
        elif perms.is_pharmacy_staff(user) or perms.is_pharmacy_head(user):
            back_url = reverse("pharmacy:worklist")  # they cannot open the case page
        else:
            back_url = reverse("cases:detail", args=[prescription.case_id])
        context = {
            "prescription": prescription,
            "back_url": back_url,
            "is_patient_view": user.is_patient,
            "can_cancel": perms.can_cancel(user, prescription),
            "can_close": perms.can_close(user, prescription),
            "cancel_form": ReasonForm(),
            "close_form": CloseForm(),
        }
        if not user.is_patient:
            drugs = [item.drug for item in prescription.items.all()]
            conflicts = services.allergy_conflicts(prescription.patient, drugs)
            context["allergies"] = prescription.patient.allergies.all()
            context["allergy_conflicts"] = conflicts
        if perms.can_dispense(user, prescription):
            form = DispenseForm(prescription=prescription)
            available = {d.pk: d.available for d in services.drug_stock()}
            context["dispense_form"] = form
            context["dispense_rows"] = [
                (item, form[name], available.get(item.drug_id, 0)) for item, name in form.item_fields
            ]
        return render(request, "pharmacy/prescription_detail.html", context)


class PrescriptionActionView(LoginRequiredMixin, View):
    """POST-only base: permission check, validate form, call the service."""

    http_method_names = ["post"]
    form_class = None
    success_text = "Updated."

    def check(self, user, prescription):
        raise NotImplementedError

    def run(self, request, prescription, form):
        raise NotImplementedError

    def build_form(self, request, prescription):
        return self.form_class(request.POST) if self.form_class else None

    def post(self, request, pk):
        prescription = get_prescription_for(request.user, pk)
        if not self.check(request.user, prescription):
            raise PermissionDenied
        form = self.build_form(request, prescription)
        if form is not None and not form.is_valid():
            messages.error(request, "Please check the form and try again.")
        else:
            try:
                self.run(request, prescription, form)
                messages.success(request, self.success_text)
            except services.AllergyWarning as error:
                messages.error(request, " ".join(error.messages)
                               + " Tick the box to confirm and try again.")
            except ValidationError as error:
                messages.error(request, " ".join(error.messages))
        return redirect("pharmacy:prescription", pk=prescription.pk)


class DispenseView(PrescriptionActionView):
    success_text = "Dispensed. The stock has been updated."
    check = staticmethod(perms.can_dispense)

    def build_form(self, request, prescription):
        return DispenseForm(request.POST, prescription=prescription)

    def run(self, request, prescription, form):
        services.dispense(prescription, form.quantities(), request.user,
                          acknowledged=form.cleaned_data["acknowledge_allergy"], request=request)


class CancelView(PrescriptionActionView):
    form_class = ReasonForm
    success_text = "Prescription cancelled."
    check = staticmethod(perms.can_cancel)

    def run(self, request, prescription, form):
        services.cancel_prescription(prescription, request.user, form.cleaned_data["reason"],
                                     request=request)


class CloseView(PrescriptionActionView):
    form_class = CloseForm
    success_text = "Prescription closed."
    check = staticmethod(perms.can_close)

    def run(self, request, prescription, form):
        services.close_prescription(prescription, request.user, form.cleaned_data["reason"],
                                    request=request)


# ---- Patient's own prescriptions --------------------------------------------------------------------

class MyPrescriptionsView(LoginRequiredMixin, View):
    def get(self, request):
        patient = case_perms.get_patient(request.user)
        if not request.user.is_patient or patient is None:
            raise PermissionDenied
        prescriptions = (
            Prescription.objects.filter(patient=patient)
            .select_related("prescribed_by").prefetch_related("items__drug")
            .order_by("-prescribed_at")
        )
        return render(request, "pharmacy/my_prescriptions.html", {"prescriptions": prescriptions})