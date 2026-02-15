"""Модуль получения курсов валют и BTC с fallback-источниками."""

import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, Optional

import aiohttp

logger = logging.getLogger(__name__)


class CurrencyFetcher:
    """Получает USD/EUR/CNY к RUB и BTC к USD/RUB."""

    def __init__(self):
        self.cbr_url = "https://www.cbr.ru/scripts/XML_daily.asp"
        self.exchangerate_url = "https://api.exchangerate.host/latest"
        self.coingecko_url = "https://api.coingecko.com/api/v3/simple/price"
        self.binance_url = "https://api.binance.com/api/v3/ticker/price"

    async def _fetch_json(self, session: aiohttp.ClientSession, url: str, params: Optional[Dict] = None) -> Optional[Dict]:
        try:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    logger.warning("HTTP %s от %s", response.status, url)
                    return None
                return await response.json()
        except Exception as exc:
            logger.warning("Ошибка JSON-запроса %s: %s", url, exc)
            return None

    async def _fetch_text(self, session: aiohttp.ClientSession, url: str) -> Optional[str]:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    logger.warning("HTTP %s от %s", response.status, url)
                    return None
                return await response.text()
        except Exception as exc:
            logger.warning("Ошибка текстового запроса %s: %s", url, exc)
            return None

    def _extract_cbr_rates(self, xml_text: str) -> Dict[str, float]:
        root = ET.fromstring(xml_text)
        result: Dict[str, float] = {}
        for valute in root.findall('Valute'):
            char_code = (valute.findtext('CharCode') or '').strip()
            nominal_text = (valute.findtext('Nominal') or '1').replace(',', '.').strip()
            value_text = (valute.findtext('Value') or '').replace(',', '.').strip()
            if not char_code or not value_text:
                continue
            try:
                nominal = float(nominal_text)
                value = float(value_text)
                if nominal <= 0:
                    continue
                result[char_code] = value / nominal
            except ValueError:
                continue
        return result

    async def _fetch_fiat_rates(self, session: aiohttp.ClientSession) -> Dict[str, float]:
        # Источник 1: ЦБ РФ
        xml_text = await self._fetch_text(session, self.cbr_url)
        if xml_text:
            try:
                rates = self._extract_cbr_rates(xml_text)
                if all(k in rates for k in ('USD', 'EUR', 'CNY')):
                    return {
                        'usd_rub': rates['USD'],
                        'eur_rub': rates['EUR'],
                        'cny_rub': rates['CNY'],
                    }
            except Exception as exc:
                logger.warning("Не удалось распарсить XML ЦБ: %s", exc)

        # Источник 2: exchangerate.host
        alt = await self._fetch_json(
            session,
            self.exchangerate_url,
            {'base': 'RUB', 'symbols': 'USD,EUR,CNY'}
        )
        if alt and alt.get('rates'):
            rates = alt['rates']
            try:
                usd_per_rub = float(rates['USD'])
                eur_per_rub = float(rates['EUR'])
                cny_per_rub = float(rates['CNY'])
                if min(usd_per_rub, eur_per_rub, cny_per_rub) > 0:
                    return {
                        'usd_rub': 1 / usd_per_rub,
                        'eur_rub': 1 / eur_per_rub,
                        'cny_rub': 1 / cny_per_rub,
                    }
            except Exception:
                pass

        return {}

    async def _fetch_btc_rates(self, session: aiohttp.ClientSession) -> Dict[str, float]:
        # Источник 1: CoinGecko
        cg = await self._fetch_json(
            session,
            self.coingecko_url,
            {'ids': 'bitcoin', 'vs_currencies': 'usd,rub'}
        )
        if cg and cg.get('bitcoin'):
            btc = cg['bitcoin']
            btc_usd = btc.get('usd')
            btc_rub = btc.get('rub')
            if isinstance(btc_usd, (int, float)) and isinstance(btc_rub, (int, float)):
                return {'btc_usd': float(btc_usd), 'btc_rub': float(btc_rub)}

        # Источник 2: Binance (BTCUSDT) + USD/RUB из fiat
        binance = await self._fetch_json(session, self.binance_url, {'symbol': 'BTCUSDT'})
        if binance and binance.get('price'):
            try:
                btc_usd = float(binance['price'])
                if btc_usd > 0:
                    return {'btc_usd': btc_usd}
            except ValueError:
                pass

        return {}

    async def fetch_rates(self) -> Optional[Dict]:
        """Возвращает актуальные курсы или None, если данные неполные."""
        async with aiohttp.ClientSession() as session:
            fiat = await self._fetch_fiat_rates(session)
            btc = await self._fetch_btc_rates(session)

        if not fiat:
            logger.warning("Курсы фиата не получены")
            return None

        rates: Dict[str, float] = {**fiat, **btc}

        # Заполняем BTC/RUB через BTC/USD и USD/RUB, если прямое значение не пришло
        if 'btc_rub' not in rates and 'btc_usd' in rates:
            rates['btc_rub'] = rates['btc_usd'] * rates['usd_rub']

        required = ('usd_rub', 'eur_rub', 'cny_rub', 'btc_usd', 'btc_rub')
        if not all(k in rates and rates[k] > 0 for k in required):
            logger.warning("Неполные курсы: %s", rates)
            return None

        rates['rub_usd'] = 1 / rates['usd_rub']
        rates['timestamp'] = datetime.utcnow()
        return rates
