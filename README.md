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

The LLM receives only the product name, brand, variant, flattened promotion text, and accessory/add-on offers. Shipping, stock, price, reviews, and links remain deterministic Python inputs. The prompt requires the model to explain variant matching, eligibility, and composite arithmetic in `step_by_step_reasoning`; that field is validated but never written to CSV.

The post-validator preserves source decimal text when it is a valid non-negative monetary value and converts missing values, `N/A`, `0`, and `-` to blank CSV cells. Upgrade switcher fields are always blank even if the model returns them.

## Checks

```bash
python3 -m py_compile config.py schemas.py prompts.py extractor.py normalizer.py main.py
python3 -m pytest -q test_normalizer.py
```

The second command requires `pytest` in the active environment.
# data_normalization
# data_normalization
# data_normalization
