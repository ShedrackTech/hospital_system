"""Appointment rules in one place. Change a number here, not in the code."""

MAX_DAYS_AHEAD = 60            # how far ahead an appointment may be booked
MAX_UPCOMING_PER_PATIENT = 3   # open (scheduled, not yet over) appointments per patient
PATIENT_CANCEL_HOURS = 2       # a patient may cancel only this long before the start
REASON_MAX_LENGTH = 500
SLOT_MINUTES_CHOICES = (10, 15, 20, 30, 45, 60)
REMINDER_HOURS = 24            # a patient is reminded when the appointment is this close
