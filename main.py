from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
from pathlib import Path

from google import genai

from config import CSV_COLUMNS, MAX_CONCURRENT_REQUESTS
from extractor import extract_product
from normalizer import normalize_row, validate_extraction


async def run(input_path: Path, output_path: Path) -> None:
    products = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(products, list):
        raise ValueError("Input JSON must contain an array of product objects")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is required; copy .env.example to .env and configure it")

    client = genai.Client(api_key=api_key)
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

    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize retailer promotions into a 29-column CSV")
    parser.add_argument("input", type=Path, help="Input product JSON array")
    parser.add_argument("output", type=Path, help="Output CSV path")
    args = parser.parse_args()
    asyncio.run(run(args.input, args.output))


if __name__ == "__main__":
    main()
