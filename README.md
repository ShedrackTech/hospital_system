# Good Health Hospital: Hospital Management System

A hospital web platform built with Django. It has two sides:

- **A public website** (no login): one scrolling home page with About, Departments, Doctors, Services, Latest news and Contact sections, plus a blog.
- **A private portal**: patients and staff log in and see only what their role allows. A dashboard never shows another person's data.

> This file is a short guide. The full design, rules and history are in
> [`HOSPITAL_SYSTEM_DESIGN_v10.md`](HOSPITAL_SYSTEM_DESIGN_v10.md). **Read that file before changing code.**

---

## What it does

**Public website** (`/`)
- One home page with smooth-scrolling sections; the menu highlights the section being read.
- Doctor profiles with a **Book an Appointment** button (doctors appear only when an admin lists them).
- Blog (health news and hospital updates) with categories and paging.
- Contact form with a spam trap and a limit of 5 messages per IP address per hour.
- Admins run all of it from the portal at `/site/`.

**Portal**
- **Patients:** registration with a card number, family cards, book and cancel appointments, see released lab results (and print them), prescriptions and bills, ask for a copy, correction or deletion of their data.
- **Cases:** triage by general staff, routing to a department, assignment, status flow.
- **Wards:** buildings, wards, beds, admission and discharge, nurse ward assignments.
- **Laboratory:** ordering, entering and releasing results, and amendments with a reason (the old value is kept and the patient is told).
- **Pharmacy:** drug catalogue, stock batches, prescribing, dispensing (earliest expiry first), allergy warnings by name, ingredient and drug class.
- **Appointments:** weekly doctor hours, booking by patients and the front desk, outcomes, 24 hour reminders, optional link to a case.
- **Billing:** price list, invoices, manual payments (cash, transfer, POS). No payment gateway yet.
- **Attendance:** clock in and out, confirmation, corrections, duty roster.
- **Notifications:** in-app messages with an unread count. The wording is always general (no results, drug names or diagnoses).
- **Audit log:** every view or change of patient data and every admin action is recorded.

---

## Tech stack

- Python 3.14, Django 6.1
- PostgreSQL (database `hospital_db`)
- HTML, CSS and vanilla JavaScript. No JavaScript framework, no build step.
- `python-decouple` for settings in a `.env` file
- Pillow (for doctor photos and blog covers)

---

## Quick start (Windows)

```
cd C:\Users\USER-PC\hospital_system
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

1. Create a PostgreSQL database named `hospital_db`.
2. Create a `.env` file next to `manage.py`. Settings are read with `python-decouple`; see `hospital/settings.py` for the names it expects.
3. Set up the database and the first account:

```
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

4. Open `http://127.0.0.1:8000/`. The portal login is on the site's **Login** button.

The **main admin** is only ever created with `createsuperuser`, never through the portal.

---

## First-time setup in the portal

Do these once after installing, as an admin:

1. Make sure `INSTALLED_APPS` lists every project app (see below) and that `HOSPITAL_NAME` is set in `settings.py` (it appears on printed results and on the website).
2. Create a **General** (triage) department. It is never shown on the public site.
3. Create a **Laboratory** department with *Is laboratory* ticked, and a **Pharmacy** department with *Is pharmacy* ticked. Put their staff in them (Medical category).
4. Tick *Attendance officer* on the profiles of gateman and HR staff.
5. Doctors (or their head, or an admin) add weekly hours at `/appointments/availability/` before patients can book.
6. An admin adds items to the price list at `/billing/prices/` before invoices can be made.
7. Add drugs, give each one a **Drug class** (spelled the same way for every drug in a family, for example `Penicillins`), then receive stock.
8. Fill in the hospital details at `/site/info/` (About text, address, phones, opening hours). These feed the website's info bar and Contact section.
9. Schedule a daily run of `python manage.py send_appointment_reminders`.

---

## Roles

| Role | Notes |
|---|---|
| Main Admin | Superuser. Created with `createsuperuser`. |
| Sub Admin | Oversees everything. Only a main admin may create or manage one. |
| Department Head | The real test is that the user is the head of a department. |
| Senior Doctor, Doctor | Medical staff. |
| Senior Nurse, Nurse | Medical staff. |
| Senior Staff, Staff | Administrative or support staff. |
| Patient | Default role of a new account. |

Staff are grouped by category: **medical** (sees only assigned cases), **admin** (front desk, records, accounts) and **support** (cleaners, gateman, drivers; **no** patient data at all). Patients log in with a username or card number (`PAT000001`); staff with a username or staff ID (`STF000001`).

---

## Project layout

| App | Purpose |
|---|---|
| `accounts` | Users, login, role dashboards, staff management |
| `core` | Access mixins, audit log, login lockout |
| `departments` | Departments and staff profiles |
| `patients` | Patient records, allergies, history, family cards, registration |
| `cases` | Cases, triage, assignment |
| `facilities` | Wards, beds, admissions |
| `datarequests` | Patient data requests |
| `website` | Public site and its admin pages at `/site/` |
| `laboratory` | Tests, results, amendments |
| `attendance` | Attendance and duty roster |
| `pharmacy` | Drugs, stock, prescriptions, dispensing |
| `appointments` | Doctor hours, bookings, reminders |
| `billing` | Price list, invoices, payments |
| `notifications` | In-app notifications |

Project settings are in `hospital/`. Shared styles are in `static/css/theme.css`; each app has its own file at `static/css/<app>.css`. Do not write `<style>` blocks, `<script>` blocks or `style=` attributes inside templates.

`appointments` and `website` keep their templates inside the app; the other apps use the project-level `templates/<app>/` folder.

---

## Tests

```
python manage.py test               # everything (about two minutes; do not stop it with Ctrl+C)
python manage.py test website       # one app
```

The last full run was **524 passing tests** on 17 October 2026. The public website became one scrolling page after that, so run `python manage.py test website` first and update any test that expects the old separate pages.

---

## Security

- Dashboards load data from the logged-in user, never from an ID in the URL.
- Every query is filtered by what the user may see; support staff see no medical data.
- Patients cannot edit or delete medical records or results.
- Audit writes are part of the same transaction as the action. If logging fails, the action fails.
- Logins are rate limited (lockout).

**Not finished yet: deployment hardening.** Before going live, work through the list in Section 14 of the design file: `collectstatic` and a static file server, HTTPS and secure cookies, `DEBUG = False`, `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`, a strong secret key and database password in `.env`, the real client IP behind a proxy, a real email backend, safe serving of uploaded media, encrypted backups, database permissions that stop edits to audit rows, and a check of every page as each role. The Nigeria Data Protection Act applies (and HIPAA or GDPR if those regions are served).

---

## Working on this project

- Make small, targeted changes; keep working code as it is.
- Use plain Django views and templates (no DRF, no JavaScript framework).
- Everyday admin work belongs in the portal; Django admin is only a backup.
- Before copying any shared file (`hospital/urls.py`, `templates/base.html`, `accounts/dashboards.py`, `departments/models.py`, `cases/views.py`), run `git diff` on it. Other work has been overwritten this way before.
- Every app folder needs an `__init__.py`, and a new app needs an entry in `INSTALLED_APPS`.
