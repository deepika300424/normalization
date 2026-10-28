from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.7-flash")
MAX_CONCURRENT_REQUESTS = 5
MAX_RETRIES = 3

CSV_COLUMNS = [
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
