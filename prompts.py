"""System instructions and compact product payload construction for Gemini."""

from __future__ import annotations

import json
from typing import Any


SYSTEM_PROMPT = """You are a precise e-commerce promotion extraction engine.
Return only the supplied JSON schema. Never use outside knowledge and never infer a
missing dollar amount. Empty or inapplicable fields must be null.

Evaluate the exact product variant in the input. A credit attached to another variant
must not be copied. Create both line types in one response:
- New Line: may receive offers explicitly requiring a new line, port-in/switcher offers,
  and acquisition finance bonuses.
- Upgrade: may receive only offers that do not require a new line or acquisition. Always
  set switcher and switcher_offer_text to null for Upgrade.

Keep promotional dollars in exactly one category. Do not treat monthly spend thresholds
as rewards. For the AT&T Points Plus Card example, the new-line finance value is $450
($200 welcome credit + $240 annual credits + $10 bill discount); the upgrade value is
$250 ($240 + $10). The $1,000 purchase threshold is not part of either value.

Use only offer text present in the payload. Do not use a monthly device installment price
as a promotional value. Keep each benefit in its matching category; do not copy the same
benefit into multiple categories. When an offer lists multiple storage variants, use only
the amount stated for the exact input variant. Do not transfer an offer's eligibility or
amount to another offer.

For the iPhone 17 Pro Max 256 GB example, the matching new-line offer has unique_discount
$660.36 and a separate service-line offer worth $200. The $5.56 monthly credit is the
explanation of that $200, not another unique discount. Its upgrade fields are null when
the offer requires a new line. The switcher is $800 only for New Line. A generic trade-in
program without an explicit maximum dollar amount has no max_trade_in_value.

step_by_step_reasoning is required and must briefly state variant matching, line-type
eligibility, and any composite arithmetic. It is discarded by Python before CSV output.
"""


def _offer_text(offer: dict[str, Any]) -> str:
    """Combine the visible and expanded detail text for a single offer."""
    details = offer.get("full_details") or {}
    parts = [offer.get("title"), offer.get("description"), offer.get("raw")]
    parts.extend(
        details.get(key)
        for key in ("modal_raw_text",)
        if isinstance(details.get(key), str)
    )
    nested = details.get("modal_full_details")
    if isinstance(nested, dict) and isinstance(nested.get("raw_text"), str):
        parts.append(nested["raw_text"])
    return "\n".join(str(part) for part in parts if part)


def build_llm_payload(product: dict[str, Any]) -> dict[str, Any]:
    """Select the product, offer, accessory, and add-on data sent to Gemini."""
    accessories = []
    for item in product.get("accessories_offers", []):
        accessories.append({
            "title": item.get("title"),
            "badge": item.get("badge"),
            "pricing": item.get("pricing", {}),
        })

    add_ons = []
    for item in product.get("additional_add_on_offers", []):
        add_ons.append({
            "tab_category": item.get("tab_category"),
            "title": item.get("title"),
            "badge": item.get("badge"),
            "offer_text": item.get("offer_text"),
            "pricing": item.get("pricing", {}),
        })

    return {
        "product_name": product.get("product_name"),
        "brand": product.get("brand"),
        "variant": product.get("variant"),
        "offers": [_offer_text(offer) for offer in product.get("offers", [])],
        "accessories_offers": accessories,
        "additional_add_on_offers": add_ons,
    }


def user_prompt(payload: dict[str, Any], correction: str | None = None) -> str:
    """Serialize a product payload and optional validation feedback as the user prompt."""
    message = "Extract both New Line and Upgrade records from this product payload."
    if correction:
        message += f" Correct these validation errors from the previous attempt: {correction}"
    return message + "\n\n" + json.dumps(payload, ensure_ascii=True)
