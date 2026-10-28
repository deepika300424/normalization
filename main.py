"""Command-line entry point for product promotion extraction and CSV generation."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import os
from pathlib import Path

from google import genai
from google.genai import types

from config import CSV_COLUMNS, MAX_CONCURRENT_REQUESTS, MODEL_NAME
from extractor import extract_product
from normalizer import normalize_row, validate_extraction

logger = logging.getLogger(__name__)


async def run(input_path: Path, output_path: Path) -> None:
    """Validate input products, extract offers, and write two CSV rows per product."""
    products = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(products, list):
        raise ValueError("Input JSON must contain an array of product objects")
    for index, product in enumerate(products):
        if not isinstance(product, dict):
            raise ValueError(f"Product at index {index} must be a JSON object")
        if product.get("pricing") is not None and not isinstance(product["pricing"], dict):
            raise ValueError(f"Product at index {index} has invalid pricing; expected an object")
        for field in ("offers", "accessories_offers", "additional_add_on_offers"):
            items = product.get(field, [])
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                raise ValueError(
                    f"Product at index {index} has invalid {field}; expected an array of objects"
                )
    logger.info(
        "Starting extraction for %d products with model %s",
        len(products),
        MODEL_NAME,
    )
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is required; copy .env.template to .env and configure it")

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=60_000),
    )
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    extractions = await asyncio.gather(
        *(extract_product(client, product, semaphore) for product in products)
    )

    rows = []
    for product, extraction in zip(products, extractions):
        validate_extraction(extraction.new_line)
        validate_extraction(extraction.upgrade)
        rows.append(normalize_row(product, "New Line", extraction.new_line))
        rows.append(normalize_row(product, "Upgrade", extraction.upgrade))

    try:
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    except PermissionError as error:
        raise PermissionError(
            f"Cannot write output file '{output_path}'. Close it if it is open in another "
            "program, check that it is not read-only, and try again."
        ) from error
    logger.info("Wrote %d rows to %s", len(rows), output_path)


def main() -> None:
    """Parse command-line arguments, configure logging, and run the pipeline."""
    parser = argparse.ArgumentParser(description="Normalize retailer promotions into a 29-column CSV")
    parser.add_argument("input", type=Path, help="Input product JSON array")
    parser.add_argument("output", type=Path, help="Output CSV path")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(run(args.input, args.output))
    except PermissionError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
