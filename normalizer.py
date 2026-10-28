from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from config import CSV_COLUMNS
from schemas import LineExtraction

CURRENCY_PATTERN = re.compile(r"^\$?\s*(-?\d+(?:\.\d+)?)$")
PLACEHOLDERS = {"", "n/a", "na", "none", "null", "-", "0"}


def money(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in PLACEHOLDERS:
        return None
    match = CURRENCY_PATTERN.fullmatch(text.replace(",", ""))
    if not match:
        return None
    try:
        amount = Decimal(match.group(1))
    except InvalidOperation:
        return None
    if amount < 0:
        return None
    return f"${match.group(1)}"


def _text(value: Any) -> str | None:
    if value is None or str(value).strip().lower() in PLACEHOLDERS:
        return None
    return str(value).strip()


def _duration(product: dict[str, Any], extracted: LineExtraction) -> str | None:
    if extracted.rateplan_duration_months:
        return extracted.rateplan_duration_months
    text = " ".join(str(option) for option in product.get("pricing", {}).get("options", []))
    match = re.search(r"(\d+)\s*[- ]?mos?", text, re.IGNORECASE)
    return match.group(1) if match else None


def validate_extraction(extracted: LineExtraction) -> None:
    monetary_fields = (
        "switcher",
        "unique_discount",
        "max_trade_in_value",
        "pwp_gwp_offer_value",
        "subscription_bundle_offer_value",
        "service_line_offer_value",
        "additional_offer_value",
        "finance_offer_value",
    )
    for field_name in monetary_fields:
        value = getattr(extracted, field_name)
        if value is not None and money(value) is None:
            raise ValueError(f"Invalid monetary value in {field_name}: {value!r}")


def normalize_row(product: dict[str, Any], line_type: str, extracted: LineExtraction) -> dict[str, Any]:
    row: dict[str, Any] = {column: None for column in CSV_COLUMNS}
    pricing = product.get("pricing") or {}
    row.update({
        "PLAN TYPE": "AT&T Installment Plan" if pricing.get("monthly") else None,
        "PRODUCT NAME": product.get("product_name"),
        "BRAND": product.get("brand"),
        "VARIANT": product.get("variant"),
        "BASE": money(pricing.get("monthly")),
        "MSRP": money(pricing.get("retail")),
        "RESELLER LIST PRICE": None,
        "LINE TYPE": line_type,
        "SHIPMENT": product.get("shipment"),
        "STOCK": product.get("stock"),
        "RATEPLAN DURATION (MONTHS)": _duration(product, extracted),
        "SWITCHER": money(extracted.switcher),
        "SWITCHER_OFFER_TEXT": _text(extracted.switcher_offer_text),
        "UNIQUE DISCOUNT": money(extracted.unique_discount),
        "FREE MEMORY UPGRADE": _text(extracted.free_memory_upgrade),
        "BOGO OFFER": _text(extracted.bogo_offer),
        "Max TI": money(extracted.max_trade_in_value),
        "Trade-In Value Type (Enhanced/ Base)": _text(extracted.trade_in_value_type),
        "PWP/GWP OFFERS": _text(extracted.pwp_gwp_offers),
        "Cleaned PWP/GWP OFFERS": _text(extracted.cleaned_pwp_gwp_offers),
        "PWP/GWP OFFER $ VALUE": money(extracted.pwp_gwp_offer_value),
        "SUBSCRIPTION BUNDLE OFFERS": _text(extracted.subscription_bundle_offers),
        "SUBSCRIPTION BUNDLE OFFER $ VALUE": money(extracted.subscription_bundle_offer_value),
        "SERVICE LINE OFFERS": _text(extracted.service_line_offers),
        "SERVICE LINE OFFER $ VALUE": money(extracted.service_line_offer_value),
        "ADDITIONAL OFFERS": _text(extracted.additional_offers),
        "ADDITIONAL OFFER $ VALUE": money(extracted.additional_offer_value),
        "FINANCE OFFER DESCRIPTION 1": _text(extracted.finance_offer_description),
        "FINANCE OFFER $ VALUE": money(extracted.finance_offer_value),
    })
    if line_type == "Upgrade":
        row["SWITCHER"] = None
        row["SWITCHER_OFFER_TEXT"] = None
    return row
