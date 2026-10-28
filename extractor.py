from __future__ import annotations

import asyncio
from typing import Any

from google import genai
from google.genai import types
from pydantic import ValidationError

from config import MAX_RETRIES, MODEL_NAME
from prompts import SYSTEM_PROMPT, build_llm_payload, user_prompt
from schemas import ExtractionResponse


class LLMExtractionError(RuntimeError):
    pass


def _gemini_response_schema() -> dict[str, Any]:
    """Adapt Pydantic JSON Schema to Gemini's supported response-schema subset."""
    schema = ExtractionResponse.model_json_schema()

    def remove_unsupported_keywords(value: Any) -> Any:
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
    payload = build_llm_payload(product)
    correction = None
    async with semaphore:
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
                return ExtractionResponse.model_validate_json(response.text)
            except (ValidationError, LLMExtractionError) as error:
                correction = str(error)
                if attempt == MAX_RETRIES - 1:
                    raise LLMExtractionError(
                        f"Structured extraction failed after {MAX_RETRIES} attempts: {error}"
                    ) from error
            except Exception as error:
                if attempt == MAX_RETRIES - 1:
                    raise LLMExtractionError(
                        f"LLM request failed after {MAX_RETRIES} attempts: {error}"
                    ) from error
                await asyncio.sleep(2**attempt)
    raise AssertionError("unreachable")
