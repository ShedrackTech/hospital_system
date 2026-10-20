# Hospital Management System: System Design and Handoff

> **For any AI or developer continuing this project: read this whole file before writing code.**
> It records the concept, the decisions made with the developer (Shedy), what is built and tested,
> the code contracts between apps, the mistakes already made (Section 12), and what to build next (Section 14).
> Last updated: 14 October 2026. Last confirmed full test run: **410 tests passing** (14 October 2026), covering every app marked Built in Section 5, including pharmacy and appointments.

---

## 1. Working rules (developer preferences, non-negotiable)

- **Give complete updated files**, not partial snippets. Make **minimal, targeted changes**; never rewrite working code without a reason.
- **Stack:** Django 6.1, Python 3.14, PostgreSQL, HTML/CSS, vanilla JavaScript. **No JS framework.** The developer is still learning DRF, so use plain Django views and templates.
- The developer works on **Windows (cmd, venv)**. Give Windows commands. Project folder: `C:\Users\USER-PC\hospital_system`.
- **One app per responsibility.** Each app has `models.py`, `admin.py`, `views.py`, `urls.py`, `forms.py`, `tests.py` (more files such as `services.py` are fine). **Every app folder needs an `__init__.py`.**
- **Django admin is registered in every app** (`list_display`, `search_fields`, `list_filter`), **but the developer wants all everyday admin work done in the hospital portal.** Django admin is a backup only. Build portal pages (CRUD) for anything an admin must do.
- Deliver **one piece at a time, tested, as a zip**, with exact Windows commands (Section 15).
- The developer **pastes terminal output** to report problems. Ask for output from the first `ERROR` or `FAIL` line onward.
- Location: Nigeria. Nigeria Data Protection Act applies; HIPAA/GDPR if serving those regions.
- Developer said "leave test" for the audit page; tests are otherwise expected. Keep tests focused on permission and data-safety rules.

---

## 2. Concept

A hospital web platform with two sides:

1. **Public website** (not built): Home, About, Departments, Doctors, Services, Contact, Blog. A Login button leads to the portal.
2. **Private portal** (mostly built): patients and staff log in and see only what their role allows. Patients log in with a username or card number (`PAT000001`); staff with a username or staff ID (`STF000001`). A dashboard can never show another user's data.

---

## 3. Roles and hierarchy

`accounts.User.Role` values (this is the real list):

| Value | Label | Notes |
|---|---|---|
| `main_admin` | Main Admin | Superuser. Created with `createsuperuser`, never through the portal. |
| `sub_admin` | Sub Admin | `is_staff=True`. Oversees everything. Only a main admin may create or manage one. |
| `department_head` | Department Head | The role label. The real test for "head" is `Department.head == user` (reverse name `headed_department`). |
| `senior_doctor`, `doctor` | | Medical |
| `senior_nurse`, `nurse` | | Medical |
| `senior_staff`, `staff` | | Admin or support staff |
| `patient` | Patient | **Default role** of a new `User`. |

`ADMIN_ROLES = (MAIN_ADMIN, SUB_ADMIN)` lives in `core/mixins.py`.

Hierarchy is the `User.supervisor` self-ForeignKey (reverse name `team`). Group-based permissions are **not** used; access is decided in code from role, `StaffProfile`, and department.

### Staff categories (`departments.StaffProfile.category`)

| Category | Examples | Access |
|---|---|---|
| `medical` | doctors, nurses, physiotherapists, lab scientists, pharmacists | Cases assigned to them |
| `admin` | receptionist, records officer, accountant, HR | Their function (front desk: register patients, card desk) |
| `support` | cleaner, chef, gateman, driver, maintenance | **No patient or case data at all** |

**How the code identifies staff types (important):** by `StaffProfile` and department, not by the role label.
- General (triage) staff: medical category and `department.is_general`.
- Department head: `user.headed_department` exists.
- Medical staff: `staff_profile.category == "medical"`.
- Admin access: `user.is_superuser or user.is_staff or user.role in ADMIN_ROLES` (`cases.permissions.is_admin`).

---

## 4. Environment and project layout

- Python 3.14, Django 6.1.2, PostgreSQL (database `hospital_db`), `python-decouple` for `.env` settings.
- `AUTH_USER_MODEL = "accounts.User"`; `AUTHENTICATION_BACKENDS = ["accounts.backends.LoginIDBackend"]` (login with username, card number, or staff ID).
- `TIME_ZONE = "Africa/Lagos"`, `USE_TZ = True`. Templates in `templates/` (project level) plus `APP_DIRS`.
- `LOGIN_URL = "accounts:login"`, `LOGIN_REDIRECT_URL = "accounts:dashboard"`.
- `INSTALLED_APPS` project apps: `accounts, core, website, departments, patients, cases, facilities, datarequests, attendance, laboratory, pharmacy, appointments, billing`.
- Project config: `hospital/` (`settings.py`, `urls.py`).

---

## 5. App status

