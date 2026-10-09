from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.generic import DetailView, FormView, ListView, TemplateView

from core.audit import log as audit_log
from core.mixins import ADMIN_ROLES, AdminRequiredMixin, FrontDeskRequiredMixin

from .cards import add_months, issue_card, next_period
from .forms import (
    CardPriceFormSet,
    PatientRegistrationForm,
    PublicRegistrationForm,
    StaffPatientRegistrationForm,
)
from .models import CardType, Family, Patient
from .security import hit_rate_limit

SESSION_KEY = "new_card_number"


class RegistrationFormMixin:
    form_class = PatientRegistrationForm

    def form_valid(self, form):
        patient = form.save()
        renewal = patient.latest_card_renewal
        issued = getattr(form, "issued_renewal", None)
        # Shown once on the confirmation page
        self.request.session[SESSION_KEY] = {
            "card_number": patient.card_number,
            "username": patient.user.username,
            "name": patient.user.get_full_name(),
            "family_number": patient.family.family_number if patient.family_id else "",
            "card_label": "Family card" if patient.family_id else "Single card",
            "card_status": patient.card_status,
            "card_expires_on": renewal.expires_on.strftime("%d %b %Y") if renewal else "",
            "charged": str(issued.amount_charged) if issued else "",
        }
        return redirect("patients:registered")


class PatientRegisterView(RegistrationFormMixin, FormView):
    """Public self-registration for patients (rate limited, with a captcha)."""

    template_name = "patients/register.html"
    form_class = PublicRegistrationForm

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("accounts:dashboard")
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs

    def post(self, request, *args, **kwargs):
        # Every submission from an IP address counts, whether it succeeds or not.
        # Override in settings.py: REGISTRATION_RATE_LIMIT, REGISTRATION_RATE_WINDOW
        limit = getattr(settings, "REGISTRATION_RATE_LIMIT", 10)
        window = getattr(settings, "REGISTRATION_RATE_WINDOW", 3600)
        if hit_rate_limit(request, "register", limit, window):
            return render(request, "patients/rate_limited.html", status=429)
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        form.refresh_captcha()
        return super().form_invalid(form)


class StaffRegisterPatientView(FrontDeskRequiredMixin, RegistrationFormMixin, FormView):
    """Registration of a patient at the front desk (administrative staff and admins only)."""

    template_name = "patients/staff_register.html"
    form_class = StaffPatientRegistrationForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["registered_by"] = self.request.user
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        # e.g. /patients/new/?family=FAM000001 (the "Add family member" button)
        number = self.request.GET.get("family", "").strip()
        if number:
            initial.update(card_choice="join", family_number=number)
            family = Family.objects.filter(family_number__iexact=number).first()
            if family:
                initial["address"] = family.address
        return initial


class RegistrationCompleteView(TemplateView):
    template_name = "patients/registered.html"

    def get(self, request, *args, **kwargs):
        details = request.session.pop(SESSION_KEY, None)
        if not details:
            return redirect("accounts:login")
        # Staff see this page inside the normal layout, patients see the public one
        staff_view = request.user.is_authenticated and not request.user.is_patient
        context = self.get_context_data(
            card_number=details["card_number"],
            username=details["username"],
            family_number=details.get("family_number", ""),
            card_label=details.get("card_label", ""),
            card_status=details.get("card_status", "none"),
            card_expires_on=details.get("card_expires_on", ""),
            charged=details.get("charged", ""),
            patient_name=details["name"],
            staff_view=staff_view,
            base_template="base.html" if staff_view else "patients/public_base.html",
        )
        return self.render_to_response(context)


class PatientListView(AdminRequiredMixin, ListView):
    template_name = "patients/patient_list.html"
    context_object_name = "patients"
    paginate_by = 20

    def get_queryset(self):
        patients = Patient.objects.select_related("user", "family").order_by(
            "user__login_id"
        )
        self.query = self.request.GET.get("q", "").strip()
        if self.query:
            patients = patients.filter(
                Q(user__login_id__icontains=self.query)
                | Q(user__first_name__icontains=self.query)
                | Q(user__last_name__icontains=self.query)
                | Q(user__phone__icontains=self.query)
                | Q(family__family_number__icontains=self.query)
            )
        return patients

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["query"] = self.query
        return context


class PatientDetailView(AdminRequiredMixin, DetailView):
    template_name = "patients/patient_detail.html"
    context_object_name = "patient"

    def get_queryset(self):
        return Patient.objects.select_related("user", "family").prefetch_related(
            "allergies", "history"
        )

    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        # Viewing a patient's record (allergies, history) is audited
        audit_log(request.user, "patient_record_viewed", self.object,
                  patient=self.object, request=request)
        return response


class MyProfileView(LoginRequiredMixin, TemplateView):
    """A patient's own profile. Always loaded from request.user, never from a URL ID."""

    template_name = "patients/my_profile.html"

    def get(self, request, *args, **kwargs):
        if not request.user.is_patient:
            raise PermissionDenied
        patient = get_object_or_404(
            Patient.objects.select_related("family").prefetch_related(
                "allergies", "history"
            ),
            user=request.user,
        )
        return self.render_to_response(self.get_context_data(patient=patient))


