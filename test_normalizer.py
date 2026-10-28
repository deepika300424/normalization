from normalizer import money, normalize_row
from schemas import LineExtraction


def test_money_preserves_decimal_precision_and_rejects_placeholders():
    assert money("$660.36") == "$660.36"
    assert money("800") == "$800"
    assert money("0") is None
    assert money("N/A") is None


def test_upgrade_guardrail_removes_switcher():
    product = {
        "product_name": "Test Phone",
        "brand": "Test",
        "variant": "256 GB",
        "pricing": {"monthly": "9.43", "retail": "1199.99", "options": ["36 mos."]},
        "shipment": "Free shipping",
        "stock": "in_stock",
    }
    extraction = LineExtraction(
        switcher="$800",
        switcher_offer_text="Switch and port in.",
        step_by_step_reasoning="Variant matches; switcher is eligible only for a new line.",
    )
    row = normalize_row(product, "Upgrade", extraction)
    assert row["SWITCHER"] is None
    assert row["SWITCHER_OFFER_TEXT"] is None
    assert row["RATEPLAN DURATION (MONTHS)"] == "36"
