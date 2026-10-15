# Hospital Management System: System Design and Handoff

> **For any AI or developer continuing this project: read this whole file before writing code.**
> It records the concept, the decisions made with the developer (Shedy), what is built and tested,
> the code contracts between apps, the mistakes already made (Section 12), and what to build next (Section 14).
> Last updated: 9 October 2026. Last confirmed full test run: 132 tests passing. Added since then and **delivered but not yet confirmed by the developer** (check Section 11): audit log page, staff management, laboratory, front-desk access rule, attendance.

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
- `INSTALLED_APPS` project apps: `accounts, core, website, departments, patients, cases, facilities, appointments, pharmacy, laboratory, billing`.
- Project config: `hospital/` (`settings.py`, `urls.py`).

---

## 5. App status

| App | Status | What it holds |
|---|---|---|
| `accounts` | Built | User, login backend, login view, **role dashboards**, **staff management (CRUD)** (delivered, unconfirmed) |
| `core` | Built | Access mixins, **AuditLog**, `audit.log()` helper, audit log page |
| `departments` | Built | Department, StaffProfile, department CRUD pages |
| `patients` | Built | Patient, Allergy, MedicalHistory, Family cards, card fees and renewals, registration |
| `cases` | Built | Case, CaseEvent, triage, assignment, status flow |
| `facilities` | Built | Building, Ward, Bed, **Admission** (admit and discharge) |
| `website` | Not built | Public pages and blog |
| `laboratory` | Built (delivered, unconfirmed) | LabTest, LabResult, ordering, entering, release, patient results, print page |
| `attendance` | Built (delivered, unconfirmed) | AttendanceRecord, AttendanceCorrection, self clock-in/out, officer recording, confirmation, corrections |
| `appointments`, `pharmacy`, `billing` | Not built | |

Cross-cutting items not built: login lockout, patient data-correction and deletion requests, nurse-to-ward assignment, duty roster (planned shifts), deployment hardening.

**Setup needed after installing laboratory and attendance:** add `"attendance"` to `INSTALLED_APPS` in `settings.py` (it is a new app); create a Laboratory department with **Is laboratory** ticked; set `HOSPITAL_NAME` in settings (used on printed results); tick **Attendance officer** on gateman and HR staff profiles.

---

## 6. Data model reference (as built)

Read the real `models.py` before changing any model; this is a map, not a substitute.

**accounts.User** (extends `AbstractUser`): `role`, `login_id` (unique, auto: `PAT######` for patients, `STF######` for others, set on first save), `phone`, `supervisor`. Properties `is_patient`, `is_staff_member`. Reverse names: `staff_profile`, `patient_profile`, `headed_department`, `team`, `assigned_cases`, `routed_cases`. `save()` forces `is_staff=True` for admin roles and `is_staff=False` for patients, but **does not clear `is_staff` when an admin is demoted** (see Section 12).