| App | Status | What it holds |
|---|---|---|
| `accounts` | Built | User, login backend, login view, **role dashboards**, **staff management (CRUD)** |
| `core` | Built | Access mixins, **AuditLog**, `audit.log()` helper, audit log page, **login lockout** (`LoginThrottle`, `lockout.py`, signals) |
| `departments` | Built | Department, StaffProfile, department CRUD pages |
| `patients` | Built | Patient, Allergy, MedicalHistory, Family cards, card fees and renewals, registration |
| `cases` | Built | Case, CaseEvent, triage, assignment, status flow |
| `facilities` | Built | Building, Ward, Bed, **Admission** (admit and discharge), **WardAssignment** (nurses assigned to wards) |
| `datarequests` | Built | DataRequest: a patient asks for a copy, a correction or deletion; admins review and answer |
| `website` | Built by another assistant, reviewed | Public site (home, about, departments, doctors, services, contact, blog) at `/`; portal pages at `/site/` |
| `laboratory` | Built | LabTest, LabResult, ordering, entering, release, patient results, print page |
| `attendance` | Built | AttendanceRecord, AttendanceCorrection, self clock-in/out, officer recording, confirmation, corrections, **duty roster** (ShiftType, RosterEntry, week grid, lateness and missing-staff checks) |
| `pharmacy` | Built by another assistant, reviewed 14 Oct 2026 | Drug, StockBatch, StockAdjustment, Prescription, PrescriptionItem, Dispensing; prescribing from the case page, dispensing, stock, allergy warnings |
| `appointments` | Built | DoctorAvailability (weekly hours) and Appointment; booking by patients and front desk, cancelling, recording the outcome |
| theme (frontend) | Built | `templates/base.html` plus `templates/partials/_theme_css.html` and `_theme_js.html`: teal to blue gradient look, animated sidebar layout, no build step, no static files, no libraries |
| `billing` | Not built | |

Cross-cutting items not built: lab result amendments, deployment hardening.

**Setup needed after installing laboratory, attendance and datarequests:** add `"attendance"` and `"datarequests"` to `INSTALLED_APPS` in `settings.py` (it is a new app); create a Laboratory department with **Is laboratory** ticked; set `HOSPITAL_NAME` in settings (used on printed results); tick **Attendance officer** on gateman and HR staff profiles. For pharmacy, create a Pharmacy department with **Is pharmacy** ticked, put pharmacy staff in it (Medical category), then add drugs and receive stock. For appointments, doctors (or their head, or an admin) must add weekly hours at `/appointments/availability/` before patients can book.

---

## 6. Data model reference (as built)

Read the real `models.py` before changing any model; this is a map, not a substitute.

**accounts.User** (extends `AbstractUser`): `role`, `login_id` (unique, auto: `PAT######` for patients, `STF######` for others, set on first save), `phone`, `supervisor`. Properties `is_patient`, `is_staff_member`. Reverse names: `staff_profile`, `patient_profile`, `headed_department`, `team`, `assigned_cases`, `routed_cases`. `save()` forces `is_staff=True` for admin roles and `is_staff=False` for patients, but **does not clear `is_staff` when an admin is demoted** (see Section 12).

**departments.Department**: `name` (unique), `description`, `head` (OneToOne to User, reverse `headed_department`), `is_general`, `is_laboratory`, `is_pharmacy`, `is_active`.
**departments.StaffProfile**: `user` (OneToOne, reverse `staff_profile`), `category`, `job_title`, `department` (nullable, PROTECT), `grade` (`junior`/`senior`), `attendance_officer` (bool: may record and confirm anyone's attendance, e.g. gateman, HR), `records_officer` (bool: may read and answer patients' data requests).

**patients**: `Patient` (OneToOne `user`, reverse `patient_profile`; fields: `date_of_birth`, `gender`, `address`, `blood_group`, `emergency_contact_name`, `emergency_contact_phone`, optional `family` and `relationship`, `created_at`; reverse names `allergies`, `history`, `card_renewals`, `cases`, `lab_results`, `prescriptions`, `appointments`, `data_requests`). **`Patient` has no `card_number` column: a patient's card number is `user.login_id` (`PAT######`).** Card status and expiry come from the card renewal records; read `patients/models.py` before using them. Also `Allergy`, `MedicalHistory`, `Family` (`FAM######`, name, address; at most one head), `CardType` (single or family card: fee, validity months), card renewal records created by `patients/cards.py: issue_card(holder, received_by)`. A family card only groups people; every member keeps a private record and login.

**facilities.WardAssignment**: `user` (reverse `ward_assignments`), `ward` (reverse `assignments`), `created_by`, `created_at`; unique per user and ward.

**cases.Case**: `patient`, `complaint`, `department` (nullable), `assigned_to`, `status` (`pending`, `assigned`, `in_treatment`, `completed`), `routed_by`, `routed_at`, `created_at`, `updated_at`. `routed_at is None` means "still in the triage queue". Related name from Patient: `cases`.
**cases.CaseEvent**: per-case history: `case`, `actor`, `action` (`created`, `routed`, `assigned`, `status`, `admitted`, `discharged`), `note`, `created_at`.

**facilities**: `Building`, `Ward` (type, optional `department`; no department means shared/general), `Bed` (`is_occupied` kept in sync by services only), `Admission` (`case`, `bed`, `admitted_by`, `admitted_at`, `discharged_by`, `discharged_at`, `notes`). Database constraints: one active (undischarged) admission per bed and per case. `Admission.case` uses PROTECT.

**laboratory**: `LabTest` (name, unit, reference_range, is_active), `LabResult` (case, patient, test, status `ordered`/`resulted`/`released`/`cancelled`, order_note, ordered_by/at, value, result_notes, entered_by, resulted_at, released_by, released_at, cancel_reason). Workflow in Section 7.

