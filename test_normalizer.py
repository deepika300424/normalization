"""Regression tests for extraction rules, CSV normalization, and pipeline behavior."""

import asyncio
import csv
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from config import CSV_COLUMNS
from extractor import extract_product
from main import run
from normalizer import money, normalize_row
from schemas import ExtractionResponse, LineExtraction
from source_rules import apply_source_grounded_rules

EXPECTED_COLUMNS = [
    "PLAN TYPE",
    "PRODUCT NAME",
    "BRAND",
    "VARIANT",
    "BASE",
    "MSRP",
    "RESELLER LIST PRICE",
    "SWITCHER",
    "SWITCHER_OFFER_TEXT",
    "UNIQUE DISCOUNT",
    "FREE MEMORY UPGRADE",
    "BOGO OFFER",
    "Max TI",
    "Trade-In Value Type (Enhanced/ Base)",
    "LINE TYPE",
    "RATEPLAN DURATION (MONTHS)",
    "SHIPMENT",
    "STOCK",
    "PWP/GWP OFFERS",
    "Cleaned PWP/GWP OFFERS",
    "PWP/GWP OFFER $ VALUE",
    "SUBSCRIPTION BUNDLE OFFERS",
    "SUBSCRIPTION BUNDLE OFFER $ VALUE",
    "SERVICE LINE OFFERS",
    "SERVICE LINE OFFER $ VALUE",
    "ADDITIONAL OFFERS",
    "ADDITIONAL OFFER $ VALUE",
    "FINANCE OFFER DESCRIPTION 1",
    "FINANCE OFFER $ VALUE",
]


def test_money_preserves_decimal_precision_and_rejects_placeholders():
    """Verify currency formatting removes redundant zeros and rejects placeholders."""
    assert money("$660.36") == "$660.36"
    assert money("800") == "$800"
    assert money("$200.00") == "$200"
    assert money("$244.360") == "$244.36"
    assert money("0") is None
    assert money("$0.00") is None
    assert money("N/A") is None


def test_upgrade_guardrail_removes_switcher():
    """Ensure normalization always clears switcher values from Upgrade rows."""
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


def test_plan_type_comes_from_product_field_not_monthly_pricing():
    """Ensure PLAN TYPE uses the explicit product field instead of monthly pricing."""
    product = {
        "plan_type": "Eligible Unlimited",
        "pricing": {"monthly": "9.43"},
    }

    row = normalize_row(
        product,
        "New Line",
        LineExtraction(step_by_step_reasoning="Test."),
    )

    assert row["PLAN TYPE"] == "Eligible Unlimited"


def test_assignment_example_is_source_grounded_for_both_line_types():
    """Check assignment example amounts and eligibility for New Line and Upgrade."""
    product = json.loads(
        Path(__file__).with_name("example.json").read_text(encoding="utf-8")
    )[0]
    deliberately_incorrect = LineExtraction(
        switcher="$999",
        switcher_offer_text="unsupported switcher offer",
        unique_discount="$1",
        max_trade_in_value="$500",
        service_line_offers="Ineligible service offer.",
        service_line_offer_value="$200",
        finance_offer_value="$1",
        step_by_step_reasoning="Untrusted initial values.",
    )
    extraction = ExtractionResponse(
        new_line=deliberately_incorrect,
        upgrade=deliberately_incorrect,
    )

    corrected = apply_source_grounded_rules(product, extraction)

    assert corrected.new_line.switcher == "$800"
    assert "switch" in corrected.new_line.switcher_offer_text.lower()
    assert corrected.new_line.unique_discount == "$660.36"
    assert corrected.new_line.service_line_offer_value == "$200"
    assert corrected.new_line.max_trade_in_value is None
    assert corrected.new_line.finance_offer_value == "$450"
    assert corrected.upgrade.switcher is None
    assert corrected.upgrade.switcher_offer_text is None
    assert corrected.upgrade.unique_discount is None
    assert corrected.upgrade.service_line_offers is None
    assert corrected.upgrade.service_line_offer_value is None
    assert corrected.upgrade.max_trade_in_value is None
    assert corrected.upgrade.finance_offer_value == "$250"

    new_row = normalize_row(product, "New Line", corrected.new_line)
    upgrade_row = normalize_row(product, "Upgrade", corrected.upgrade)
    assert new_row["UNIQUE DISCOUNT"] == "$660.36"
    assert new_row["SERVICE LINE OFFER $ VALUE"] == "$200"
    assert new_row["SWITCHER"] == "$800"
    assert new_row["FINANCE OFFER $ VALUE"] == "$450"
    assert new_row["Max TI"] is None
    assert upgrade_row["UNIQUE DISCOUNT"] is None
    assert upgrade_row["SERVICE LINE OFFER $ VALUE"] is None
    assert upgrade_row["SWITCHER"] is None
    assert upgrade_row["FINANCE OFFER $ VALUE"] == "$250"


