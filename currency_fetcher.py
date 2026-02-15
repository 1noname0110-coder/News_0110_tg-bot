"""Модуль для получения актуальных курсов валют и криптовалют с fallback-источниками."""

import logging
from datetime import datetime
from typing import Dict, Optional

import aiohttp

logger = logging.getLogger(__name__)


class CurrencyFetcher:
    """Получает курсы USD/EUR/CNY, индекс рубля и BTC."""

    def __init__(self):
        self.timeout = aiohttp.ClientTimeout(total=10)

    async def _fetch_json(self, session: aiohttp.ClientSession, url: str, params: Optional[Dict] = None) -> Optional[Dict]:
        try:
            async with session.get(url, params=params, timeout=self.timeout) as response:
                if response.status != 200:
                    logger.warning("Не удалось получить данные (%s): HTTP %s", url, response.status)
                    return None
                return await response.json()
        except Exception as exc:
            logger.warning("Ошибка API (%s): %s", url, exc)
            return None

    async def _fetch_cbr_rates(self, session: aiohttp.ClientSession) -> Dict[str, Optional[float]]:
        data = await self._fetch_json(session, "https://www.cbr-xml-daily.ru/daily_json.js")
        if not data:
            return {}

        valute = data.get("Valute", {})

        def rub_per_unit(code: str) -> Optional[float]:
            item = valute.get(code)
            if not item:
                return None
            value = item.get("Value")
            nominal = item.get("Nominal") or 1
            if not value:
                return None
            return float(value) / float(nominal)

        return {
            "usd_rub": rub_per_unit("USD"),
            "eur_rub": rub_per_unit("EUR"),
            "cny_rub": rub_per_unit("CNY"),
            "source_fiat": "CBR",
        }

    async def _fetch_fiat_fallback(self, session: aiohttp.ClientSession) -> Dict[str, Optional[float]]:
        data = await self._fetch_json(
            session,
            "https://api.exchangerate.host/latest",
            {"base": "USD", "symbols": "RUB,EUR,CNY"}
        )
        if not data or not data.get("rates"):
            return {}

        rates = data["rates"]
        usd_rub = rates.get("RUB")
        if not usd_rub:
            return {}

        # Из базы USD получаем RUB для USD/EUR/CNY
        eur_rub = usd_rub / rates.get("EUR") if rates.get("EUR") else None
        cny_rub = usd_rub / rates.get("CNY") if rates.get("CNY") else None
        return {
            "usd_rub": float(usd_rub),
            "eur_rub": float(eur_rub) if eur_rub else None,
            "cny_rub": float(cny_rub) if cny_rub else None,
            "source_fiat": "ExchangeRate.host",
        }

    async def _fetch_btc_coingecko(self, session: aiohttp.ClientSession) -> Dict[str, Optional[float]]:
        data = await self._fetch_json(
            session,
            "https://api.coingecko.com/api/v3/simple/price",
            {"ids": "bitcoin", "vs_currencies": "usd,rub"}
        )
        btc = (data or {}).get("bitcoin", {})
        return {
            "btc_usd": btc.get("usd"),
            "btc_rub": btc.get("rub"),
            "source_btc": "CoinGecko" if btc else None,
        }

    async def _fetch_btc_binance(self, session: aiohttp.ClientSession) -> Dict[str, Optional[float]]:
        usd = await self._fetch_json(session, "https://api.binance.com/api/v3/ticker/price", {"symbol": "BTCUSDT"})
        rub = await self._fetch_json(session, "https://api.binance.com/api/v3/ticker/price", {"symbol": "BTCRUB"})
        btc_usd = float(usd["price"]) if usd and usd.get("price") else None
        btc_rub = float(rub["price"]) if rub and rub.get("price") else None
        return {
            "btc_usd": btc_usd,
            "btc_rub": btc_rub,
            "source_btc": "Binance" if (btc_usd or btc_rub) else None,
        }

    async def fetch_rates(self) -> Optional[Dict]:
        async with aiohttp.ClientSession() as session:
            fiat = await self._fetch_cbr_rates(session)
            if not fiat.get("usd_rub"):
                fiat = await self._fetch_fiat_fallback(session)

            btc = await self._fetch_btc_coingecko(session)
            if not btc.get("btc_usd") or not btc.get("btc_rub"):
                fallback_btc = await self._fetch_btc_binance(session)
                btc = {
                    "btc_usd": btc.get("btc_usd") or fallback_btc.get("btc_usd"),
                    "btc_rub": btc.get("btc_rub") or fallback_btc.get("btc_rub"),
                    "source_btc": btc.get("source_btc") or fallback_btc.get("source_btc"),
                }

        usd_rub = fiat.get("usd_rub")
        eur_rub = fiat.get("eur_rub")
        cny_rub = fiat.get("cny_rub")
        btc_usd = btc.get("btc_usd")
        btc_rub = btc.get("btc_rub")

        if not (usd_rub and eur_rub and cny_rub and btc_usd and btc_rub):
            logger.error("Не удалось получить полный набор курсов")
            return None

        rub_usd = 1 / usd_rub if usd_rub else None

        return {
            "usd_rub": float(usd_rub),
            "eur_rub": float(eur_rub),
            "cny_rub": float(cny_rub),
            "rub_usd": float(rub_usd) if rub_usd else None,
            "btc_usd": float(btc_usd),
            "btc_rub": float(btc_rub),
            "fiat_source": fiat.get("source_fiat", "Unknown"),
            "btc_source": btc.get("source_btc", "Unknown"),
            "timestamp": datetime.utcnow(),
        }
