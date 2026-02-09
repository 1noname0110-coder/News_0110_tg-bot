"""
Модуль для получения актуальных курсов валют и криптовалют.
"""

import logging
from datetime import datetime
from typing import Dict, Optional

import aiohttp

logger = logging.getLogger(__name__)


class CurrencyFetcher:
    """Получает курсы валют и биткоина."""

    def __init__(self):
        self.fiat_url = "https://api.exchangerate.host/latest"
        self.crypto_url = "https://api.coingecko.com/api/v3/simple/price"

    async def _fetch_json(self, session: aiohttp.ClientSession, url: str, params: Dict) -> Optional[Dict]:
        try:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    logger.warning("Не удалось получить курсы (%s): HTTP %s", url, response.status)
                    return None
                return await response.json()
        except Exception as exc:
            logger.error("Ошибка запроса курсов (%s): %s", url, exc)
            return None

    async def fetch_rates(self) -> Dict:
        async with aiohttp.ClientSession() as session:
            fiat_data = await self._fetch_json(
                session,
                self.fiat_url,
                {"base": "RUB", "symbols": "USD,EUR,CNY"}
            )
            crypto_data = await self._fetch_json(
                session,
                self.crypto_url,
                {"ids": "bitcoin", "vs_currencies": "usd,rub"}
            )

        rates = {}
        if fiat_data and fiat_data.get("rates"):
            rates.update(fiat_data["rates"])

        btc_usd = None
        btc_rub = None
        if crypto_data:
            btc = crypto_data.get("bitcoin", {})
            btc_usd = btc.get("usd")
            btc_rub = btc.get("rub")

        return {
            "usd_per_rub": rates.get("USD"),
            "eur_per_rub": rates.get("EUR"),
            "cny_per_rub": rates.get("CNY"),
            "btc_usd": btc_usd,
            "btc_rub": btc_rub,
            "timestamp": datetime.utcnow()
        }