def test_variant_specific_discount_changes_with_product_variant():
    """Ensure the deterministic rule selects the amount for the exact storage variant."""
    product = json.loads(
        Path(__file__).with_name("example.json").read_text(encoding="utf-8")
    )[0]
    product["variant"] = "1 TB"
    extraction = ExtractionResponse(
        new_line=LineExtraction(
            unique_discount="$660.36",
            step_by_step_reasoning="Incorrect variant amount.",
        ),
        upgrade=LineExtraction(
            unique_discount="$660.36",
            step_by_step_reasoning="Incorrect variant amount.",
        ),
    )

    corrected = apply_source_grounded_rules(product, extraction)

    assert corrected.new_line.unique_discount == "$628.36"
    assert corrected.upgrade.unique_discount is None


def test_assignment_output_schema_has_exactly_29_headers():
    """Verify normalized rows and emitted CSV headers match the assignment schema."""
    assert CSV_COLUMNS == EXPECTED_COLUMNS

    row = normalize_row(
        {"product_name": "Test phone", "variant": "256 GB"},
        "New Line",
        LineExtraction(step_by_step_reasoning="Test."),
    )
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    writer.writerow(row)
    assert list(row) == CSV_COLUMNS
    assert next(csv.reader(io.StringIO(stream.getvalue()))) == CSV_COLUMNS


def test_main_writes_exactly_two_rows_per_product(tmp_path, monkeypatch):
    """Verify the pipeline writes one New Line and one Upgrade row per product."""
    product = json.loads(
        Path(__file__).with_name("example.json").read_text(encoding="utf-8")
    )[0]
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.csv"
    input_path.write_text(json.dumps([product]), encoding="utf-8")
    extraction = ExtractionResponse(
        new_line=LineExtraction(step_by_step_reasoning="Test."),
        upgrade=LineExtraction(step_by_step_reasoning="Test."),
    )

    async def fake_extract_product(client, product, semaphore):
        """Return the canned response instead of sending a test API request."""
        return extraction

    monkeypatch.setattr("main.os.getenv", lambda name: "test-key")
    monkeypatch.setattr("main.genai.Client", lambda **kwargs: object())
    monkeypatch.setattr("main.extract_product", fake_extract_product)

    asyncio.run(run(input_path, output_path))

    with output_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    assert reader.fieldnames == EXPECTED_COLUMNS
    assert len(rows) == 2
    assert [row["LINE TYPE"] for row in rows] == ["New Line", "Upgrade"]


def test_extractor_logs_product_variant_and_model(caplog):
    """Verify extraction logs include the product, variant, and configured model."""
    product = json.loads(
        Path(__file__).with_name("example.json").read_text(encoding="utf-8")
    )[0]
    response = ExtractionResponse(
        new_line=LineExtraction(step_by_step_reasoning="Test."),
        upgrade=LineExtraction(step_by_step_reasoning="Test."),
    )

    async def fake_generate_content(**kwargs):
        """Return a canned JSON response for the extractor logging test."""
        return SimpleNamespace(text=response.model_dump_json())

    client = SimpleNamespace(
        aio=SimpleNamespace(
            models=SimpleNamespace(generate_content=fake_generate_content)
        )
    )
    caplog.set_level("INFO", logger="extractor")

    asyncio.run(extract_product(client, product, asyncio.Semaphore(1)))

    assert "Apple iPhone 17 Pro Max" in caplog.text
    assert "256 GB" in caplog.text
    assert "gemini-3.7-flash" in caplog.text


def test_output_permission_error_explains_how_to_fix(tmp_path, monkeypatch):
    """Verify a locked output file raises an actionable permission error."""
    product = {"product_name": "Test phone", "offers": []}
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.csv"
    input_path.write_text(json.dumps([product]), encoding="utf-8")
    extraction = ExtractionResponse(
        new_line=LineExtraction(step_by_step_reasoning="Test."),
        upgrade=LineExtraction(step_by_step_reasoning="Test."),
    )

    async def fake_extract_product(client, product, semaphore):
        """Return the canned response before simulating an output permission error."""
        return extraction

    original_open = Path.open

    def deny_output_write(path, *args, **kwargs):
        """Simulate a locked CSV while allowing the test input to be read normally."""
        if path == output_path and args and args[0] == "w":
            raise PermissionError("locked")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr("main.os.getenv", lambda name: "test-key")
    monkeypatch.setattr("main.genai.Client", lambda **kwargs: object())
    monkeypatch.setattr("main.extract_product", fake_extract_product)
    monkeypatch.setattr(Path, "open", deny_output_write)

    with pytest.raises(PermissionError, match="Close it if it is open"):
        asyncio.run(run(input_path, output_path))
