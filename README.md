# Data Normalization and LLM Extraction Pipeline

This project converts retailer product JSON into the assignment's exact 29-column CSV schema. It uses a hybrid Python + Gemini design:

- Python loads and validates the input, prunes static metadata before the API call, maps product metadata, formats currency, applies the Upgrade switcher guardrail, expands each product into two rows, and writes CSV.
- The Gemini structured-output call handles variant matching, promotion classification, line-type eligibility, cleaned descriptions, and composite promotion arithmetic.
- Pydantic rejects unexpected fields and malformed structured responses. The extractor retries transient failures and sends validation errors back as correction context.

## Setup

Use a project virtual environment, then install the pinned dependency categories:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
```

Set `GEMINI_API_KEY` in `.env`. `GEMINI_MODEL` defaults to `gemini-3.7-flash`.

## Run

```bash
python3 main.py Input.json output.csv
```

The input is processed record by record. At most five requests run concurrently. Each product produces exactly two output rows: `New Line` and `Upgrade`. With the supplied `Input.json`, the output contains 24 data rows plus the header.

## Design Notes

### Architecture Overview

The pipeline deliberately separates semantic interpretation from deterministic data processing:

1. Python reads the complete input JSON array and processes each product independently.
2. Python maps reliable top-level metadata such as product name, brand, variant, pricing, shipment, and stock.
3. Python builds a reduced LLM payload containing only the fields needed for promotion reasoning. Large static fields such as reviews, product links, and shipping text are not sent to Gemini.
4. Gemini analyzes the promotion language and returns both `new_line` and `upgrade` results in a single structured response.
5. Pydantic validates the response shape and required reasoning field.
6. Python validates monetary values and applies business guardrails, including the rule that Upgrade rows cannot receive switcher offers.
7. Python expands each product into exactly two CSV rows and writes the fixed 29-column schema.

This division prevents the LLM from controlling deterministic fields while still using it for the semantic tasks that regular string matching cannot reliably solve.

### File-by-File Responsibilities

#### `config.py`

This file contains shared configuration and the output contract:

- Loads environment variables through `python-dotenv`.
- Defines the Gemini model name using `GEMINI_MODEL`.
- Defines the maximum number of concurrent requests and retry attempts.
- Defines `CSV_COLUMNS`, the authoritative list of all 29 required output headers.

Keeping the column list in one place prevents accidental header omissions or column renaming during CSV serialization.

#### `schemas.py`

This file defines the Pydantic structured-output models:

- `LineExtraction` represents the promotion fields for one line type.
- `ExtractionResponse` contains both `new_line` and `upgrade` objects.
- Optional fields represent promotions that may not exist for a product.
- `step_by_step_reasoning` is required so the model must explicitly account for variant matching, eligibility, and composite calculations.
- `extra="forbid"` makes post-response validation strict and rejects unexpected fields.

The reasoning field is used for quality control and debugging only. It is intentionally excluded from the final CSV.

#### `prompts.py`

This file owns the LLM instructions and payload preparation:

- `SYSTEM_PROMPT` defines the extraction rules, including strict variant matching, New Line versus Upgrade eligibility, non-duplication, and the Citi finance calculation.
- The prompt includes the assignment’s iPhone example as a few-shot reference. It demonstrates that `$660.36` belongs in `UNIQUE DISCOUNT`, while the separate `$200` credit belongs in `SERVICE LINE OFFER $ VALUE`.
- `_offer_text()` flattens nested offer data such as titles, descriptions, raw text, and modal details into text the model can reason over.
- `build_llm_payload()` strips unnecessary product metadata and retains the product identity, exact variant, offers, and accessory/add-on information.
- `user_prompt()` serializes the reduced payload and adds correction details when a previous extraction fails validation.

#### `extractor.py`

This file is the Gemini extraction engine:

- Uses the native `google-genai` SDK and its asynchronous API.
- Calls Gemini once per product and requests both line types in one response.
- Requests JSON output using `response_mime_type="application/json"`.
- Passes a Gemini-compatible response schema derived from the Pydantic model.
- Removes `additionalProperties` from the schema because Gemini does not accept that JSON Schema keyword, while Pydantic still performs strict validation after the response.
- Limits simultaneous calls using the semaphore supplied by `main.py`.
- Retries structured validation failures and transient API failures up to `MAX_RETRIES` times.
- Sends validation error details back into the next prompt attempt so the model can correct its output.

#### `normalizer.py`

This file converts the validated LLM result into the final CSV row:

- `money()` accepts valid numeric currency values, preserves exact decimal text, adds a leading `$`, and turns placeholders such as `N/A`, `0`, and `-` into blank values.
- `_text()` normalizes optional text fields and converts empty placeholders to `None`.
- `_duration()` extracts the installment duration from the LLM result or falls back to the product’s pricing options.
- `validate_extraction()` verifies every monetary extraction before serialization.
- `normalize_row()` maps deterministic product fields and semantic extraction fields to the exact CSV headers.
- The Upgrade guardrail always clears `SWITCHER` and `SWITCHER_OFFER_TEXT`, even if Gemini incorrectly returns those values.

#### `main.py`

This is the command-line entry point and orchestration layer:

1. Reads the input path supplied on the command line.
2. Verifies that the JSON root is a list of products.
3. Loads `GEMINI_API_KEY` and creates the Gemini client.
4. Creates an `asyncio.Semaphore(5)` to limit concurrency.
5. Runs one extraction task per product with `asyncio.gather()`.
6. Validates both line-type results for every product.
7. Creates one `New Line` row and one `Upgrade` row per product.
8. Writes the header and rows using `csv.DictWriter`.

#### `test_normalizer.py`

This file contains focused tests for the deterministic layer:

- Verifies that currency values preserve decimals, such as `$660.36`.
- Verifies that placeholders such as `0` and `N/A` become empty values.
- Verifies that the Upgrade switcher guardrail removes switcher values.
- Verifies fallback extraction of the 36-month rate plan duration.

#### `requirements.txt` and `.env.example`

`requirements.txt` declares the runtime libraries: Gemini SDK, Pydantic, and environment-variable loading. `.env.example` documents the required `GEMINI_API_KEY` and optional model override without committing secrets to the repository.

### End-to-End Processing Steps

#### Step 1: Load and validate input

`main.py` loads `Input.json` as a Python list. Each list item is treated as an independent product and never combined with another product’s offers. This record-level processing prevents a large input file from exceeding the LLM context window and limits the impact of a failed request.

#### Step 2: Map deterministic product data

Product name, brand, variant, monthly price, retail price, shipment, and stock come directly from the input object. These fields do not require semantic interpretation and therefore remain under Python’s control.

#### Step 3: Prune and prepare the LLM payload

The payload includes the exact product variant because variant matching is a hard eligibility gate. It includes flattened promotion text and accessory/add-on arrays because those fields may contain PWP/GWP, subscription, BOGO, or related offer information. Reviews, links, shipping details, and other static metadata are omitted from the LLM request.

#### Step 4: Extract both line types

Gemini receives one product at a time and must return:

- `new_line`: offers available when a customer activates a new line, including eligible switcher and acquisition offers.
- `upgrade`: offers available to an existing customer upgrading a line. Switcher offers are not eligible for this row.

The model must match credits to the exact storage variant. For example, a `$660.36` credit for a 256 GB device must not be copied to a 512 GB or 1 TB row.

#### Step 5: Validate and retry

The Gemini response is parsed with Pydantic. Missing optional promotions are allowed, but malformed monetary strings, unexpected fields, and missing reasoning are rejected. The extractor retries failures and includes the previous error in the next request when correction is possible.

#### Step 6: Apply Python guardrails

After LLM extraction, Python validates monetary fields and formats them consistently. It also clears switcher values for Upgrade rows regardless of the model response. This protects the final dataset from common semantic hallucinations and ensures that the CSV contract is enforced outside the LLM.

#### Step 7: Expand rows and serialize CSV

Each product produces exactly two rows in a predictable order: New Line first, followed by Upgrade. All 29 headers are written even when a value is missing. Missing values are emitted as empty CSV cells rather than `N/A`, `0`, or `-`.

### Review Checklist

Reviewers can verify the implementation by checking:

- The number of data rows is exactly twice the number of input products.
- The output header contains exactly 29 columns.
- New Line and Upgrade rows exist for every product.
- Upgrade switcher fields are blank.
- Variant-specific credits are not copied between storage variants.
- Citi finance values distinguish New Line acquisition credit from Upgrade recurring benefits.
- Spend thresholds are described as conditions, not incorrectly added to reward totals.
- Monetary values retain source precision and use a leading `$`.
- Missing values remain blank.
## Checks

```bash
python3 -m py_compile config.py schemas.py prompts.py extractor.py normalizer.py main.py
python3 -m pytest -q test_normalizer.py
```

The second command requires `pytest` in the active environment.
