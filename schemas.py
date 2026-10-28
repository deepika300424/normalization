"""Pydantic response models defining Gemini's required extraction structure."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class LineExtraction(BaseModel):
    """Offer fields for one customer line type, plus required extraction reasoning."""

    model_config = ConfigDict(extra="forbid")

    switcher: Optional[str] = None
    switcher_offer_text: Optional[str] = None
    unique_discount: Optional[str] = None
    free_memory_upgrade: Optional[str] = None
    bogo_offer: Optional[str] = None
    max_trade_in_value: Optional[str] = None
    trade_in_value_type: Optional[str] = Field(default=None, description="Enhanced or Base")
    rateplan_duration_months: Optional[str] = None
    pwp_gwp_offers: Optional[str] = None
    cleaned_pwp_gwp_offers: Optional[str] = None
    pwp_gwp_offer_value: Optional[str] = None
    subscription_bundle_offers: Optional[str] = None
    subscription_bundle_offer_value: Optional[str] = None
    service_line_offers: Optional[str] = None
    service_line_offer_value: Optional[str] = None
    additional_offers: Optional[str] = None
    additional_offer_value: Optional[str] = None
    finance_offer_description: Optional[str] = None
    finance_offer_value: Optional[str] = None
    step_by_step_reasoning: str


class ExtractionResponse(BaseModel):
    """Structured extraction containing separate New Line and Upgrade results."""

    model_config = ConfigDict(extra="forbid")

    new_line: LineExtraction
    upgrade: LineExtraction