**departments.Department**: `name` (unique), `description`, `head` (OneToOne to User, reverse `headed_department`), `is_general`, `is_laboratory`, `is_active`.
**departments.StaffProfile**: `user` (OneToOne, reverse `staff_profile`), `category`, `job_title`, `department` (nullable, PROTECT), `grade` (`junior`/`senior`), `attendance_officer` (bool: may record and confirm anyone's attendance, e.g. gateman, HR).

**patients**: `Patient` (OneToOne `user`, reverse `patient_profile`; date of birth, gender, address, blood group, emergency contact, optional `family` and `relationship`; `card_number`, `card_status`, `card_expires_on`, `latest_card_renewal`), `Allergy`, `MedicalHistory`, `Family` (`FAM######`, name, address; at most one head), `CardType` (single or family card: fee, validity months), card renewal records created by `patients/cards.py: issue_card(holder, received_by)`. A family card only groups people; every member keeps a private record and login.

**cases.Case**: `patient`, `complaint`, `department` (nullable), `assigned_to`, `status` (`pending`, `assigned`, `in_treatment`, `completed`), `routed_by`, `routed_at`, `created_at`, `updated_at`. `routed_at is None` means "still in the triage queue". Related name from Patient: `cases`.
**cases.CaseEvent**: per-case history: `case`, `actor`, `action` (`created`, `routed`, `assigned`, `status`, `admitted`, `discharged`), `note`, `created_at`.

**facilities**: `Building`, `Ward` (type, optional `department`; no department means shared/general), `Bed` (`is_occupied` kept in sync by services only), `Admission` (`case`, `bed`, `admitted_by`, `admitted_at`, `discharged_by`, `discharged_at`, `notes`). Database constraints: one active (undischarged) admission per bed and per case. `Admission.case` uses PROTECT.

**laboratory**: `LabTest` (name, unit, reference_range, is_active), `LabResult` (case, patient, test, status `ordered`/`resulted`/`released`/`cancelled`, order_note, ordered_by/at, value, result_notes, entered_by, resulted_at, released_by, released_at, cancel_reason). Workflow in Section 7.

**attendance**: `AttendanceRecord` (user, work_date, clock_in, clock_out, source `self`/`officer`, recorded_by, confirmed_by, confirmed_at), `AttendanceCorrection` (record, corrected_by, reason, old and new clock times). Records are never deleted or silently edited.

**core.AuditLog**: `actor`, `actor_label` (snapshot), `action` (free string), `target_type`, `target_id`, `target_repr`, `patient` (nullable), `detail`, `ip_address`, `created_at`. Cannot be saved twice or deleted through the app.

---

## 7. Business flows

**Case flow.** Patient registers (public form requires a complaint; front-desk form makes it optional) and may pick a department. A `Pending` case is created. General staff **route or confirm** the department (a patient's choice is saved but still goes through triage). The department head **assigns** active medical staff of that department. Assigned staff move the status `assigned` to `in_treatment` to `completed` (no skipping). Re-assigning is allowed until treatment starts. A case cannot be completed while the patient is still in a bed.

**Admission flow.** The assigned doctor or the department head admits a patient from the case page into a free bed (shared ward, or a ward of the case's department). Discharge frees the bed. A bed cannot be double-booked; a patient cannot be admitted twice.

**Laboratory flow.** The assigned doctor or department head orders tests from the case page (case must be assigned or in treatment). Lab staff (medical category, in a department with `is_laboratory`) enter the value. The assigned doctor, the department head, or **senior** lab staff **release** it. Only released results are visible to the patient (own results only); unreleased ones return 404. A patient can print a released result (clean print page, browser Print or Save as PDF). A test can be cancelled only before a result is entered. Released results cannot be edited (planned: amendments with a reason). Admins can view all results (audited) but cannot enter or release. Values are never copied into the audit log.

**Attendance flow.** Staff with a staff profile clock themselves in and out (source `self`, unconfirmed). An **attendance officer** (flag on StaffProfile) can record someone's arrival by staff ID (confirmed immediately, source `officer`). Department heads, supervisors, officers and admins can confirm records, record a departure, and correct times; a correction needs a written reason, keeps the old values, is audited, and marks the record confirmed. Nobody can confirm or correct their own record. Earlier days that are still unconfirmed or never clocked out are **flagged** for review (shown on dashboards and the team page). A staff member cannot clock in twice on the same day without clocking out; a forgotten clock-out from an earlier day is closed by a head or officer.

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
```

**Audit log:**

```python
from core import audit
audit.log(actor, "action_name", target_obj, patient=patient_or_None, detail="text", request=request)
```

The entry is written inside the caller's transaction (if logging fails, the action fails). Never put secrets (passwords) in `detail`. Action names in use: `case_created, case_routed, case_assigned, case_status, case_viewed, patient_admitted, patient_discharged, patient_record_viewed, staff_created, staff_updated, staff_password_reset, staff_deactivated, staff_reactivated, lab_ordered, lab_result_entered, lab_result_released, lab_result_cancelled, lab_result_viewed, lab_result_printed, lab_test_created, lab_test_updated, attendance_clock_in, attendance_clock_out, attendance_recorded, attendance_departure_recorded, attendance_confirmed, attendance_corrected`. Add new actions as plain strings; no migration needed. Log **every** view or change of patient data and every admin action.

**Permission helpers:** `cases/permissions.py`: `is_admin, is_medical, is_general_staff, headed_department, get_patient, can_view, can_route, can_assign, can_change_status, can_admit`. Staff management: `accounts/staff_rules.py: can_manage(actor, target)`, `assignable_roles(actor)`.

**Mixins:** `core/mixins.py`: `StaffRequiredMixin` (patients get 403), `AdminRequiredMixin` (admin roles only, others 403), `FrontDeskRequiredMixin` (administrative staff and admin roles only; helper `is_front_desk(user)`). All include `LoginRequiredMixin`.

**More permission helpers:** `laboratory/permissions.py`: `is_lab_staff, is_senior_lab, can_order, can_enter, can_release, can_cancel, can_view, can_print, results_for_case`. `attendance/permissions.py`: `has_staff_profile, is_officer, sees_team, visible_records, flagged, can_manage_record, can_record_arrival`.

**Staff management rules:** nobody manages themselves; patients and main admins are never managed through the portal; only a main admin manages sub admins; a sub admin manages everyone below; main admin accounts are never created through the portal; a demoted admin has `is_staff` cleared explicitly in the form code; supervisor loops are rejected; doctors and nurses must be in the Medical category.

---

## 9. URL map

| Prefix | Pages (names are `namespace:name`) |
|---|---|
| `/admin/` | Django admin (backup only) |
| `/accounts/` | `login/`, `logout/`, `dashboard/`, `staff/` (`staff_list`), `staff/new/`, `staff/<pk>/` (`staff_detail`), `staff/<pk>/edit/`, `staff/<pk>/password/`, `staff/<pk>/deactivate/`, `staff/<pk>/reactivate/` |
| `/departments/` | `list`, `new/`, `<pk>/`, `<pk>/edit/`, `staff/new/`, `staff/<pk>/edit/` (profile only, for an existing user) |
| `/patients/` | `list`, `<pk>/`, `new/` (`staff_register`), public `register`, `registered/`, `me/` (`my_profile`), families (`family_list`), `cards/` (`card_desk`), `cards/prices/` (`card_prices`) |
| `/cases/` | `home` (redirects by role), `new/`, `mine/`, `triage/`, `department/`, `assigned/`, `all/`, `<pk>/` (`detail`), `<pk>/route/`, `<pk>/assign/`, `<pk>/status/` |
| `/facilities/` | `overview`, buildings and wards CRUD, `wards/<pk>/beds/add/`, `admissions/` (`admission_list`), `cases/<case_pk>/admit/` (`admit`), `admissions/<pk>/discharge/` (`discharge`) |
| `/laboratory/` | `worklist` (`/`), `tests/` catalogue (`tests`, `test_create`, `test_update`), `order/<case_pk>/` (`order`), `results/<pk>/` (`result`), `results/<pk>/enter|release|cancel/`, `results/<pk>/print/` (`print`), `mine/` (patient results) |
| `/attendance/` | `mine` (`/`), `clock-in/`, `clock-out/`, `team/`, `record/new/` (`officer_record`), `record/<pk>/confirm|departure|correct/` |
| `/audit/` | `core:audit_list` (admin roles only, filters and search, read-only) |
| `/` | Temporary redirect to login |

Case pages use a case ID in the URL, but access is always checked against the user; unauthorized access returns 404 (the case's existence is not revealed). Dashboards never use an ID in the URL.

---

## 10. Security rules (non-negotiable)

- Never put a user or patient ID in dashboard URLs. Load data from `request.user`.
- Filter every query by what the logged-in user may see. `LoginRequiredMixin` on all portal views plus role checks.
- Department head sees only their department's cases and staff. Staff see only cases assigned to them. General staff see unrouted pending cases. Patients see only their own records. Support staff see **no** medical data.
- Patients cannot delete or edit medical records or results. (Planned: a request flow, Section 14.)
- Audit every view or change of patient data, and every admin action.
- Use `override_settings(PASSWORD_HASHERS=[MD5...])` in tests only.
- Planned: HTTPS, login lockout, encrypted backups, `REMOTE_ADDR` replaced by the real client IP behind a proxy, database permissions that stop edits to audit rows.

### Access matrix (current)

| Who | Cases | Patients | Staff pages | Audit log |
|---|---|---|---|---|
| Main/Sub admin | All (view) | All | Manage | View |
| Dept head | Own department; assigns | No | No | No |
| General staff | Unrouted queue; routes | No | No | No |
| Other medical | Assigned to them | Via case only | No | No |
| Front desk (admin category) | No | Register, card desk (admin roles too) | No | No |
| Support staff | None | None | No | No |
| Patient | Own | Own profile | No | No |

Laboratory: lab staff see the worklist and enter results; the assigned doctor, department head, or senior lab staff release; admins view all (audited); patients see only their own released results; support staff and unrelated staff see nothing. Attendance: everyone with a staff profile sees their own; heads and supervisors see their team; attendance officers and admins see everyone.

---

## 11. Testing

- Run everything: `python manage.py test`. Per app: `python manage.py test cases facilities`.
- Last full run: **132 tests, all passing** (accounts, cases, core, facilities, patients, dashboards, audit log). Added afterwards and **not yet confirmed by a test run on the developer's machine**: audit log page (no tests by request), staff management (`accounts/test_staff.py`), laboratory (`laboratory/tests.py`), front-desk rule (`patients/test_access.py`), attendance (`attendance/tests.py`). The developer's older `patients/tests.py` may need its staff user changed to an administrative staff member because of the front-desk rule.
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
- Registering patients and the card desk are **front desk only** (administrative staff and admins).
- Cases a patient files with a chosen department still go through triage by general staff before reaching the department head (confirmed with the developer).

---

## 14. Roadmap (build in this order)

1. **Confirm and commit** the delivered pieces (audit page, staff management, laboratory, front-desk rule, attendance). Run `python manage.py test`; fix any failures before building more.
2. **Duty roster** (planned shifts per staff, shown on staff dashboards; support staff roster by building or ward). Attendance can then compare actual and planned.
3. **Patient data requests**: a form for correction or deletion requests that goes to the records officer or an admin; staff review and everything is audited. Medical records are retained per legal retention rules (confirm the period with a lawyer).
4. **Login lockout** after repeated failures, and audit `login_success`, `login_failed`, `account_locked`.
5. **Nurse-to-ward assignment** so nurses see only admitted patients in their ward; cleaners assigned to buildings and wards.
6. **Lab result amendments** (a released result can be amended with a reason, keeping the old value and notifying the patient).
7. `website` (public pages and blog published from the portal), `appointments`, `pharmacy`, `billing` (Paystack or Flutterwave scope still open).
8. Security review and deployment: HTTPS, secure cookies, real client IP, backups, database permissions for audit rows, DEBUG off.

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
