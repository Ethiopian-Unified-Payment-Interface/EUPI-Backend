"""
Mock Fayda National ID Registry
=================================
Layer: 🔴 LAYER 3 — Infrastructure / Mock Data

A fixed dataset of test identities standing in for the real Fayda national
registry. Provides deterministic FIN → identity mappings so the same FIN
always returns the same person — required for stateful features like user
accounts and linked bank accounts.

Used by FaydaAdapter.confirm_kyc_otp() to look up verified identity data
instead of generating random identities on each call.
"""

from __future__ import annotations

FAYDA_REGISTRY = {
    "12345678901234": {
        "full_name": "Abebe Girma Tadesse",
        "phone_number": "+251911234567",
        "date_of_birth": "1990-05-15",
        "gender": "MALE"
    },
    "21872187218777": {
        "full_name": "Daniel Kebede Woldetsadik",
        "phone_number": "+251904267039",
        "date_of_birth": "2003-03-11",
        "gender": "MALE"
        },
    "23456789012345": {
        "full_name": "Selamawit Bekele Hailu",
        "phone_number": "+251922345678",
        "date_of_birth": "1995-08-22",
        "gender": "FEMALE"
    },
    "34567890123456": {
        "full_name": "Tewodros Kassahun",
        "phone_number": "+251933456789",
        "date_of_birth": "1988-11-10",
        "gender": "MALE"
    },
    "45678901234567": {
        "full_name": "Betelhem Desalegn",
        "phone_number": "+251944567890",
        "date_of_birth": "1992-02-14",
        "gender": "FEMALE"
    },
    "56789012345678": {
        "full_name": "Yared Ashenafi",
        "phone_number": "+251955678901",
        "date_of_birth": "1985-06-30",
        "gender": "MALE"
    },
    "67890123456789": {
        "full_name": "Mekdes Worku",
        "phone_number": "+251966789012",
        "date_of_birth": "1998-09-05",
        "gender": "FEMALE"
    },
    "78901234567890": {
        "full_name": "Henok Tilahun",
        "phone_number": "+251977890123",
        "date_of_birth": "1991-12-25",
        "gender": "MALE"
    },
    "89012345678901": {
        "full_name": "Hirut Zewdu",
        "phone_number": "+251988901234",
        "date_of_birth": "1987-04-18",
        "gender": "FEMALE"
    },
    "90123456789012": {
        "full_name": "Ermias Tsegaye",
        "phone_number": "+251999012345",
        "date_of_birth": "1994-07-12",
        "gender": "MALE"
    },
    "01234567890123": {
        "full_name": "Tigist Alemu",
        "phone_number": "+251910123456",
        "date_of_birth": "1996-03-08",
        "gender": "FEMALE"
    },
    "11223344556677": {
        "full_name": "Abel Berhanu",
        "phone_number": "+251920234567",
        "date_of_birth": "1989-10-20",
        "gender": "MALE"
    },
    "22334455667788": {
        "full_name": "Eden Tesfaye",
        "phone_number": "+251930345678",
        "date_of_birth": "1993-01-15",
        "gender": "FEMALE"
    }
}

def get_identity(fin: str) -> dict | None:
    """Look up a FIN in the mock registry. Returns the identity dict or None."""
    return FAYDA_REGISTRY.get(fin)
