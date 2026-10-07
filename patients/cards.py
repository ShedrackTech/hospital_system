import calendar
from datetime import date

from django.utils import timezone

from .models import CardRenewal, CardType, Family, Patient


def add_months(start, months):
    """Add whole months to a date. Jan 31 + 1 month gives the last day of February."""
    index = start.month - 1 + months
    year = start.year + index // 12
    month = index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def card_type_for(holder):
    kind = CardType.Kind.FAMILY if isinstance(holder, Family) else CardType.Kind.SINGLE
    return CardType.for_kind(kind)


def next_period(holder, card_type=None, today=None):
    """
    The dates the next payment would cover.
    A card that is still valid is extended from its expiry date.
    An expired or new card starts today.
    """
    today = today or timezone.localdate()
    card_type = card_type or card_type_for(holder)
    current = holder.latest_card_renewal
    if current and current.expires_on >= today:
        starts_on = current.expires_on
    else:
        starts_on = today
    return starts_on, add_months(starts_on, card_type.validity_months)


def issue_card(holder, received_by=None, today=None):
    """
    Issue or renew a card for a Patient (single card) or a Family (family card)
    and record the fee that was charged.
    """
    if isinstance(holder, Patient) and holder.family_id:
        raise ValueError("This patient is covered by a family card. Renew the family card.")

    card_type = card_type_for(holder)
    starts_on, expires_on = next_period(holder, card_type, today)
    is_family = isinstance(holder, Family)
    return CardRenewal.objects.create(
        patient=None if is_family else holder,
        family=holder if is_family else None,
        card_type=card_type,
        starts_on=starts_on,
        expires_on=expires_on,
        amount_charged=card_type.fee,
        received_by=received_by,
    )
