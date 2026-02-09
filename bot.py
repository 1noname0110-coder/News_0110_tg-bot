"""
Основной файл телеграм-бота для публикации новостей в канал.
Бот публикует ежедневные сводки и курсы валют по расписанию.
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict

from telegram import Bot, InputMediaPhoto
from telegram.constants import ParseMode

import config
from currency_fetcher import CurrencyFetcher
from database import NewsDatabase
from news_collector import NewsCollector
from post_generator import PostGenerator

# Настройка логирования для отслеживания работы бота
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


class NewsBot:
    """Главный класс бота для публикации новостей в канал."""

    def __init__(self):
        self.bot = Bot(token=config.BOT_TOKEN)
        self.channel_id = config.CHANNEL_ID
        self.database = NewsDatabase(config.DATABASE_PATH)
        self.news_collector = NewsCollector(config.NEWS_SOURCES)
        self.post_generator = PostGenerator(config.MAX_POST_LENGTH)
        self.pending_news: Dict[str, Dict] = {}
        self.msk_tz = timezone(timedelta(hours=3))

        logger.info("Бот инициализирован")

    async def _send_message(self, text: str) -> bool:
        try:
            await self.bot.send_message(
                chat_id=self.channel_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=False
            )
            return True
        except Exception as markdown_error:
            logger.warning("Ошибка Markdown форматирования, публикуем без разметки: %s", markdown_error)
            plain_text = text.replace('*', '').replace('[', '').replace(']', '').replace('(', '').replace(')', '')
            await self.bot.send_message(
                chat_id=self.channel_id,
                text=plain_text,
                disable_web_page_preview=False
            )
            return True

    async def publish_news(self, news: dict, related_news: Optional[dict] = None) -> bool:
        """Публикует новость в канал Telegram."""
        try:
            post_text = self.post_generator.format_post(news, related_news)
            categories = news.get('categories') or [news.get('category', 'general')]
            post_text = self.post_generator.add_category_tag(post_text, categories)
            await self._send_message(post_text)

            logger.info(f"Опубликована новость: {news['title'][:80]}...")
            return True
        except Exception as e:
            logger.error(f"Ошибка при публикации новости '{news['title']}': {str(e)}")
            return False

    def _title_tokens(self, text: str) -> set:
        words = re.findall(r"[а-яa-zё0-9]{4,}", text.lower())
        stop_words = {
            'когда', 'после', 'будет', 'стало', 'этого', 'также', 'которые', 'россии',
            'чтобы', 'через', 'между', 'about', 'with', 'that', 'this', 'from'
        }
        return {word for word in words if word not in stop_words}

    def is_unwanted_local_news(self, news: Dict) -> bool:
        text = f"{news.get('title', '')} {news.get('description', '')}".lower()
        has_crime = any(keyword in text for keyword in config.LOCAL_NOISE_CRIME_KEYWORDS)
        has_local_marker = any(marker in text for marker in config.LOCAL_NEWS_MARKERS)
        return has_crime and has_local_marker

    def is_political_news(self, news: Dict) -> bool:
        text = f"{news.get('title', '')} {news.get('description', '')}".lower()
        return any(keyword in text for keyword in config.WORLD_KEYWORDS)

    def _detect_region(self, news: Dict) -> str:
        text = f"{news.get('title', '')} {news.get('description', '')}".lower()
        if any(keyword in text for keyword in config.RUSSIA_KEYWORDS):
            return 'рф'
        if any(keyword in text for keyword in config.WORLD_KEYWORDS):
            return 'мир'
        return 'мир'

    def _detect_topic(self, news: Dict) -> str:
        text = f"{news.get('title', '')} {news.get('description', '')}".lower()
        if any(keyword in text for keyword in config.ECONOMY_KEYWORDS):
            return 'экономика'
        return 'политика'

    def _detect_categories(self, news: Dict) -> List[str]:
        text = f"{news.get('title', '')} {news.get('description', '')}".lower()
        categories: List[str] = []

        if any(keyword in text for keyword in config.WORLD_KEYWORDS):
            categories.append('мир')
        if any(keyword in text for keyword in config.RUSSIA_KEYWORDS):
            categories.append('россия')
        if any(keyword in text for keyword in config.ECONOMY_KEYWORDS):
            categories.append('экономика')

        source_category = news.get('category')
        if source_category and source_category not in categories:
            categories.append(source_category)

        return categories

    def is_excluded_russian_topic(self, news: Dict) -> bool:
        if news.get('source') not in config.EXCLUDED_RUSSIAN_SOURCES:
            return False
        text = f"{news.get('title', '')} {news.get('description', '')}".lower()
        return any(keyword in text for keyword in config.EXCLUDED_RUSSIAN_TOPICS_KEYWORDS)

    def is_blocked_crime_news(self, news: Dict) -> bool:
        """Блокирует криминальный контент, кроме глобально значимого и терактов."""
        text = f"{news.get('title', '')} {news.get('description', '')}".lower()

        has_crime = any(keyword in text for keyword in config.CRIME_CONTENT_KEYWORDS)
        if not has_crime:
            return False

        is_allowed_global = any(keyword in text for keyword in config.ALLOWED_GLOBAL_CRIME_KEYWORDS)
        return not is_allowed_global

    def is_low_value_news(self, news: Dict) -> bool:
        """Фильтрует пустые/кликбейтные новости-затычки."""
        title = (news.get('title') or '').strip().lower()
        description = (news.get('description') or '').strip().lower()
        text = f"{title} {description}".strip()

        if not title or len(title) < 12:
            return True

        # Пустое или слишком короткое описание, особенно если повторяет заголовок
        normalized_title = re.sub(r'\s+', ' ', title)
        normalized_description = re.sub(r'\s+', ' ', description)
        if not normalized_description:
            return True

        if len(normalized_description) < config.MIN_DESCRIPTION_LENGTH:
            return True

        if normalized_description == normalized_title:
            return True

        if normalized_description.startswith(normalized_title):
            tail = normalized_description[len(normalized_title):].strip(' .:-—')
            if len(tail) < 30:
                return True

        # Слишком высокая текстовая похожесть заголовка и описания
        title_tokens = self._title_tokens(normalized_title)
        description_tokens = self._title_tokens(normalized_description)
        if title_tokens and description_tokens:
            overlap = len(title_tokens & description_tokens) / max(len(title_tokens), 1)
            if overlap >= 0.9 and len(description_tokens) <= len(title_tokens) + 2:
                return True

        if any(pattern in text for pattern in config.LOW_VALUE_NEWS_PATTERNS):
            # Если описание при этом очень короткое — почти точно затычка
            if len(normalized_description) < 220:
                return True

        return False

    def group_news_by_url(self, news_list: List[Dict]) -> Dict[str, Dict]:
        grouped = {}
        now = datetime.now()

        for news in news_list:
            categories = news.get('categories') or [news.get('category', 'general')]
            normalized_url = self.database.normalize_url(news['url'])
            if normalized_url not in grouped:
                grouped[normalized_url] = {
                    'title': news['title'],
                    'url': news['url'],
                    'description': news.get('description', ''),
                    'source': news['source'],
                    'categories': list(dict.fromkeys(categories)),
                    'sources': [news['source']],
                    'images': news.get('images', []),
                    'published_at': news['published_at'],
                    'first_seen_at': now,
                    'combined_items': [news]
                }
            else:
                for category in categories:
                    if category not in grouped[normalized_url]['categories']:
                        grouped[normalized_url]['categories'].append(category)
                if news['source'] not in grouped[normalized_url]['sources']:
                    grouped[normalized_url]['sources'].append(news['source'])
                for image_url in news.get('images', []):
                    if image_url not in grouped[normalized_url]['images']:
                        grouped[normalized_url]['images'].append(image_url)
                if news.get('description') and len(news['description']) > len(grouped[normalized_url]['description']):
                    grouped[normalized_url]['description'] = news['description']
                if news['published_at'] > grouped[normalized_url]['published_at']:
                    grouped[normalized_url]['published_at'] = news['published_at']
                grouped[normalized_url]['combined_items'].append(news)

        return grouped

    def _merge_into_existing(self, target: Dict, incoming: Dict) -> None:
        """Объединяет данные новости в существующую запись."""
        for category in incoming.get('categories', []):
            if category not in target['categories']:
                target['categories'].append(category)
        for source in incoming.get('sources', []):
            if source not in target['sources']:
                target['sources'].append(source)
        for image_url in incoming.get('images', []):
            if image_url not in target['images']:
                target['images'].append(image_url)
        if len(incoming.get('description', '')) > len(target.get('description', '')):
            target['description'] = incoming['description']
        target['combined_items'].extend(incoming.get('combined_items', []))

    def add_to_pending(self, grouped_news: Dict[str, Dict]):
        for normalized_url, news in grouped_news.items():
            existing = self.pending_news.get(normalized_url)
            if not existing:
                similar_target = None
                for pending in self.pending_news.values():
                    if self._similarity(news, pending) >= 0.5:
                        similar_target = pending
                        break

                if similar_target:
                    self._merge_into_existing(similar_target, news)
                    continue

                self.pending_news[normalized_url] = news
                continue

            self._merge_into_existing(existing, news)

    def _is_ready_for_publish(self, news: Dict, now: datetime) -> bool:
        first_seen = news.get('first_seen_at', now)
        return now - first_seen >= timedelta(minutes=config.PUBLISH_DELAY_MINUTES)

    def _similarity(self, left: Dict, right: Dict) -> float:
        left_tokens = self._title_tokens(left.get('title', ''))
        right_tokens = self._title_tokens(right.get('title', ''))
        if not left_tokens or not right_tokens:
            return 0.0
        intersection = len(left_tokens & right_tokens)
        return intersection / max(len(left_tokens), len(right_tokens))

    def merge_similar_news(self, matured_news: List[Dict]) -> List[Dict]:
        clusters: List[List[Dict]] = []

        for item in matured_news:
            placed = False
            for cluster in clusters:
                if any(self._similarity(item, existing) >= 0.4 for existing in cluster):
                    cluster.append(item)
                    placed = True
                    break
            if not placed:
                clusters.append([item])

        merged: List[Dict] = []
        for cluster in clusters:
            if len(cluster) == 1:
                cluster[0]['combined_items'] = cluster[0].get('combined_items', [cluster[0]])
                merged.append(cluster[0])
                continue

            all_categories = []
            all_sources = []
            all_images = []
            all_urls = []
            all_descriptions = []
            all_combined_items = []

            for news in cluster:
                all_categories.extend(news.get('categories', []))
                all_sources.extend(news.get('sources', [news.get('source', 'Unknown')]))
                all_images.extend(news.get('images', []))
                all_urls.append(news['url'])
                if news.get('description'):
                    all_descriptions.append(news['description'])
                all_combined_items.extend(news.get('combined_items', [news]))

            unique_categories = list(dict.fromkeys(all_categories))
            unique_sources = list(dict.fromkeys(all_sources))
            unique_images = list(dict.fromkeys(all_images))
            unique_urls = list(dict.fromkeys(all_urls))

            merged_description_parts = []
            for description in sorted(all_descriptions, key=len, reverse=True):
                if description not in merged_description_parts:
                    merged_description_parts.append(description)
                if len(' '.join(merged_description_parts)) > 1800:
                    break

            merged.append({
                'title': cluster[0]['title'],
                'url': unique_urls[0],
                'alternate_urls': unique_urls[1:],
                'description': '\n\n'.join(merged_description_parts),
                'source': ', '.join(unique_sources),
                'sources': unique_sources,
                'categories': unique_categories,
                'published_at': max(news['published_at'] for news in cluster),
                'images': unique_images,
                'is_merged_topic': True,
                'topic_size': len(cluster),
                'combined_items': all_combined_items
            })

        return merged

    def _find_related_news(self, news: Dict) -> Optional[Dict]:
        for category in news.get('categories', []):
            recent_news = self.database.get_recent_news_by_category(category, hours=24, limit=3)
            if not recent_news:
                continue
            news_words = self._title_tokens(news['title'])
            for recent in recent_news:
                recent_words = self._title_tokens(recent['title'])
                if len(news_words & recent_words) >= 2:
                    return recent
        return None

    async def process_and_publish_news(self):
        try:
            logger.info("Начало сбора новостей...")
            all_news = await self.news_collector.collect_all_news()
            new_news = self.news_collector.filter_new_news(all_news, self.database)

            filtered_news = []
            dropped_local_noise = 0
            dropped_low_value = 0
            dropped_crime = 0
            dropped_non_political = 0
            skipped_duplicates = 0
            skipped_content_duplicates = 0
            seen_content_hashes = set()

            for news in new_news:
                if self.is_excluded_russian_topic(news):
                    dropped_non_political += 1
                    continue
                categories = self._detect_categories(news)
                if not categories:
                    dropped_non_political += 1
                    continue
                news['categories'] = categories
                news['category'] = categories[0]
                if self.is_unwanted_local_news(news):
                    dropped_local_noise += 1
                    continue
                if self.is_blocked_crime_news(news):
                    dropped_crime += 1
                    continue
                if self.is_low_value_news(news):
                    dropped_low_value += 1
                    continue
                normalized_title = self.database.normalize_title(news['title'])
                normalized_url = self.database.normalize_url(news['url'])
                if any(
                    normalized_title == self.database.normalize_title(item['title'])
                    or normalized_url == self.database.normalize_url(item['url'])
                    for item in filtered_news
                ):
                    skipped_duplicates += 1
                    continue
                content_hash = self.database.generate_content_hash(
                    news.get('title', ''),
                    news.get('description', '')
                )
                if content_hash and content_hash in seen_content_hashes:
                    skipped_content_duplicates += 1
                    continue
                if content_hash:
                    seen_content_hashes.add(content_hash)
                filtered_news.append(news)

            if dropped_non_political:
                logger.info(f"Отфильтровано нерелевантных новостей: {dropped_non_political}")
            if dropped_local_noise:
                logger.info(f"Отфильтровано локальных криминальных новостей: {dropped_local_noise}")
            if dropped_crime:
                logger.info(f"Отфильтровано криминального контента: {dropped_crime}")
            if dropped_low_value:
                logger.info(f"Отфильтровано новостей-затычек: {dropped_low_value}")
            if skipped_duplicates:
                logger.info(f"Пропущено дубликатов в пакете: {skipped_duplicates}")
            if skipped_content_duplicates:
                logger.info(f"Пропущено дубликатов по содержанию: {skipped_content_duplicates}")

            grouped_news = self.group_news_by_url(filtered_news)
            self.add_to_pending(grouped_news)

            now = datetime.now()
            matured_by_url = {
                key: news for key, news in self.pending_news.items() if self._is_ready_for_publish(news, now)
            }

            if not matured_by_url:
                logger.info("Нет новостей, готовых к публикации (ожидаем 30 минут для агрегации)")
                return

            matured_news = list(matured_by_url.values())
            matured_news.sort(key=lambda x: x['published_at'], reverse=True)
            publish_queue = self.merge_similar_news(matured_news)
            publish_queue.sort(key=lambda x: x['published_at'], reverse=True)

            published_count = 0
            published_urls = set()

            for news in publish_queue:
                related_news = self._find_related_news(news)
                success = await self.publish_news(news, related_news)
                if not success:
                    continue

                for item in news.get('combined_items', [news]):
                    item_categories = item.get('categories', [item.get('category', 'general')])
                    item_sources = item.get('sources', [item.get('source', 'Unknown')])
                    for category in item_categories:
                        self.database.save_news(
                            title=item['title'],
                            url=item['url'],
                            source=item_sources[0] if item_sources else 'Unknown',
                            category=category,
                            published_at=item.get('published_at', news['published_at']),
                            description=item.get('description', news.get('description', ''))
                        )
                    normalized_url = self.database.normalize_url(item['url'])
                    published_urls.add(normalized_url)

                published_count += 1
                await asyncio.sleep(5)

            for normalized_url in published_urls:
                self.pending_news.pop(normalized_url, None)

            logger.info(f"Опубликовано новостей: {published_count}")
        except Exception as e:
            logger.error(f"Ошибка при обработке новостей: {str(e)}", exc_info=True)

    def _to_msk(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=self.msk_tz)
        return value.astimezone(self.msk_tz)

    def _digest_bucket_label(self, topic: str, region: str) -> str:
        if topic == 'экономика' and region == 'рф':
            return 'Экономическая ситуация • РФ'
        if topic == 'экономика' and region == 'мир':
            return 'Экономическая ситуация • Мир'
        if topic == 'политика' and region == 'рф':
            return 'Политика • РФ'
        return 'Политика • Мир'

    def _digest_bucket_key(self, topic: str, region: str) -> str:
        return f"{topic}_{region}"

    def _filter_news_for_digest(self, news: Dict) -> bool:
        if self.is_excluded_russian_topic(news):
            return False
        categories = self._detect_categories(news)
        if not categories:
            return False
        news['categories'] = categories
        news['category'] = categories[0]
        if self.is_unwanted_local_news(news):
            return False
        if self.is_blocked_crime_news(news):
            return False
        if self.is_low_value_news(news):
            return False
        return True

    async def publish_daily_digest(self) -> None:
        try:
            logger.info("Сбор новостей для ежедневной сводки...")
            all_news = await self.news_collector.collect_all_news()
            new_news = self.news_collector.filter_new_news(all_news, self.database)

            now_msk = datetime.now(self.msk_tz)
            lookback_boundary = now_msk - timedelta(hours=config.DIGEST_LOOKBACK_HOURS)
            filtered_news = [
                news for news in new_news
                if self._filter_news_for_digest(news)
                and self._to_msk(news.get('published_at', now_msk)) >= lookback_boundary
            ]

            buckets: Dict[str, List[Dict]] = {
                self._digest_bucket_key('политика', 'мир'): [],
                self._digest_bucket_key('политика', 'рф'): [],
                self._digest_bucket_key('экономика', 'мир'): [],
                self._digest_bucket_key('экономика', 'рф'): []
            }

            for news in filtered_news:
                topic = self._detect_topic(news)
                region = self._detect_region(news)
                bucket_key = self._digest_bucket_key(topic, region)
                if bucket_key in buckets:
                    buckets[bucket_key].append(news)

            for bucket_key, items in buckets.items():
                items.sort(key=lambda x: x['published_at'], reverse=True)
                buckets[bucket_key] = items[:config.DIGEST_MAX_ITEMS]

            used_urls = set()
            used_hashes = set()
            for bucket_key, items in buckets.items():
                topic, region = bucket_key.split('_', maxsplit=1)
                heading = self._digest_bucket_label(topic, region)
                unique_items = []
                for item in items:
                    normalized_url = self.database.normalize_url(item.get('url', ''))
                    content_hash = self.database.generate_content_hash(
                        item.get('title', ''),
                        item.get('description', '')
                    )
                    if normalized_url and normalized_url in used_urls:
                        continue
                    if content_hash and content_hash in used_hashes:
                        continue
                    if normalized_url:
                        used_urls.add(normalized_url)
                    if content_hash:
                        used_hashes.add(content_hash)
                    unique_items.append(item)

                post_text = self.post_generator.format_digest_post(heading, unique_items, now_msk)
                await self._send_message(post_text)

                for item in unique_items:
                    self.database.save_news(
                        title=item['title'],
                        url=item['url'],
                        source=item['source'],
                        category=bucket_key,
                        published_at=item.get('published_at', now_msk),
                        description=item.get('description', '')
                    )
                await asyncio.sleep(5)
        except Exception as e:
            logger.error("Ошибка при публикации ежедневной сводки: %s", e, exc_info=True)

    def _seconds_until_next_digest(self) -> float:
        now = datetime.now(self.msk_tz)
        target = now.replace(
            hour=config.DIGEST_PUBLISH_HOUR_MSK,
            minute=config.DIGEST_PUBLISH_MINUTE_MSK,
            second=0,
            microsecond=0
        )
        if now >= target:
            target += timedelta(days=1)
        return (target - now).total_seconds()

    async def run_continuously(self):
        logger.info("Бот запущен. Публикация сводок по расписанию МСК.")

        while True:
            try:
                sleep_seconds = self._seconds_until_next_digest()
                logger.info("Ожидание до следующей сводки: %.0f секунд", sleep_seconds)
                await asyncio.sleep(sleep_seconds)
                await self.publish_daily_digest()
            except KeyboardInterrupt:
                logger.info("Получен сигнал остановки, завершение работы...")
                break
            except Exception as e:
                logger.error("Ошибка в основном цикле: %s", e, exc_info=True)
                await asyncio.sleep(60)


def main():
    if not config.BOT_TOKEN:
        logger.error("BOT_TOKEN не установлен! Установите его в файле .env")
        return

    if not config.CHANNEL_ID:
        logger.error("CHANNEL_ID не установлен! Установите его в файле .env")
        return

    news_bot = NewsBot()

    try:
        asyncio.run(news_bot.run_continuously())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")


if __name__ == "__main__":
    main()
