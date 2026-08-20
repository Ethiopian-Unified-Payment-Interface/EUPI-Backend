"""
Simulated Core Banking System
=============================
Layer: 🔴 LAYER 3 — Infrastructure / Driven Adapters

A single stateful simulator shared by every bank adapter. It owns real account
balances, performs atomic debit/credit, and confirms settlement asynchronously,
so a transfer in the sandbox behaves like a transfer rather than returning a
formatted string.

Nothing here is money. EUPI is a pass-through orchestrator and never holds
customer funds; these balances are fixtures owned by the *simulated banks*. The
whole package sits behind `BankPort`, so integrating a real core banking system
means writing an adapter and deleting nothing else.
"""
