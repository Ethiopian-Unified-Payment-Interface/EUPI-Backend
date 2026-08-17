"""
Domain Utility: PII Masking
Layer: 🟢 LAYER 1 — Enterprise Business Rules
Rule: ZERO external framework imports. Pure Python only.

Masking helpers for values that must not leave the system in full by default.

The Fayda Identification Number is Ethiopia's national identity number. It is
not an account reference and must never be treated as one: an operator browsing
a customer list has no need for a full FIN, and any endpoint that returns one
turns a single compromised session into a national-ID disclosure.

Default to masked. Reveal only where a role explicitly permits it, the caller
explicitly asks, and the reveal is written to the audit log.
"""

from __future__ import annotations

_VISIBLE_SUFFIX = 4


def mask_fin(fin: str | None) -> str:
    """
    Mask a Fayda Identification Number to its last four digits.

    Args:
        fin: The full 14-digit FIN, or None.

    Returns:
        A masked string such as "**********1234". Empty string for None.
        Values too short to mask meaningfully are fully masked rather than
        partially exposed.

    Examples:
        >>> mask_fin("12345678901234")
        '**********1234'
        >>> mask_fin("123")
        '***'
    """
    if not fin:
        return ""
    if len(fin) <= _VISIBLE_SUFFIX:
        return "*" * len(fin)
    return "*" * (len(fin) - _VISIBLE_SUFFIX) + fin[-_VISIBLE_SUFFIX:]


def mask_phone(phone: str | None) -> str:
    """
    Mask a phone number, keeping any country prefix and the last two digits.

    Enough to recognise a known number, not enough to dial or enumerate one.

    Args:
        phone: An E.164 phone number, or None.

    Returns:
        A masked string such as "+251*******67". Empty string for None.

    Examples:
        >>> mask_phone("+251911234567")
        '+251*******67'
    """
    if not phone:
        return ""

    prefix = ""
    digits = phone
    if phone.startswith("+") and len(phone) > 4:
        prefix, digits = phone[:4], phone[4:]

    if len(digits) <= 2:
        return prefix + "*" * len(digits)
    return prefix + "*" * (len(digits) - 2) + digits[-2:]


def mask_account_number(account_number: str | None) -> str:
    """
    Mask a bank account number to its last four digits.

    Args:
        account_number: The account number, or None.

    Returns:
        A masked string such as "****7890". Empty string for None.

    Examples:
        >>> mask_account_number("1000234567890")
        '****7890'
    """
    if not account_number:
        return ""
    if len(account_number) <= _VISIBLE_SUFFIX:
        return "*" * len(account_number)
    return "****" + account_number[-_VISIBLE_SUFFIX:]
