"""Apply deterministic, source-text-backed corrections to Gemini extractions."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from prompts import build_llm_payload
from schemas import ExtractionResponse

MONEY_PATTERN = r"\$([\d,]+(?:\.\d{1,2})?)"
VARIANT_PATTERN = re.compile(r"\b(\d+(?:\.\d+)?)\s*(GB|TB)\b", re.IGNORECASE)
VARIANT_DISCOUNT_PATTERN = re.compile(
    rf"\bup to\s+{MONEY_PATTERN}\s+in\s+(?:bill\s+)?credits?\b",
    re.IGNORECASE,
)


def _variant_key(value: str | None) -> tuple[str, str] | None:
    """Normalize storage variants so equivalent GB/TB labels compare consistently."""
    if not value:
        return None
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(GB|TB)\s*", value, re.IGNORECASE)
    if not match:
        return None
    number = Decimal(match.group(1)).normalize()
    return format(number, "f"), match.group(2).upper()


def _variant_discounts(
    offer_text: str,
) -> tuple[dict[tuple[str, str], set[str]], bool]:
    """Find explicit storage-specific bill-credit amounts in offer text."""
    matches = list(VARIANT_PATTERN.finditer(offer_text))
    amounts: dict[tuple[str, str], set[str]] = {}
    has_variant_credit_schedule = False

    for index, match in enumerate(matches):
        key = _variant_key(f"{match.group(1)} {match.group(2)}")
        if key is None:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(offer_text)
        segment = offer_text[match.end():end]
        discount = VARIANT_DISCOUNT_PATTERN.search(segment)
        if discount is None:
            continue
        has_variant_credit_schedule = True
        amount = f"${discount.group(1).replace(',', '')}"
        amounts.setdefault(key, set()).add(amount)

    return amounts, has_variant_credit_schedule


def _requires_new_line(offer_text: str) -> bool:
    """Detect common explicit wording that limits an offer to new-line customers."""
    return bool(
        re.search(
            r"\b(?:requires?\s+(?:a\s+)?new line|"
            r"new customers activating new line|new consumer lines only)\b",
            offer_text,
            re.IGNORECASE,
        )
    )


def _has_monthly_service_credit(offer_text: str) -> bool:
    """Detect monthly bill credits identified as applicable to wireless service."""
    return bool(
        re.search(r"\$\d+(?:\.\d{1,2})?\s*/\s*mo\b", offer_text, re.IGNORECASE)
        and re.search(r"\bbill credits?\b", offer_text, re.IGNORECASE)
        and re.search(r"\bwireless service\b", offer_text, re.IGNORECASE)
    )


def _explicit_service_line_credit(
    product: dict[str, Any],
) -> tuple[str, str] | None:
    """Extract the unique total and description for the explicit service-line credit."""
    pattern = re.compile(
        rf"(?P<text>(?:price after\s+)?additional\s+"
        rf"(?P<amount>{MONEY_PATTERN})\s+in credits?\s*"
        rf"\(\s*\$\d+(?:\.\d{{1,2}})?\s*/\s*mo\.?\s*\)\s*"
        rf"for new consumer lines only)",
        re.IGNORECASE,
    )
    matches = {
        (match.group("amount").replace(",", ""), match.group("text"))
        for offer_text in build_llm_payload(product)["offers"]
        for match in pattern.finditer(offer_text)
    }
    return next(iter(matches)) if len(matches) == 1 else None


def _switcher_offer(
    product: dict[str, Any],
) -> tuple[str, str] | None:
    """Find a unique explicit switching incentive amount and its short offer text."""
    candidates: set[str] = set()
    source_text: str | None = None

    for offer in product.get("offers", []):
        if not isinstance(offer, dict):
            continue
        text = build_llm_payload({"offers": [offer]})["offers"][0]
        if not re.search(
            r"\bswitch(?:er|ing)?\b|\bswitch to\b|\bport[- ]?in\b|"
            r"\bbreak your contract\b",
            text,
            re.IGNORECASE,
        ):
            continue
        amounts = {
            f"${match.replace(',', '')}"
            for match in re.findall(
                rf"\bup to\s+(?:an?\s+)?{MONEY_PATTERN}",
                text,
                re.IGNORECASE,
            )
        }
        if len(amounts) == 1:
            candidates.update(amounts)
            source_text = " ".join(
                str(offer.get(key)).strip()
                for key in ("title", "description")
                if offer.get(key)
            )

    if len(candidates) != 1 or not source_text:
        return None
    return candidates.pop(), source_text


def _trade_in_max(product: dict[str, Any]) -> str | None:
    """Return a unique maximum amount explicitly tied to a trade-in offer."""
    amounts: set[str] = set()
    for offer_text in build_llm_payload(product)["offers"]:
        if not re.search(r"\btrade[- ]?in\b|\btrade in\b", offer_text, re.IGNORECASE):
            continue
        patterns = (
            rf"\btrade[- ]?in\b.{{0,100}}?\b(?:up to|maximum|max)\s+{MONEY_PATTERN}",
            rf"\b(?:up to|maximum|max)\s+{MONEY_PATTERN}.{{0,100}}?\btrade[- ]?in\b",
        )
        for pattern in patterns:
            amounts.update(
                f"${match.replace(',', '')}"
                for match in re.findall(pattern, offer_text, re.IGNORECASE)
            )
    return next(iter(amounts)) if len(amounts) == 1 else None


def _points_plus_totals(product: dict[str, Any]) -> tuple[str, str] | None:
    """Calculate assignment-defined New Line and Upgrade totals for the Points Plus offer."""
    text = "\n".join(build_llm_payload(product)["offers"])
    if not re.search(r"\bAT&T Points Plus\b", text, re.IGNORECASE):
        return None

    welcome = re.search(
        rf"\bwelcome bonus\s+{MONEY_PATTERN}\s+statement credit\b",
        text,
        re.IGNORECASE,
    )
    annual = re.search(
        rf"\b(?:up to\s+)?{MONEY_PATTERN}\s+in statement credits every year\b",
        text,
        re.IGNORECASE,
    )
    bill_discount = re.search(
        rf"{MONEY_PATTERN}\s+discounts? on (?:your )?AT&T bills\b",
        text,
        re.IGNORECASE,
    )
    if not (welcome and annual and bill_discount):
        return None

    welcome_amount, annual_amount, bill_amount = (
        Decimal(match.group(1).replace(",", ""))
        for match in (welcome, annual, bill_discount)
    )
    new_line_total = welcome_amount + annual_amount + bill_amount
    upgrade_total = annual_amount + bill_amount
    return f"${new_line_total:f}", f"${upgrade_total:f}"


def apply_source_grounded_rules(
    product: dict[str, Any],
    extraction: ExtractionResponse,
) -> ExtractionResponse:
    """Correct fields whose values and eligibility are explicit in source text."""
    payload = build_llm_payload(product)
    variant = _variant_key(payload.get("variant"))
    variant_discount: str | None = None
    discount_offer_requires_new_line = False
    discount_offer_has_service_credit = False
    has_variant_credit_schedule = False
    found_variant_amounts: set[str] = set()

    if variant is not None:
        for offer_text in payload["offers"]:
            amounts, has_schedule = _variant_discounts(offer_text)
            has_variant_credit_schedule |= has_schedule
            found_variant_amounts.update(amounts.get(variant, set()))
            if variant in amounts:
                discount_offer_requires_new_line |= _requires_new_line(offer_text)
                discount_offer_has_service_credit |= _has_monthly_service_credit(offer_text)
        if len(found_variant_amounts) == 1:
            variant_discount = next(iter(found_variant_amounts))

    switcher = _switcher_offer(product)
    service_line_credit = _explicit_service_line_credit(product)
    trade_in_max = _trade_in_max(product)
    points_plus_totals = _points_plus_totals(product)

    new_line_updates: dict[str, str | None] = {
        "switcher": None,
        "switcher_offer_text": None,
    }
    upgrade_updates: dict[str, str | None] = {
        "switcher": None,
        "switcher_offer_text": None,
    }

    if switcher is not None:
        amount, offer_text = switcher
        new_line_updates.update(
            switcher=amount,
            switcher_offer_text=offer_text,
        )

    if has_variant_credit_schedule:
        new_line_updates["unique_discount"] = variant_discount
        if discount_offer_requires_new_line:
            upgrade_updates["unique_discount"] = None
            if discount_offer_has_service_credit:
                upgrade_updates.update(
                    service_line_offers=None,
                    service_line_offer_value=None,
                )

    if service_line_credit is not None:
        amount, offer_text = service_line_credit
        new_line_updates.update(
            service_line_offers=offer_text,
            service_line_offer_value=amount,
        )
        upgrade_updates.update(
            service_line_offers=None,
            service_line_offer_value=None,
        )

    if trade_in_max is not None:
        new_line_updates["max_trade_in_value"] = trade_in_max
        upgrade_updates["max_trade_in_value"] = trade_in_max
    else:
        new_line_updates.update(
            max_trade_in_value=None,
            trade_in_value_type=None,
        )
        upgrade_updates.update(
            max_trade_in_value=None,
            trade_in_value_type=None,
        )

    if points_plus_totals is not None:
        new_line_updates["finance_offer_value"] = points_plus_totals[0]
        upgrade_updates["finance_offer_value"] = points_plus_totals[1]

    return extraction.model_copy(
        update={
            "new_line": extraction.new_line.model_copy(update=new_line_updates),
            "upgrade": extraction.upgrade.model_copy(update=upgrade_updates),
        }
    )
