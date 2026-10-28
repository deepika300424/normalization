"""Gemini request construction, structured-response validation, and retries."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from google import genai
from google.genai import types
from pydantic import ValidationError

from config import MAX_RETRIES, MODEL_NAME
from normalizer import validate_extraction
from prompts import SYSTEM_PROMPT, build_llm_payload, user_prompt
from schemas import ExtractionResponse
from source_rules import apply_source_grounded_rules


class LLMExtractionError(RuntimeError):
    """Raised when a product cannot be extracted into the required response shape."""

    pass


logger = logging.getLogger(__name__)


def _gemini_response_schema() -> dict[str, Any]:
    """Adapt Pydantic JSON Schema to Gemini's supported response-schema subset."""
    schema = ExtractionResponse.model_json_schema()

    def remove_unsupported_keywords(value: Any) -> Any:
        """Recursively remove schema keywords unsupported by Gemini."""
        if isinstance(value, dict):
            return {
                key: remove_unsupported_keywords(item)
                for key, item in value.items()
                if key != "additionalProperties"
            }
        if isinstance(value, list):
            return [remove_unsupported_keywords(item) for item in value]
        return value

    return remove_unsupported_keywords(schema)


async def extract_product(
    client: genai.Client,
    product: dict[str, Any],
    semaphore: asyncio.Semaphore,
) -> ExtractionResponse:
    """Extract both line types for one product, retrying failed or invalid responses."""
    payload = build_llm_payload(product)
    correction = None
    async with semaphore:
        logger.info(
            "Processing product %r, variant %r with model %s",
            product.get("product_name"),
            product.get("variant"),
            MODEL_NAME,
        )
        for attempt in range(MAX_RETRIES):
            try:
                response = await client.aio.models.generate_content(
                    model=MODEL_NAME,
                    contents=user_prompt(payload, correction),
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        temperature=0,
                        response_mime_type="application/json",
                        response_schema=_gemini_response_schema(),
                    ),
                )
                if not response.text:
                    raise LLMExtractionError("LLM returned no structured response")
                extraction = ExtractionResponse.model_validate_json(response.text)
                extraction = apply_source_grounded_rules(product, extraction)
                validate_extraction(extraction.new_line)
                validate_extraction(extraction.upgrade)
                logger.info(
                    "Finished product %r, variant %r",
                    product.get("product_name"),
                    product.get("variant"),
                )
                return extraction
            except (ValidationError, LLMExtractionError, ValueError) as error:
                correction = str(error)
                if attempt == MAX_RETRIES - 1:
                    raise LLMExtractionError(
                        f"Structured extraction failed after {MAX_RETRIES} attempts: {error}"
                    ) from error
                logger.warning(
                    "Structured extraction attempt %d/%d failed for product %r, "
                    "variant %r: %s",
                    attempt + 1,
                    MAX_RETRIES,
                    product.get("product_name"),
                    product.get("variant"),
                    error,
                )
            except Exception as error:
                if attempt == MAX_RETRIES - 1:
                    raise LLMExtractionError(
                        f"LLM request failed after {MAX_RETRIES} attempts: {error}"
                    ) from error
                logger.warning(
                    "LLM request attempt %d/%d failed for product %r, variant %r: %s",
                    attempt + 1,
                    MAX_RETRIES,
                    product.get("product_name"),
                    product.get("variant"),
                    error,
                )
                await asyncio.sleep(2**attempt)
    raise AssertionError("unreachable")
