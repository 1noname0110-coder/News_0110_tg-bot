"""Telegram-бот ежедневного новостного дайджеста (РФ + Мир)."""

import argparse
import asyncio
import logging
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from telegram import Bot
from telegram.constants import ParseMode

import config
from database import NewsDatabase
from news_collector import NewsCollector
from post_generator import PostGenerator
from currency_fetcher import CurrencyFetcher

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


@dataclass
class DigestSchedule:
    name: str
    hour: int
    minute: int


class NewsBot:
    """Бот, публикующий структурированные дневные дайджесты."""

    def __init__(self):
        self.bot = Bot(token=config.BOT_TOKEN)
        self.channel_id = config.CHANNEL_ID
        self.database = NewsDatabase(config.DATABASE_PATH)
        self.news_collector = NewsCollector(config.NEWS_SOURCES)
        self.post_generator = PostGenerator(config.MAX_POST_LENGTH)
        self.currency_fetcher = CurrencyFetcher()

        self.msk_tz = timezone(timedelta(hours=3))
        self.last_update_id: Optional[int] = None

        # Метки публикаций в рамках дня
        self.last_morning_digest_at: Optional[datetime] = None
        self.last_evening_digest_at: Optional[datetime] = None
        self.last_morning_digest_urls: Set[str] = set()
        self.last_important_snapshot_at: Optional[datetime] = None
        self.last_currency_post_at: Optional[datetime] = None
        self.last_currency_evening_post_at: Optional[datetime] = None

        self.schedule = [
            DigestSchedule('morning', config.DIGEST_PUBLISH_HOUR_MSK, config.DIGEST_PUBLISH_MINUTE_MSK),
            DigestSchedule('supplement', config.SUPPLEMENT_PUBLISH_HOUR_MSK, config.SUPPLEMENT_PUBLISH_MINUTE_MSK),
            DigestSchedule('evening', config.EVENING_PUBLISH_HOUR_MSK, config.EVENING_PUBLISH_MINUTE_MSK),
        ]

    async def _send_message(self, text: str) -> None:
        try:
            await self.bot.send_message(
                chat_id=self.channel_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
        except Exception:
            # Fallback без markdown
            await self.bot.send_message(
                chat_id=self.channel_id,
                text=text.replace('*', ''),
                disable_web_page_preview=True,
            )

    def _news_text(self, news: Dict) -> str:
        return f"{news.get('title', '')} {news.get('description', '')}".lower()

    def _keyword_score(self, text: str, keywords: List[str]) -> int:
        return sum(1 for word in keywords if word in text)

    def _source_weight(self, news: Dict) -> float:
        source = news.get('source', '')
        return config.SOURCE_RELIABILITY_WEIGHTS.get(source, 1.0)

    def _freshness_score(self, news: Dict, now: datetime) -> float:
        published_at = news.get('published_at', now)
        if not isinstance(published_at, datetime):
            return 1.0
        age_h = max((now - published_at).total_seconds() / 3600, 0)
        half_life = max(config.PRIORITY_RECENCY_HALF_LIFE_HOURS, 1)
        return math.exp(-age_h / half_life)

    def classify_bucket(self, news: Dict) -> Optional[str]:
        """Жёсткая рубрикация по ТЗ."""
        text = self._news_text(news)

        russia_score = self._keyword_score(text, config.RUSSIA_KEYWORDS)
        world_score = self._keyword_score(text, config.WORLD_KEYWORDS)
        economy_score = self._keyword_score(text, config.ECONOMY_KEYWORDS)
        politics_score = self._keyword_score(text, config.POLITICS_KEYWORDS)
        conflict_score = self._keyword_score(text, config.ARMED_CONFLICT_KEYWORDS)
        society_score = self._keyword_score(text, config.SOCIETY_KEYWORDS)

        region = 'russia' if russia_score >= world_score else 'world'

        if region == 'russia':
            if conflict_score > 0:
                return 'РОССИЯ|Безопасность'
            if economy_score > 0 and economy_score >= politics_score:
                return 'РОССИЯ|Экономика'
            if politics_score > 0:
                return 'РОССИЯ|Политика'
            if society_score > 0:
                return 'РОССИЯ|Безопасность'
            return None

        if conflict_score > 0 or politics_score > 0:
            return 'МИР|Геополитика'
        if economy_score > 0:
            return 'МИР|Экономика'
        if society_score > 0:
            return 'МИР|Жизнь за рубежом'
        return None

    def importance_score(self, news: Dict, now: datetime) -> float:
        text = self._news_text(news)
        high = self._keyword_score(text, config.HIGH_IMPORTANCE_KEYWORDS)
        medium = self._keyword_score(text, config.MEDIUM_IMPORTANCE_KEYWORDS)
        signal = high * 2.2 + medium * 0.8
        topic_bonus = 1.4 if self.classify_bucket(news) in {'РОССИЯ|Политика', 'РОССИЯ|Экономика', 'МИР|Геополитика'} else 1.0
        return (1 + signal + topic_bonus) * self._source_weight(news) * (0.7 + self._freshness_score(news, now))

    def is_noise(self, news: Dict) -> bool:
        text = self._news_text(news)
        if any(marker in text for marker in config.LOW_VALUE_NEWS_PATTERNS):
            return True
        if len((news.get('title') or '').strip()) < 12:
            return True
        if not (news.get('description') or '').strip():
            return True
        if any(k in text for k in config.LOCAL_NOISE_CRIME_KEYWORDS) and any(k in text for k in config.LOCAL_NEWS_MARKERS):
            return True
        if any(k in text for k in config.CRIME_CONTENT_KEYWORDS) and not any(k in text for k in config.ALLOWED_GLOBAL_CRIME_KEYWORDS):
            return True
        return False

    def deduplicate(self, items: List[Dict]) -> List[Dict]:
        seen_urls: Set[str] = set()
        seen_titles: Set[str] = set()
        seen_content: Set[str] = set()
        result = []
        for item in items:
            nurl = self.database.normalize_url(item.get('url', ''))
            ntitle = self.database.normalize_title(item.get('title', ''))
            chash = self.database.generate_content_hash(item.get('title', ''), item.get('description', ''))
            if nurl and nurl in seen_urls:
                continue
            if ntitle and ntitle in seen_titles:
                continue
            if chash and chash in seen_content:
                continue
            if nurl:
                seen_urls.add(nurl)
            if ntitle:
                seen_titles.add(ntitle)
            if chash:
                seen_content.add(chash)
            result.append(item)
        return result

    async def collect_important_news(self, since: datetime, until: datetime) -> List[Dict]:
        all_news = await self.news_collector.collect_all_news()
        filtered = []
        for news in all_news:
            published_at = news.get('published_at', until)
            if not isinstance(published_at, datetime):
                continue
            if not (since <= published_at <= until):
                continue
            if self.database.is_news_published(news['title'], news['url'], news['source'], news.get('description', '')):
                continue
            if self.is_noise(news):
                continue
            bucket = self.classify_bucket(news)
            if not bucket:
                continue
            news['bucket'] = bucket
            score = self.importance_score(news, until)
            news['importance_score'] = score
            if score < 2.8:
                continue
            filtered.append(news)

        unique = self.deduplicate(filtered)
        unique.sort(key=lambda x: (x.get('importance_score', 0.0), x.get('published_at', since)), reverse=True)
        return unique

    def _group_for_digest(self, items: List[Dict]) -> Dict[str, List[Dict]]:
        grouped: Dict[str, List[Dict]] = defaultdict(list)
        for item in items:
            grouped[item['bucket']].append(item)
        return grouped

    async def publish_digest(self, title: str, items: List[Dict], mark_as_published: bool = True) -> bool:
        if not items:
            logger.info('Для "%s" нет важных новостей', title)
            return False

        grouped = self._group_for_digest(items)
        chunks = self.post_generator.format_structured_digest(title=title, grouped_news=grouped, generated_at=datetime.now(self.msk_tz))

        for chunk in chunks:
            await self._send_message(chunk)

        if mark_as_published:
            now_msk = datetime.now(self.msk_tz)
            for item in items:
                self.database.save_news(
                    title=item['title'],
                    url=item['url'],
                    source=item.get('source', 'Unknown'),
                    category=item.get('bucket', 'digest'),
                    published_at=item.get('published_at', now_msk),
                    description=item.get('description', ''),
                )

        return True

    def _today_start_msk(self, now_msk: datetime) -> datetime:
        return now_msk.replace(hour=0, minute=0, second=0, microsecond=0)

    def _schedule_dt(self, now_msk: datetime, item: DigestSchedule) -> datetime:
        return now_msk.replace(hour=item.hour, minute=item.minute, second=0, microsecond=0)

    async def run_morning_digest(self, now_msk: datetime) -> None:
        since = self._today_start_msk(now_msk)
        items = await self.collect_important_news(since, now_msk)
        sent = await self.publish_digest('Главное за день (утро)', items)
        if sent:
            self.last_morning_digest_at = now_msk
            self.last_morning_digest_urls = {self.database.normalize_url(i['url']) for i in items}
            self.last_important_snapshot_at = now_msk

    async def run_supplement_digest(self, now_msk: datetime) -> None:
        if not self.last_morning_digest_at:
            return
        since = self.last_morning_digest_at
        items = await self.collect_important_news(since, now_msk)
        truly_new = [
            i for i in items
            if self.database.normalize_url(i['url']) not in self.last_morning_digest_urls
        ]
        if not truly_new:
            logger.info('Дополнение в 12:20 не требуется: новых важных новостей нет')
            return
        await self.publish_digest('Дополнение к дневному дайджесту', truly_new)

    async def publish_currency_post(self, now_msk: datetime, post_type: str, force: bool = False) -> bool:
        rates = await self.currency_fetcher.fetch_rates()
        if not rates:
            logger.warning('Курсы не получены, сервисный пост пропущен')
            return False

        today = now_msk.strftime('%Y-%m-%d')
        if not force and self.database.has_currency_post_for_day(today, post_type):
            logger.info('Пост курсов (%s) уже опубликован сегодня', post_type)
            return False

        if post_type == 'evening_update' and not force:
            latest = self.database.get_latest_currency_snapshot()
            if not latest:
                logger.info('Нет базового дневного снимка курсов для сравнения')
                return False
            max_change = self._max_currency_change_pct(latest, rates)
            if max_change < config.CURRENCY_SIGNIFICANT_CHANGE_PCT:
                logger.info('Вечернее обновление не требуется: max изменение %.2f%%', max_change)
                return False

        text = self.post_generator.format_currency_post(rates, now_msk)
        await self._send_message(text)

        saved = self.database.save_currency_snapshot(rates, post_type=post_type, published_at=now_msk)
        if not saved and not force:
            logger.info('Курсы не опубликованы: дубликат снимка')
            return False

        if post_type == 'daily':
            self.last_currency_post_at = now_msk
        elif post_type == 'evening_update':
            self.last_currency_evening_post_at = now_msk

        return True

    def _max_currency_change_pct(self, previous: Dict, current: Dict) -> float:
        keys = ('usd_rub', 'eur_rub', 'cny_rub', 'btc_usd', 'btc_rub')
        changes: List[float] = []
        for key in keys:
            prev = float(previous.get(key, 0) or 0)
            cur = float(current.get(key, 0) or 0)
            if prev <= 0 or cur <= 0:
                continue
            changes.append(abs(cur - prev) / prev * 100)
        return max(changes) if changes else 0.0

    async def run_evening_digest(self, now_msk: datetime) -> None:
        since = self._today_start_msk(now_msk)
        items = await self.collect_important_news(since, now_msk)
        sent = await self.publish_digest('Главное за день (полный вечерний итог)', items)
        if sent:
            self.last_evening_digest_at = now_msk

    async def run_continuously(self) -> None:
        logger.info('Запуск: дайджесты 12:00/12:20/19:00 + курсы 12:05 (опц. 18:00) МСК.')
        while True:
            try:
                now_msk = datetime.now(self.msk_tz)

                morning_time = self._schedule_dt(now_msk, self.schedule[0])
                supplement_time = self._schedule_dt(now_msk, self.schedule[1])
                evening_time = self._schedule_dt(now_msk, self.schedule[2])
                currency_time = now_msk.replace(hour=config.CURRENCY_POST_HOUR_MSK, minute=config.CURRENCY_POST_MINUTE_MSK, second=0, microsecond=0)
                currency_evening_time = now_msk.replace(hour=config.CURRENCY_EVENING_HOUR_MSK, minute=config.CURRENCY_EVENING_MINUTE_MSK, second=0, microsecond=0)

                if now_msk >= morning_time and (not self.last_morning_digest_at or self.last_morning_digest_at.date() != now_msk.date()):
                    await self.run_morning_digest(now_msk)

                if now_msk >= supplement_time and self.last_morning_digest_at and self.last_morning_digest_at.date() == now_msk.date():
                    supplement_already_sent = self.last_important_snapshot_at and self.last_important_snapshot_at.date() == now_msk.date() and self.last_important_snapshot_at >= supplement_time
                    if not supplement_already_sent:
                        await self.run_supplement_digest(now_msk)
                        self.last_important_snapshot_at = now_msk

                if now_msk >= currency_time and (not self.last_currency_post_at or self.last_currency_post_at.date() != now_msk.date()):
                    await self.publish_currency_post(now_msk, post_type='daily')

                if config.CURRENCY_ENABLE_EVENING_UPDATE and now_msk >= currency_evening_time and (not self.last_currency_evening_post_at or self.last_currency_evening_post_at.date() != now_msk.date()):
                    await self.publish_currency_post(now_msk, post_type='evening_update')

                if now_msk >= evening_time and (not self.last_evening_digest_at or self.last_evening_digest_at.date() != now_msk.date()):
                    await self.run_evening_digest(now_msk)

                await asyncio.sleep(max(30, config.CHECK_INTERVAL_SECONDS))
            except KeyboardInterrupt:
                logger.info('Остановка по Ctrl+C')
                break
            except Exception as exc:
                logger.error('Ошибка в основном цикле: %s', exc, exc_info=True)
                await asyncio.sleep(60)


def main() -> None:
    parser = argparse.ArgumentParser(description='Telegram-бот дневных дайджестов и сервисных курсов валют')
    parser.add_argument('--currency-now', action='store_true', help='опубликовать пост с курсами валют немедленно')
    args = parser.parse_args()

    if not config.BOT_TOKEN:
        logger.error('BOT_TOKEN не установлен')
        return
    if not config.CHANNEL_ID:
        logger.error('CHANNEL_ID не установлен')
        return

    bot = NewsBot()

    if args.currency_now:
        asyncio.run(bot.publish_currency_post(datetime.now(bot.msk_tz), post_type='manual', force=True))
        return

    asyncio.run(bot.run_continuously())


if __name__ == '__main__':
    main()