class FamilyListView(AdminRequiredMixin, ListView):
    template_name = "patients/family_list.html"
    context_object_name = "families"
    paginate_by = 20

    def get_queryset(self):
        self.query = self.request.GET.get("q", "").strip()
        families = Family.objects.all()
        if self.query:
            matching = Family.objects.filter(
                Q(family_number__icontains=self.query)
                | Q(name__icontains=self.query)
                | Q(members__user__login_id__icontains=self.query)
                | Q(members__user__first_name__icontains=self.query)
                | Q(members__user__last_name__icontains=self.query)
            ).values("pk")
            families = families.filter(pk__in=matching)
        return families.annotate(member_count=Count("members")).order_by("family_number")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["query"] = self.query
        return context


class FamilyDetailView(AdminRequiredMixin, DetailView):
    template_name = "patients/family_detail.html"
    context_object_name = "family"

    def get_queryset(self):
        return Family.objects.prefetch_related(
            Prefetch("members", queryset=Patient.objects.select_related("user"))
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        members = list(self.object.members.all())
        members.sort(key=lambda m: (m.relationship != Patient.Relationship.HEAD, m.user.login_id))
        context["members"] = members
        return context


class CardDeskView(FrontDeskRequiredMixin, TemplateView):
    """Find a card by number, then issue or renew it. Shows no medical information."""

    template_name = "patients/card_desk.html"

    @staticmethod
    def lookup(number):
        number = number.strip()
        if not number:
            return None, None
        patient = (
            Patient.objects.select_related("user", "family")
            .filter(user__login_id__iexact=number)
            .first()
        )
        if patient:
            return patient, patient.family
        return None, Family.objects.filter(family_number__iexact=number).first()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        number = self.request.GET.get("number", "").strip()
        patient, family = self.lookup(number)
        context.update(number=number, searched=bool(number), patient=patient, family=family)
        context["is_admin"] = self.request.user.role in ADMIN_ROLES

        if patient or family:
            holder = family or patient
            card_type = CardType.for_kind(
                CardType.Kind.FAMILY if family else CardType.Kind.SINGLE
            )
            context.update(
                holder=holder,
                card_type=card_type,
                status=holder.card_status,
                expires_on=holder.card_expires_on,
                new_expiry=next_period(holder, card_type)[1],
            )
            if patient and not patient.family_id:
                family_type = CardType.for_kind(CardType.Kind.FAMILY)
                context.update(
                    family_type=family_type,
                    upgrade_expiry=add_months(timezone.localdate(), family_type.validity_months),
                )
        return context

    def post(self, request, *args, **kwargs):
        number = request.POST.get("number", "")
        action = request.POST.get("action", "renew")
        back = f"{reverse('patients:card_desk')}?{urlencode({'number': number})}"
        patient, family = self.lookup(number)

        if not (patient or family):
            messages.error(request, "No patient or family card has this number.")
            return redirect(back)

        upgrade = action == "upgrade"
        if upgrade and (patient is None or patient.family_id):
            messages.error(request, "Only a patient with a single card can move to a family card.")
            return redirect(back)

        kind = CardType.Kind.FAMILY if (upgrade or family) else CardType.Kind.SINGLE
        card_type = CardType.for_kind(kind)
        if card_type.fee > 0 and request.POST.get("fee_received") != "on":
            messages.error(
                request,
                f"Confirm that the card fee of \u20a6{card_type.fee:,.2f} has been received.",
            )
            return redirect(back)

        with transaction.atomic():
            if upgrade:
                holder = Family.objects.create(
                    name=f"{patient.user.last_name} family", address=patient.address
                )
                patient.family = holder
                patient.relationship = Patient.Relationship.HEAD
                patient.save(update_fields=["family", "relationship"])
            else:
                holder = family or patient
            renewal = issue_card(holder, received_by=request.user)

        messages.success(
            request,
            f"Card issued. It is valid until {renewal.expires_on:%d %b %Y} "
            f"(\u20a6{renewal.amount_charged:,.2f} charged).",
        )
        return redirect(back)


class CardPricesView(AdminRequiredMixin, TemplateView):
    """Admins set the card fees and how long each card lasts."""

    template_name = "patients/card_prices.html"

    def get_formset(self, data=None):
        CardType.ensure_defaults()
        return CardPriceFormSet(data, queryset=CardType.objects.order_by("-kind"))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["formset"] = kwargs.get("formset") or self.get_formset()
        return context

    def post(self, request, *args, **kwargs):
        formset = self.get_formset(request.POST)
        if formset.is_valid():
            formset.save()
            messages.success(request, "Card prices saved.")
            return redirect("patients:card_prices")
        return self.render_to_response(self.get_context_data(formset=formset))