**pharmacy**: `Drug` (name, strength, form, unit, comma-separated `ingredients` used for allergy matching, `reorder_level`, `is_active`; unique on name, strength and form), `StockBatch` (one delivery: drug, batch_number, `expiry_date`, `quantity_received`, `quantity_remaining` changed only by services), `StockAdjustment` (every correction or write-off: signed `change`, reason, note; never edited or deleted), `Prescription` (case, patient always equal to `case.patient`, status `prescribed`/`partly_dispensed`/`dispensed`/`closed`/`cancelled`, `note` for the pharmacy, prescribed_by/at, `allergy_warning_acknowledged`, close and cancel fields), `PrescriptionItem` (drug, dose, frequency, duration_days, quantity, `quantity_dispensed` changed only by services; one line per drug), `Dispensing` (each handover, tied to the batch it came from; never edited or deleted). Reverse names: `Case.prescriptions`, `Patient.prescriptions`.
**appointments**: `DoctorAvailability` (doctor, weekday 0 to 6, start_time, end_time, `slot_minutes`; a doctor may have several non-overlapping windows a day) and `Appointment` (patient, doctor, `department` snapshot taken at booking, starts_at, ends_at, `reason`, status `scheduled`/`completed`/`cancelled`/`no_show`, booked_by, closed_by/at, cancel_reason). Database constraints: one scheduled appointment per doctor and start time, and one per patient and start time. Reverse names: `Patient.appointments`, `User.doctor_appointments`, `User.availability_windows`.
**attendance**: `AttendanceRecord` (user, work_date, clock_in, clock_out, source `self`/`officer`, recorded_by, confirmed_by, confirmed_at), `AttendanceCorrection` (record, corrected_by, reason, old and new clock times), `ShiftType` (name, start_time, end_time; end earlier than start means overnight; is_active), `RosterEntry` (user, date, shift, optional building as work area, note, created_by; unique per user, date and shift). Attendance records are never deleted or silently edited.

**datarequests.DataRequest**: `patient`, `kind` (`access`/`correction`/`deletion`), `subject`, `details`, `status` (`open`, `in_review`, `resolved`, `declined`), `created_at`, `handled_by`, `handled_at`, `response` (shown to the patient).

**website** (built by another assistant, reviewed against these rules): `SiteInfo` (single row: About text, address, phones, public email, opening hours, `notify_email` for new-message emails, never shown), `Service`, `DoctorListing` (opt-in: user, bio, photo, order, `is_listed`), `BlogPost` (draft/published, category health or hospital, slug, author), `ContactMessage` (visitor messages with IP and a handled flag).

**core.LoginThrottle**: `key` (`user:<pk>` or `unknown:<typed id>`), `label`, `user`, `failed_count`, `last_failed_at`, `locked_until`, `last_ip`.

**core.AuditLog**: `actor`, `actor_label` (snapshot), `action` (free string), `target_type`, `target_id`, `target_repr`, `patient` (nullable), `detail`, `ip_address`, `created_at`. Cannot be saved twice or deleted through the app.

---

## 7. Business flows

