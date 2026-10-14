"""
Builds the data for the role-based dashboard.

Rules (same as the rest of the portal):
- Everything is loaded from the logged-in user, never from an ID in the URL.
- Each role gets only the data it is allowed to see.
- Support staff get no patient or case data at all.
- Other apps are imported inside the functions to avoid circular imports.
"""
from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.utils import timezone


def build_dashboard(user):
    dash = _role_dashboard(user)
    # Staff with a staff profile also get the clock in / clock out panel
    if not user.is_patient and getattr(user, "staff_profile", None) is not None:
        from attendance import services as attendance_services

        dash["attendance"] = attendance_services.panel_for(user)
    return dash


def _role_dashboard(user):
    from cases import permissions as perms

    if perms.is_admin(user):
        return _admin()
    if user.is_patient:
        return _patient(user)
    from laboratory import permissions as lab_perms

    if lab_perms.is_lab_staff(user):
        return _lab()
    from pharmacy import permissions as pharmacy_perms

    if pharmacy_perms.is_pharmacy_staff(user):
        return _pharmacy()
    if perms.headed_department(user):
        return _head(user)
    if perms.is_general_staff(user):
        return _general()
    if perms.is_medical(user):
        return _medical(user)
    profile = getattr(user, "staff_profile", None)
    if profile and profile.category == "admin":
        dash = {"kind": "front_desk", "title": "Front desk"}
        if profile.records_officer:
            from datarequests.models import DataRequest

            dash["open_requests"] = DataRequest.objects.filter(
                status__in=["open", "in_review"]).count()
        return dash
    if profile and profile.category == "support":
        return {"kind": "support", "title": "Your duties"}
    return {"kind": "other", "title": "Welcome"}


def _admin():
    from cases.models import Case
    from core.models import AuditLog
    from core.models import LoginThrottle
    from datarequests.models import DataRequest
    from facilities.models import Admission, Bed
    from patients.models import Patient

    User = get_user_model()
    counts = Case.objects.aggregate(
        total=Count("id"),
        awaiting_triage=Count("id", filter=Q(status="pending", routed_at__isnull=True)),
        awaiting_assignment=Count("id", filter=Q(status="pending", routed_at__isnull=False)),
        assigned=Count("id", filter=Q(status="assigned")),
        in_treatment=Count("id", filter=Q(status="in_treatment")),
        completed=Count("id", filter=Q(status="completed")),
    )
    beds = Bed.objects.aggregate(
        total=Count("id"), occupied=Count("id", filter=Q(is_occupied=True))
    )
    beds["free"] = beds["total"] - beds["occupied"]
    return {
        "kind": "admin",
        "title": "Hospital overview",
        "counts": counts,
        "beds": beds,
        "admitted": Admission.objects.filter(discharged_at__isnull=True).count(),
        "open_requests": DataRequest.objects.filter(status__in=["open", "in_review"]).count(),
        "locked_accounts": LoginThrottle.objects.filter(locked_until__gt=timezone.now()).count(),
        "patients": Patient.objects.count(),
        "staff": User.objects.exclude(role=User.Role.PATIENT).filter(is_active=True).count(),
        "recent_audit": list(AuditLog.objects.all()[:8]),
    }


def _head(user):
    from cases.models import Case
    from cases.permissions import headed_department
    from facilities.models import Admission

    User = get_user_model()
    dept = headed_department(user)
    routed = Case.objects.filter(department=dept, routed_at__isnull=False)
    counts = routed.aggregate(
        awaiting=Count("id", filter=Q(status="pending")),
        assigned=Count("id", filter=Q(status="assigned")),
        in_treatment=Count("id", filter=Q(status="in_treatment")),
        completed=Count("id", filter=Q(status="completed")),
    )
    return {
        "kind": "head",
        "title": f"{dept.name} department",
        "department": dept,
        "counts": counts,
        "waiting": list(
            routed.filter(status="pending").select_related("patient__user")
            .order_by("created_at")[:5]
        ),
        "team": User.objects.filter(is_active=True, staff_profile__department=dept).count(),
        "admitted": Admission.objects.filter(
            case__department=dept, discharged_at__isnull=True
        ).count(),
    }


def _general():
    from cases.models import Case

    queue = Case.objects.filter(status="pending", routed_at__isnull=True)
    return {
        "kind": "general",
        "title": "Triage",
        "waiting_count": queue.count(),
        "waiting": list(queue.select_related("patient__user", "department")
                        .order_by("created_at")[:5]),
    }


def _medical(user):
    from cases.models import Case
    from facilities.models import Admission, WardAssignment

    mine = Case.objects.filter(assigned_to=user)
    counts = mine.aggregate(
        assigned=Count("id", filter=Q(status="assigned")),
        in_treatment=Count("id", filter=Q(status="in_treatment")),
        completed=Count("id", filter=Q(status="completed")),
    )
    return {
        "kind": "medical",
        "title": "My patients",
        "counts": counts,
        "active": list(
            mine.filter(status__in=["assigned", "in_treatment"])
            .select_related("patient__user", "department").order_by("created_at")[:5]
        ),
        "admitted": Admission.objects.filter(
            case__assigned_to=user, discharged_at__isnull=True
        ).count(),
        "has_wards": WardAssignment.objects.filter(user=user).exists(),
        "ward_patients": Admission.objects.filter(
            discharged_at__isnull=True, bed__ward__assignments__user=user
        ).count(),
    }


def _lab():
    from laboratory.models import LabResult

    counts = LabResult.objects.aggregate(
        ordered=Count("id", filter=Q(status="ordered")),
        resulted=Count("id", filter=Q(status="resulted")),
        released=Count("id", filter=Q(status="released")),
    )
    return {
        "kind": "lab",
        "title": "Laboratory",
        "counts": counts,
        "waiting": list(
            LabResult.objects.filter(status="ordered")
            .select_related("patient__user", "test").order_by("ordered_at")[:5]
        ),
    }


def _pharmacy():
    from pharmacy import services as pharmacy_services
    from pharmacy.models import Prescription

    counts = Prescription.objects.aggregate(
        waiting=Count("id", filter=Q(status="prescribed")),
        partly=Count("id", filter=Q(status="partly_dispensed")),
    )
    return {
        "kind": "pharmacy",
        "title": "Pharmacy",
        "counts": counts,
        "low_stock": pharmacy_services.low_stock_count(),
        "expiring": pharmacy_services.expiring_batches().count(),
        "waiting": list(
            Prescription.objects.filter(status__in=["prescribed", "partly_dispensed"])
            .select_related("patient__user").order_by("prescribed_at")[:5]
        ),
    }


def _patient(user):
    from cases.models import Case
    from cases.permissions import get_patient
    from laboratory.models import LabResult
    from pharmacy.models import Prescription

    patient = get_patient(user)
    results_count = 0
    prescriptions_count = 0
    if patient is not None:
        results_count = LabResult.objects.filter(patient=patient, status="released").count()
        prescriptions_count = Prescription.objects.filter(patient=patient).count()
    cases = Case.objects.none()
    if patient is not None:
        cases = Case.objects.filter(patient=patient).select_related("department", "assigned_to")
    return {
        "kind": "patient",
        "title": "My health portal",
        "patient": patient,
        "open_count": cases.exclude(status="completed").count(),
        "results_count": results_count,
        "prescriptions_count": prescriptions_count,
        "cases": list(cases[:5]),
    }
