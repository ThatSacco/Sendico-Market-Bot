from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class FxRates:
    usd_to_aud: float
    jpy_to_aud: float
    source: str


class FxClient:
    def __init__(self, manual_usd_to_aud: float, manual_jpy_to_aud: float) -> None:
        self.manual_usd_to_aud = manual_usd_to_aud
        self.manual_jpy_to_aud = manual_jpy_to_aud

    def get_rates(self) -> FxRates:
        try:
            response = httpx.get(
                "https://api.frankfurter.dev/v1/latest",
                params={"from": "USD", "to": "AUD,JPY"},
                timeout=20.0,
                headers={"User-Agent": "sendico-pokemon-deal-bot/0.1"},
                follow_redirects=True,
            )
            response.raise_for_status()
            rates = response.json()["rates"]
            usd_to_aud = float(rates["AUD"])
            usd_to_jpy = float(rates["JPY"])
            return FxRates(
                usd_to_aud=usd_to_aud,
                jpy_to_aud=usd_to_aud / usd_to_jpy,
                source="Frankfurter/ECB",
            )
        except Exception as exc:  # noqa: BLE001 - a fallback is intentional
            LOGGER.warning("FX lookup failed; using configured fallback rates: %s", exc)
            return FxRates(
                usd_to_aud=self.manual_usd_to_aud,
                jpy_to_aud=self.manual_jpy_to_aud,
                source="configured fallback",
            )