**Case flow.** Patient registers (public form requires a complaint; front-desk form makes it optional) and may pick a department. A `Pending` case is created. General staff **route or confirm** the department (a patient's choice is saved but still goes through triage). The department head **assigns** active medical staff of that department. Assigned staff move the status `assigned` to `in_treatment` to `completed` (no skipping). Re-assigning is allowed until treatment starts. A case cannot be completed while the patient is still in a bed.

**Admission flow.** The assigned doctor or the department head admits a patient from the case page into a free bed (shared ward, or a ward of the case's department). Discharge frees the bed. A bed cannot be double-booked; a patient cannot be admitted twice.

**Laboratory flow.** The assigned doctor or department head orders tests from the case page (case must be assigned or in treatment). Lab staff (medical category, in a department with `is_laboratory`) enter the value. The assigned doctor, the department head, or **senior** lab staff **release** it. Only released results are visible to the patient (own results only); unreleased ones return 404. A patient can print a released result (clean print page, browser Print or Save as PDF). A test can be cancelled only before a result is entered. Released results cannot be edited (planned: amendments with a reason). Admins can view all results (audited) but cannot enter or release. Values are never copied into the audit log.

**Attendance flow.** Staff with a staff profile clock themselves in and out (source `self`, unconfirmed). An **attendance officer** (flag on StaffProfile) can record someone's arrival by staff ID (confirmed immediately, source `officer`). Department heads, supervisors, officers and admins can confirm records, record a departure, and correct times; a correction needs a written reason, keeps the old values, is audited, and marks the record confirmed. Nobody can confirm or correct their own record. Earlier days that are still unconfirmed or never clocked out are **flagged** for review (shown on dashboards and the team page). **Duty roster:** admins define shift types; admins, department heads and supervisors plan shifts for the staff they manage (a department head: their department and direct reports; admins: everyone; attendance officers see everyone read-only). Planning is by date range (max 31 days, not in the past); past entries cannot be removed. Staff see their own roster and today's shift on the dashboard. The team attendance page shows the planned shift, minutes late (15 minute grace period), and a list of staff planned for today who have not clocked in. A staff member cannot clock in twice on the same day without clocking out; a forgotten clock-out from an earlier day is closed by a head or officer.

**Pharmacy flow.** An admin ticks **Is pharmacy** on a department; its Medical-category staff are pharmacy staff and its head is the pharmacy head. Senior pharmacy staff, the pharmacy head and admins manage the drug catalogue and correct or write off stock; any pharmacy staff may receive stock. Only the assigned doctor (role `doctor` or `senior_doctor`), the assigned **senior nurse** (role `senior_nurse`) or the head of the case's department may prescribe, from the case page, while the case is assigned or in treatment. Junior nurses, other staff and pharmacy staff never prescribe, even if assigned to the case; they can still see the case's prescriptions if assigned. The same people (plus pharmacy staff, who may cancel an unfilled prescription) can cancel a prescription before anything is dispensed. A drug whose name or ingredients match a recorded allergy (substring match, at least 3 letters) blocks prescribing and dispensing until the warning is acknowledged; this check does **not** know drug classes (a penicillin allergy does not flag amoxicillin unless "penicillin" is in the drug's ingredients). Pharmacy staff and the pharmacy head dispense: all or nothing across the prescription, earliest-expiry batch first, never expired stock, partial dispensing allowed. A prescription can be cancelled only before anything is dispensed; a partly dispensed one is closed with a written reason. Admins can view but never dispense. Patients see their own prescriptions (not the note to the pharmacy). Drug names and doses are never copied into the audit log.

**Appointments.** Doctors set weekly hours (for example Monday 09:00 to 12:00 in 30 minute visits); a department head sets them for their department and admins for anyone. Only active doctors in the Medical category in a clinical department can be booked (not the general or laboratory department). A patient books for themselves at `/appointments/book/`; the front desk books for a patient by card number (`?patient=PAT000001`). Rules (numbers in `appointments/rules.py`): up to 60 days ahead, at most 3 upcoming appointments per patient, no two at the same time, no double booking of a doctor. A patient may cancel until 2 hours before the start; staff (front desk, the doctor, the head, admins) may cancel before the start but must give a reason. Only the doctor or the head records the outcome (completed or no-show), and only once the time has started. The **front desk sees who, when and with whom, but never the reason for the visit**; the doctor, head, admins and the patient see it. Admins view and cancel but do not record outcomes. The reason and the cancellation text are never copied into the audit log. Booking does not create a case (not linked yet).

**Data requests.** A patient files a request (copy, correction or deletion; at most 5 open at a time). Main and sub admins and staff marked **records officer** on their staff profile handle them: move to `in_review`, then `resolved` or `declined`; closing needs a written answer the patient reads on the request page. Closed requests are final. **Nothing is ever deleted automatically**; a deletion request is decided by an administrator who explains what must be kept under legal retention. Other staff cannot see requests; a records officer gets no other admin power (no audit log, no staff pages). The request text and the answer are never copied into the audit log.

**Login lockout (built, tested).** 5 wrong passwords in a row lock an account for 15 minutes (constants in `core/lockout.py`: `MAX_ATTEMPTS`, `LOCK_MINUTES`, `WINDOW_MINUTES`). The counter is per account, shared by username and card number or staff ID; unknown IDs are counted and locked identically so the login page reveals nothing. A locked account cannot log in even with the right password, through the portal or Django admin (the auth backend raises `PermissionDenied`). Failures older than 15 minutes are forgotten; a correct login clears the counter. Failures and successes are recorded by signals in `core/signals.py` (connected in `CoreConfig.ready`). Admins unlock early at `/accounts/locked/`.

**Nurses and wards.** Admins (everyone) and department heads (their own team) assign nurses (role Nurse or Senior Nurse, Medical category) to wards at `/facilities/ward-staff/`. A nurse sees, at `/facilities/my-ward/`, the beds and the patients **currently admitted** in the wards they are assigned to, and may open the **read-only** case page of those patients (`cases.permissions.is_ward_nurse_for`, used by `can_view`). Access ends automatically at discharge. A nurse cannot change status, route, assign, admit, discharge, or order tests; those checks are separate. Viewing the ward list and the case page is audited. Cleaners are placed by building through the duty roster (`RosterEntry.building`), not by ward assignment.

**Public website.** The home page `/` is public (Login or My portal button leads to the portal). Public pages: `about/`, `our-departments/` (not `departments/`, which belongs to the portal), `doctors/`, `services/`, `contact/`, `blog/`. They show no patient or private staff data. Doctors appear only if an admin lists them (opt-in, active, Medical category, doctor role, full name on file); only name, department, bio and an optional photo are shown. The general (triage) department is never advertised. Drafts and future-dated posts return 404. The contact form has a honeypot and a limit of 5 messages per IP per hour; new messages can also be emailed to `SiteInfo.notify_email`. Admins run the site at `/site/`; **blog posts** can also be written by administrative-category staff (`FrontDeskRequiredMixin`). Every change is audited (fail-closed) without copying text into the log. Doctor photos are stored under random names, JPG/PNG/WebP up to 2 MB, and need **Pillow**.

**Cards.** Front desk (administrative staff and admins only) issues and renews single or family cards (fee confirmation required). Registering patients at `/patients/new/` follows the same rule. Public self-registration has no family options.

**Staff management.** Admin roles create staff (account and profile in one form, staff ID generated), edit them, reset passwords, deactivate and reactivate. **Staff are never deleted** (history must survive). See Section 8 for rules.

**Dashboards.** One view, one template; `accounts/dashboards.py: build_dashboard(user)` returns `kind` = `admin`, `patient`, `head`, `general`, `medical`, `front_desk`, `support`, or `other`. Support staff get no patient data.

---

## 8. Code contracts (use these; do not bypass them)

**Services (all state changes go through these; they use transactions and row locks and write the audit log):**

```python
# cases/services.py  (all raise django ValidationError on rule violations)
create_case(patient, complaint, department=None, actor=None, request=None)
route_case(case, department, actor, note="", request=None)
assign_case(case, assignee, actor, note="", request=None)
change_status(case, new_status, actor, note="", request=None)

# facilities/services.py
admit_patient(case, bed, actor, notes="", request=None)
discharge_patient(admission, actor, request=None)
```

```python
# laboratory/services.py
order_tests(case, tests, actor, note="", request=None)
enter_result(result, value, notes, actor, request=None)
release_result(result, actor, request=None)
cancel_result(result, actor, reason="", request=None)

# attendance/services.py
clock_in(user, request=None); clock_out(user, request=None)
record_arrival(actor, target, request=None); record_departure(actor, record, request=None)
confirm_record(actor, record, request=None)
correct_record(actor, record, new_in, new_out, reason, request=None)
panel_for(user)   # dashboard data

# pharmacy/services.py  (raise ValidationError; AllergyWarning is a ValidationError subclass)
prescribe(case, items, actor, note="", acknowledged=False, request=None)
cancel_prescription(prescription, actor, reason="", request=None)
close_prescription(prescription, actor, reason, request=None)
dispense(prescription, quantities, actor, acknowledged=False, request=None)   # quantities = {item_id: number}
receive_stock(drug, batch_number, expiry_date, quantity, actor, notes="", request=None)
adjust_stock(batch, change, reason, note, actor, request=None)

# appointments/services.py  (ValidationError for broken rules, PermissionDenied if not allowed to act)
available_slots(doctor, day, now=None)        # list of Slot(start, end)
book_appointment(patient, doctor, starts_at, reason, actor, request=None)
cancel_appointment(appt, actor, reason="", request=None)
close_appointment(appt, new_status, actor, request=None)   # completed or no_show
add_availability(actor, doctor, weekday, start_time, end_time, slot_minutes, request=None)
remove_availability(actor, window, request=None)
```

**Audit log:**

```python
from core import audit
audit.log(actor, "action_name", target_obj, patient=patient_or_None, detail="text", request=request)
```

The entry is written inside the caller's transaction (if logging fails, the action fails). Never put secrets (passwords) in `detail`. Action names in use: `case_created, case_routed, case_assigned, case_status, case_viewed, patient_admitted, patient_discharged, patient_record_viewed, staff_created, staff_updated, staff_password_reset, staff_deactivated, staff_reactivated, lab_ordered, lab_result_entered, lab_result_released, lab_result_cancelled, lab_result_viewed, lab_result_printed, lab_test_created, lab_test_updated, attendance_clock_in, attendance_clock_out, attendance_recorded, attendance_departure_recorded, attendance_confirmed, attendance_corrected, roster_assigned, roster_removed, shift_created, shift_updated, data_request_created, data_request_updated, data_request_viewed, login_success, login_failed, login_blocked, account_locked, account_unlocked, ward_staff_assigned, ward_staff_removed, ward_list_viewed, blog_post_created, blog_post_updated, blog_post_published, blog_post_unpublished, service_created, service_updated, doctor_listing_created, doctor_listing_updated, site_info_updated, contact_message_viewed, contact_message_handled, contact_message_reopened, prescription_created, prescription_cancelled, prescription_closed, prescription_dispensed, prescription_viewed, drug_created, drug_updated, stock_received, stock_adjusted, appointment_booked, appointment_cancelled, appointment_completed, appointment_no_show, appointment_viewed, appointment_list_viewed, availability_added, availability_removed`. Add new actions as plain strings; no migration needed. Log **every** view or change of patient data and every admin action.

**Permission helpers:** `cases/permissions.py`: `is_admin, is_medical, is_general_staff, headed_department, get_patient, can_view, can_route, can_assign, can_change_status, can_admit`. Staff management: `accounts/staff_rules.py: can_manage(actor, target)`, `assignable_roles(actor)`.

**Mixins:** `core/mixins.py`: `StaffRequiredMixin` (patients get 403), `AdminRequiredMixin` (admin roles only, others 403), `FrontDeskRequiredMixin` (administrative staff and admin roles only; helper `is_front_desk(user)`). All include `LoginRequiredMixin`.

**More permission helpers:** `facilities/ward_permissions.py`: `manageable_nurses, can_open_manager`; `cases/permissions.py` also has `is_ward_nurse_for`. `laboratory/permissions.py`: `is_lab_staff, is_senior_lab, can_order, can_enter, can_release, can_cancel, can_view, can_print, results_for_case`. `attendance/permissions.py`: `has_staff_profile, is_officer, sees_team, visible_records, flagged, can_manage_record, can_record_arrival`. `datarequests/permissions.py`: `is_records_officer, can_handle`. `attendance/roster_permissions.py`: `manageable_staff, visible_staff, can_open_manager, can_manage_roster_for`. `pharmacy/permissions.py` (`PRESCRIBER_ROLES`): `is_pharmacy_staff, is_pharmacy_head, is_senior_pharmacy, in_pharmacy_area, can_manage_stock, can_receive_stock, can_prescribe, can_dispense, can_cancel, can_close, can_view, prescriptions_for_case`. `appointments/permissions.py`: `eligible_doctors, is_eligible_doctor, patient_of, can_view, can_see_reason, visible_appointments, can_open_staff_list, can_book_for, cancel_problem, can_cancel, close_problem, can_close, manageable_doctors, can_manage_availability, can_open_availability` (the `*_problem` functions return a message, or an empty string when allowed). `attendance/roster_services.py`: `assign_shift(actor, users, shift, date_from, date_to, building=None, note="", request=None)`, `remove_entry`, `evaluate`, `missing_today`.

**Staff management rules:** nobody manages themselves; patients and main admins are never managed through the portal; only a main admin manages sub admins; a sub admin manages everyone below; main admin accounts are never created through the portal; a demoted admin has `is_staff` cleared explicitly in the form code; supervisor loops are rejected; doctors and nurses must be in the Medical category.

---

## 9. URL map

| Prefix | Pages (names are `namespace:name`) |
|---|---|
| `/admin/` | Django admin (backup only) |
| `/accounts/` | `locked/` (`locked_list`), `locked/<pk>/unlock/` (`unlock`), `login/`, `logout/`, `dashboard/`, `staff/` (`staff_list`), `staff/new/`, `staff/<pk>/` (`staff_detail`), `staff/<pk>/edit/`, `staff/<pk>/password/`, `staff/<pk>/deactivate/`, `staff/<pk>/reactivate/` |
| `/departments/` | `list`, `new/`, `<pk>/`, `<pk>/edit/`, `staff/new/`, `staff/<pk>/edit/` (profile only, for an existing user) |
| `/patients/` | `list`, `<pk>/`, `new/` (`staff_register`), public `register`, `registered/`, `me/` (`my_profile`), families (`family_list`), `cards/` (`card_desk`), `cards/prices/` (`card_prices`) |
| `/cases/` | `home` (redirects by role), `new/`, `mine/`, `triage/`, `department/`, `assigned/`, `all/`, `<pk>/` (`detail`), `<pk>/route/`, `<pk>/assign/`, `<pk>/status/` |
| `/facilities/` | `ward-staff/` (`ward_staff`, `ward_assign`, `ward_unassign`), `my-ward/` (`my_ward`), `overview`, buildings and wards CRUD, `wards/<pk>/beds/add/`, `admissions/` (`admission_list`), `cases/<case_pk>/admit/` (`admit`), `admissions/<pk>/discharge/` (`discharge`) |
| `/laboratory/` | `worklist` (`/`), `tests/` catalogue (`tests`, `test_create`, `test_update`), `order/<case_pk>/` (`order`), `results/<pk>/` (`result`), `results/<pk>/enter|release|cancel/`, `results/<pk>/print/` (`print`), `mine/` (patient results) |
| `/attendance/` | `mine` (`/`), `clock-in/`, `clock-out/`, `team/`, `record/new/` (`officer_record`), `record/<pk>/confirm|departure|correct/`, `roster/` (manage grid), `roster/mine/`, `roster/assign/`, `roster/entry/<pk>/remove/`, `roster/shifts/` (admins) |
| `/pharmacy/` | `worklist` (`/`), `drugs/` (`drugs`, `drug_create`, `drug_update`), `stock/` (`stock`), `stock/receive/` (`receive`), `stock/batches/<pk>/adjust/` (`adjust`), `prescribe/<case_pk>/` (`prescribe`), `prescriptions/<pk>/` (`prescription`), `prescriptions/<pk>/dispense|cancel|close/`, `mine/` (patient's own prescriptions) |
| `/appointments/` | `home` (redirects by role), `mine/` (patient), `book/` (patient for self; front desk adds `?patient=PAT000001`), `all/` (`staff_list`), `<pk>/` (`detail`), `<pk>/cancel/`, `<pk>/close/`, `availability/`, `availability/<pk>/remove/` |
| `/requests/` | `mine`, `new/`, `manage/` (admins and records officers), `<pk>/` (`detail`), `<pk>/handle/` (admins and records officers) |
| `/` and public paths | `/` (home), `about/`, `our-departments/`, `doctors/`, `services/`, `contact/`, `blog/`, `blog/<slug>/` (no login) |
| `/site/` | admin pages for the website: `site/`, `site/info/`, `site/posts/` (admins and administrative staff), `site/services/`, `site/doctors/`, `site/messages/` |
| `/audit/` | `core:audit_list` (admin roles only, filters and search, read-only) |
| (root) | Now served by the website app (public home page). The old temporary redirect to login was removed |

Case pages use a case ID in the URL, but access is always checked against the user; unauthorized access returns 404 (the case's existence is not revealed). Dashboards never use an ID in the URL.

---

## 10. Security rules (non-negotiable)

- Never put a user or patient ID in dashboard URLs. Load data from `request.user`.
- Filter every query by what the logged-in user may see. `LoginRequiredMixin` on all portal views plus role checks.
- Department head sees only their department's cases and staff. Staff see only cases assigned to them. General staff see unrouted pending cases. Patients see only their own records. Support staff see **no** medical data.
- Patients cannot delete or edit medical records or results. (Planned: a request flow, Section 14.)
- Audit every view or change of patient data, and every admin action.
- Use `override_settings(PASSWORD_HASHERS=[MD5...])` in tests only.
- Planned: serving uploaded media (doctor photos) safely in production (the development server serves `/media/` only when DEBUG is on), a real email backend for contact notifications (use the console backend while developing), HTTPS, login lockout, encrypted backups, `REMOTE_ADDR` replaced by the real client IP behind a proxy, database permissions that stop edits to audit rows.

### Access matrix (current)

| Who | Cases | Patients | Staff pages | Audit log |
|---|---|---|---|---|
| Main/Sub admin | All (view) | All | Manage | View |
| Dept head | Own department; assigns | No | No | No |
| General staff | Unrouted queue; routes | No | No | No |
| Other medical | Assigned to them; nurses also see patients admitted in their assigned wards (read-only) | Via case only | No | No |
| Front desk (admin category) | No | Register, card desk (admin roles too) | No | No |
| Support staff | None | None | No | No |
| Patient | Own | Own profile | No | No |

Laboratory: lab staff see the worklist and enter results; the assigned doctor, department head, or senior lab staff release; admins view all (audited); patients see only their own released results; support staff and unrelated staff see nothing. Attendance: everyone with a staff profile sees their own; heads and supervisors see their team; attendance officers and admins see everyone. Pharmacy: pharmacy staff and the pharmacy head see every prescription, dispense and look after stock but never prescribe; the assigned doctor, assigned senior nurse or department head prescribes; any assigned staff member sees the prescriptions of their case; admins view only; patients see their own; unrelated staff and support staff see nothing. Appointments: patients see their own; a doctor sees appointments booked with them; a head sees their department's; the front desk sees every appointment but not the reason for the visit; admins see everything; nurses, support and other staff see nothing.

---

## 11. Testing

- Run everything: `python manage.py test`. Per app: `python manage.py test cases facilities`.
- Last confirmed full run: **410 tests, all passing** on 14 October 2026 (all apps marked Built in Section 5).
- Test helpers live in `cases/tests.py`: `make_user`, `make_staff`, `make_patient`, `PW`. Note `make_user`/`make_staff` create users with the **default role `patient`**; tests that need a real role must set `user.role` and save.
- Tests slow down because of password hashing; use the `FAST` hasher override.

---

## 12. Known pitfalls (learned the hard way)

1. **Reverse names are `staff_profile` and `patient_profile`**, not `staffprofile`. Wrong names fail silently in `getattr(..., None)` and caused real bugs.
2. **Every app needs `__init__.py`.** Missing ones made `manage.py test` import test modules as top-level modules (`ImportError: attempted relative import with no known parent package`).
3. **Same-named files in different apps** (`models.py`, `admin.py`, `tests.py`, `views.py`) were pasted into the wrong app twice. Always name the destination path for every file, give copy commands, and ask the developer to verify with `git status --short` and `findstr "^class " <file>`.
4. **Never overwrite whole folders.** Extracting a zip over the project once deleted the `core` app. Use `git restore <file>` for single files; never `git restore` a whole folder with uncommitted work.
5. **`makemigrations` then `migrate` after every model change**, and commit the migration files. A missing migration shows as `relation "..." does not exist`.
6. **Do not use `context_object_name = "user"`** in views: it hides the logged-in `user` that `base.html` uses for the menu.
7. **`base.html` already renders `messages`.** Do not render them again in page templates.
8. **`User.save()` does not clear `is_staff` on demotion.** `cases.permissions.is_admin` trusts `is_staff`, so any code that changes a role must set `is_staff = role in ADMIN_ROLES`.
9. Dashboards and case rules identify staff by **StaffProfile and department**, so a staff account with no `StaffProfile` gets a generic dashboard and no case access. Create profiles.
10. Public registration now **requires a complaint**; any test posting the public form must include `complaint`.
11. The server's auto-reloader can get stuck after a crash. Stop it with Ctrl+C and restart.
12. **New app = new `INSTALLED_APPS` entry.** `attendance` must be added to `settings.py` by hand.
13. **`makemigrations` per app**, naming every app that changed (for example `departments laboratory`, `departments attendance`), and read what it reports before running `migrate`.
14. **Do not name a context variable `user`**, and remember `DetailView`/`ListView` default names.
15. The sandbox used to build the code cannot run the project; a Django template syntax check passes, but tests only run on the developer's machine. Ask for test output.
16. Windows line endings: Git prints "LF will be replaced by CRLF" warnings. They are harmless.
17. **`Patient` has no `card_number` column.** A patient's card number is `user.login_id` (`PAT######`). Look patients up with `user__login_id`. An earlier version of this document listed `card_number` and other card fields on `Patient`; that was wrong and caused two failing tests in appointments.
18. **Zips from other assistants contain shared files** (`hospital/urls.py`, `templates/base.html`, `accounts/dashboards.py`, `departments/models.py`, `cases/views.py`). Copying them blindly overwrites newer work: the pharmacy zip's `hospital/urls.py` has no appointments line. Run `git diff <file>` first and merge only the lines needed.
19. **Code written without the real repository uses guessed interfaces.** Before building a new piece, check the real names with `findstr` (template block names, model field names) and treat a stand-in test run in a sandbox as a syntax check, not proof.
20. **Styling lives in real files, never inline.** The hospital name is **GOOD HEALTH HOSPITAL**. `core/static/core/css/theme.css` is the shared design system (colours are variables at the top: `--accent-a` to `--accent-e`), `core/static/core/js/theme.js` and `theme-boot.js` are the shared behaviour, `core/static/core/img/` holds the logo emblem, favicon and `icons.svg` (all menu icons). **Each app has its own stylesheet** at `<app>/static/<app>/css/<app>.css`; `templates/base.html` loads the right one automatically from the page's URL namespace (`request.resolver_match.app_name`), so a new app only needs its own file, with the same name as its namespace. An app file may redefine the accent variables to recolour its pages (pharmacy and departments are green, laboratory indigo, and so on) and holds rules only that app uses (accounts holds the animated sign-in card, appointments the time-picker pills). Do not write `<style>` blocks, `<script>` blocks or `style=` attributes in templates; add a class and put the rule in the app's file. New templates should use plain `<table>`, `<form>`, `<h1>`, `<h2>`, `<button>` (styled automatically). Existing classes: `.card`, `.bar`, `.btn`, `.wrap`, `.muted`, `.errorlist`, `.actions` (row of buttons), `.stat-grid` with `.stat`, `.stat-number`, `.stat-label` (gradient tiles with a count-up; `data-count` makes any number count up). Status words in table cells become coloured badges, and buttons whose text contains cancel, remove, delete, reject, withdraw or discharge turn red. Django messages show as toasts. Needs `django.contrib.staticfiles` in INSTALLED_APPS, `STATIC_URL`, and the `request` context processor. In production run `collectstatic` and serve the static folder (see Section 14). The logo image supplied by the hospital says Good Healthcare Hospital, so only its emblem is used; the name is live text in `base.html` and `accounts/login.html`. The menu conditions in `base.html` mirror the permission rules; for a new menu link copy a `nav-link` line and choose an icon id from `icons.svg`.

---

## 13. Decisions log

- Card numbers and staff IDs are generated automatically (`PAT000001`, `STF000001`). Patients may choose a username; login accepts username, card number, or staff ID.
- Staff and patients are **deactivated, never deleted**.
- Family card groups people only; no shared medical records.
- Patient's chosen department is confirmed by triage staff; it is not automatic.
- Admission is by the assigned doctor or department head; discharge frees the bed; a case cannot be completed while admitted.
- Audit writes are **fail-closed** (same transaction as the action).
- `Admission.case` is PROTECT, not CASCADE (deviation from the first draft, deliberate).
- Staff management lives in `accounts`; `StaffProfile` stays in `departments` (resolved).
- Patients print their own results after release (built). Release is by the assigned doctor, the department head, or senior lab staff.
- Laboratory is identified by a department flag `is_laboratory` (resolved open question).
- Attendance uses **both** self clock-in and confirmation by someone else (built). "Attendance officer" is a flag on StaffProfile (gateman, HR). Records are append-only; corrections keep history.
- Patient data requests are handled by **admin roles and records officers** (`StaffProfile.records_officer`, ticked on the staff pages). Confirm the legal retention period with a lawyer before answering deletion requests.
- Registering patients and the card desk are **front desk only** (administrative staff and admins).
- Cases a patient files with a chosen department still go through triage by general staff before reaching the department head (confirmed with the developer).
- A patient's card number is their `login_id`; there is no separate card number column.
- Prescribing is limited to the assigned doctor or senior doctor, the assigned senior nurse, or the head of the case's department. Pharmacy staff store, look after and dispense drugs; they never prescribe.
- Pharmacy is identified by a department flag `is_pharmacy` (same pattern as `is_laboratory`). Dispensing is all or nothing, earliest expiry first, never expired stock. Dispensing and stock records are append-only, and the admin pages for them are read-only.
- Appointments: the front desk may book and cancel but never sees the reason for a visit; admins view and cancel but do not record outcomes; only the doctor or the head records completed or no-show; doctors in the general or laboratory department take no bookings; a department snapshot is stored on each appointment so history does not move when a doctor transfers.

---

## 14. Roadmap (build in this order)

1. **Pharmacy follow-up** (small): the allergy check matches names and ingredients only, not drug classes (see Section 7). Consider a drug class field. (The nurse-prescribing gap and the Back link for pharmacy staff were fixed on 14 Oct 2026.)
2. **Lab result amendments** (next): a released result can be amended with a reason, keeping the old value and notifying the patient.
3. **Appointments follow-ups:** a dashboard tile for upcoming appointments, reminders by SMS or email, and an optional link from an appointment to a case when the patient arrives.
4. `billing` (Paystack or Flutterwave scope still open).
5. Security review and deployment: `collectstatic` and a static file server (for example WhiteNoise), HTTPS, secure cookies, real client IP (also needed for lockout and audit addresses behind a proxy), backups, database permissions for audit rows, DEBUG off.

Rule for each new app: build the **portal CRUD pages** the admin needs, register Django admin as a backup, add the audit calls, write tests for permission rules.

---

## 15. Delivery protocol (how to hand code to this developer)

1. Build the piece, **compile-check it**, and write tests.
2. Deliver one **zip**. List every file with its **exact destination folder**.
3. Give Windows commands that extract the zip and **copy each file to its own destination**, for example:
   ```
   mkdir %TEMP%\piece
   tar -xf "%USERPROFILE%\Downloads\piece.zip" -C %TEMP%\piece
   copy /Y %TEMP%\piece\accounts\staff_views.py accounts\staff_views.py
   ```
4. Give the verification commands: `git diff <file>` for rebuilt files, `git status --short`, then `python manage.py makemigrations <app>`, `python manage.py migrate`, `python manage.py test`.
5. State what `makemigrations` should report, and tell the developer to stop and paste the output if it mentions anything else.
6. Finish with the commit command and the next suggested piece.

---

## 16. Open questions

- Whether a nurse or doctor can belong to more than one department (currently one).
- Billing and payment gateway scope.
- Whether staff clock-in should be limited to the hospital network.
- Whether front desk should be narrower than the whole Administrative category (for example receptionists only).
- Whether admins should see lab result values or only counts.
- Whether appointments should create or attach to a case at check-in.
- Whether the pharmacy allergy check needs drug classes.
