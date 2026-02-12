"""
Основной файл телеграм-бота для публикации новостей в канал.
Бот публикует ежедневные сводки и курсы валют по расписанию.
"""

import asyncio
import logging
import re
import math
from datetime import datetime, timedelta, timezone
from collections import deque, defaultdict
from typing import Optional, List, Dict

from telegram import Bot
from telegram.constants import ParseMode

import config
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
        self.breaking_publish_times = deque()
        self.pending_breaking_digest: List[Dict] = []
        self.last_collector_stats: Dict[str, Dict[str, int]] = {}

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

    def _news_text(self, news: Dict) -> str:
        return f"{news.get('title', '')} {news.get('description', '')}".lower()

    def _keyword_score(self, text: str, keywords: List[str]) -> int:
        return sum(1 for keyword in keywords if keyword in text)

    def _detect_region(self, news: Dict) -> str:
        text = self._news_text(news)
        russia_score = self._keyword_score(text, config.RUSSIA_KEYWORDS)
        world_score = self._keyword_score(text, config.WORLD_KEYWORDS)

        if russia_score > world_score:
            return 'рф'
        if world_score > 0:
            return 'мир'

        source_category = str(news.get('category', '')).lower()
        if source_category in {'россия', 'рф'}:
            return 'рф'
        return 'мир'

    def _is_armed_conflict_news(self, news: Dict) -> bool:
        text = self._news_text(news)
        conflict_score = self._keyword_score(text, config.ARMED_CONFLICT_KEYWORDS)
        if conflict_score == 0:
            return False
        has_noise = any(keyword in text for keyword in config.NON_CONFLICT_NOISE_KEYWORDS)
        return not has_noise

    def _is_economy_news(self, news: Dict) -> bool:
        text = self._news_text(news)
        economy_score = self._keyword_score(text, config.ECONOMY_KEYWORDS)
        if economy_score == 0:
            return False

        social_score = self._keyword_score(text, config.NON_ECONOMIC_SOCIAL_KEYWORDS)
        return economy_score > social_score

    def _is_society_news(self, news: Dict) -> bool:
        text = self._news_text(news)
        society_score = self._keyword_score(text, config.SOCIETY_KEYWORDS)
        politics_score = self._keyword_score(text, config.POLITICS_KEYWORDS)
        return society_score > 0 and society_score >= politics_score

    def _is_politics_news(self, news: Dict) -> bool:
        text = self._news_text(news)
        politics_score = self._keyword_score(text, config.POLITICS_KEYWORDS)
        return politics_score > 0

    def _detect_topic(self, news: Dict) -> str:
        if self._is_armed_conflict_news(news):
            return 'конфликт'
        if self._is_economy_news(news):
            return 'экономика'
        if self._is_society_news(news):
            return 'общество'
        if self._is_politics_news(news):
            return 'политика'
        return 'неопределено'

    def _detect_categories(self, news: Dict) -> List[str]:
        topic = self._detect_topic(news)
        if topic == 'неопределено':
            return []

        region = self._detect_region(news)

        if topic == 'конфликт':
            return ['вооружённые конфликты рф' if region == 'рф' else 'вооружённые конфликты мир']
        if topic == 'экономика':
            return ['экономика рф'] if region == 'рф' else []
        if topic == 'политика':
            return ['политика рф' if region == 'рф' else 'политика мир']
        if topic == 'общество':
            return ['общество рф'] if region == 'рф' else []

        return []


    def _source_weight(self, news: Dict) -> float:
        sources = news.get('sources') or [news.get('source', '')]
        weights = [config.SOURCE_RELIABILITY_WEIGHTS.get(src, 1.0) for src in sources if src]
        return max(weights) if weights else 1.0

    def _importance_keyword_score(self, news: Dict) -> float:
        text = self._news_text(news)
        high = self._keyword_score(text, config.HIGH_IMPORTANCE_KEYWORDS)
        medium = self._keyword_score(text, config.MEDIUM_IMPORTANCE_KEYWORDS)
        return high * 1.2 + medium * 0.5

    def _freshness_score(self, news: Dict, now: Optional[datetime] = None) -> float:
        now_value = now or datetime.now()
        published_at = news.get('published_at', now_value)
        if not isinstance(published_at, datetime):
            return 1.0
        age_hours = max((now_value - published_at).total_seconds() / 3600, 0)
        half_life = max(config.PRIORITY_RECENCY_HALF_LIFE_HOURS, 1)
        return math.exp(-age_hours / half_life)

    def _news_priority_score(self, news: Dict, now: Optional[datetime] = None) -> float:
        topic = self._detect_topic(news)
        topic_priority = config.TOPIC_BASE_PRIORITY.get(topic, 1.0)
        source_priority = self._source_weight(news)
        keyword_priority = self._importance_keyword_score(news)
        freshness_priority = self._freshness_score(news, now)

        return (topic_priority + keyword_priority) * source_priority * (0.7 + freshness_priority)

    def _priority_breakdown(self, news: Dict, now: Optional[datetime] = None) -> Dict[str, object]:
        topic = self._detect_topic(news)
        topic_priority = config.TOPIC_BASE_PRIORITY.get(topic, 1.0)
        source_priority = self._source_weight(news)
        keyword_priority = self._importance_keyword_score(news)
        freshness_priority = self._freshness_score(news, now)
        score = (topic_priority + keyword_priority) * source_priority * (0.7 + freshness_priority)
        return {
            'topic': topic,
            'topic_priority': topic_priority,
            'source_priority': source_priority,
            'keyword_priority': keyword_priority,
            'freshness_priority': freshness_priority,
            'score': score,
        }

    def is_breaking_news(self, news: Dict, threshold: Optional[float] = None) -> bool:
        text = self._news_text(news)
        high_hits = self._keyword_score(text, config.HIGH_IMPORTANCE_KEYWORDS)
        score = news.get('priority_score', 0.0)
        effective_threshold = threshold if threshold is not None else config.BREAKING_NEWS_MIN_PRIORITY
        return high_hits >= 2 or score >= effective_threshold

    def is_breaking_or_urgent(self, news: Dict) -> bool:
        return bool(news.get('is_breaking'))

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
                    'priority_score': news.get('priority_score', 0.0),
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
                if news.get('priority_score', 0.0) > grouped[normalized_url].get('priority_score', 0.0):
                    grouped[normalized_url]['priority_score'] = news.get('priority_score', 0.0)
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
        if incoming.get('priority_score', 0.0) > target.get('priority_score', 0.0):
            target['priority_score'] = incoming.get('priority_score', 0.0)
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

    def _is_ready_for_publish(self, news: Dict, now: datetime, breaking_mode: bool = False) -> bool:
        if breaking_mode and self.is_breaking_or_urgent(news):
            return True
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
                cluster[0]['priority_score'] = cluster[0].get('priority_score', 0.0)
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
                'priority_score': max(news.get('priority_score', 0.0) for news in cluster),
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

    async def process_and_publish_news(self, breaking_only: bool = False):
        try:
            logger.info("Начало сбора новостей%s...", " (режим срочных)" if breaking_only else "")
            all_news = await self.news_collector.collect_all_news()
            self.last_collector_stats = self.news_collector.last_fetch_stats
            new_news = self.news_collector.filter_new_news(all_news, self.database)
            effective_breaking_threshold = self._adaptive_breaking_threshold(len(new_news))

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
                breakdown = self._priority_breakdown(news)
                news['priority_score'] = breakdown['score']
                news['is_breaking'] = self.is_breaking_news(news, threshold=effective_breaking_threshold)
                if config.DEBUG_PRIORITY_LOGGING:
                    logger.info(
                        "Priority: topic=%s tp=%.2f kw=%.2f src=%.2f fresh=%.2f score=%.2f | %s",
                        breakdown['topic'],
                        breakdown['topic_priority'],
                        breakdown['keyword_priority'],
                        breakdown['source_priority'],
                        breakdown['freshness_priority'],
                        breakdown['score'],
                        news.get('title', '')[:100]
                    )
                if breaking_only and not news['is_breaking']:
                    continue
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
                key: news for key, news in self.pending_news.items()
                if self._is_ready_for_publish(news, now, breaking_mode=breaking_only)
            }

            if not matured_by_url:
                logger.info(
                    "Нет новостей, готовых к публикации%s",
                    " (режим срочных)" if breaking_only else " (ожидаем 30 минут для агрегации)"
                )
                return

            matured_news = list(matured_by_url.values())
            matured_news.sort(
                key=lambda x: (x.get('priority_score', 0.0), x['published_at']),
                reverse=True
            )
            publish_queue = self.merge_similar_news(matured_news)
            publish_queue.sort(
                key=lambda x: (x.get('priority_score', 0.0), x['published_at']),
                reverse=True
            )

            published_count = 0
            published_urls = set()

            for news in publish_queue:
                if published_count >= config.MAX_POSTS_PER_PUBLISH_CYCLE:
                    break
                if breaking_only and self._breaking_limit_reached(datetime.now(self.msk_tz)):
                    self.pending_breaking_digest.append(news)
                    continue
                related_news = self._find_related_news(news)
                success = await self.publish_news(news, related_news)
                if not success:
                    continue
                if breaking_only and news.get('is_breaking'):
                    self._record_breaking_publish(datetime.now(self.msk_tz))

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
        if topic == 'конфликт' and region == 'рф':
            return 'Вооружённые конфликты • РФ'
        if topic == 'конфликт' and region == 'мир':
            return 'Вооружённые конфликты • Мир'
        if topic == 'экономика' and region == 'рф':
            return 'Экономическая ситуация • РФ'
        if topic == 'политика' and region == 'рф':
            return 'Политика • РФ'
        if topic == 'общество' and region == 'рф':
            return 'Общество • РФ'
        if topic == 'политика' and region == 'мир':
            return 'Политика • Мир'
        return 'Прочее'

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
        news['priority_score'] = self._news_priority_score(news)
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
            self.last_collector_stats = self.news_collector.last_fetch_stats
            new_news = self.news_collector.filter_new_news(all_news, self.database)
            effective_breaking_threshold = self._adaptive_breaking_threshold(len(new_news))

            now_msk = datetime.now(self.msk_tz)
            lookback_boundary = now_msk - timedelta(hours=config.DIGEST_LOOKBACK_HOURS)
            filtered_news = [
                news for news in new_news
                if self._filter_news_for_digest(news)
                and self._to_msk(news.get('published_at', now_msk)) >= lookback_boundary
            ]

            buckets: Dict[str, List[Dict]] = {
                self._digest_bucket_key('конфликт', 'мир'): [],
                self._digest_bucket_key('конфликт', 'рф'): [],
                self._digest_bucket_key('экономика', 'рф'): [],
                self._digest_bucket_key('политика', 'рф'): [],
                self._digest_bucket_key('политика', 'мир'): [],
                self._digest_bucket_key('общество', 'рф'): []
            }

            for news in filtered_news:
                topic = self._detect_topic(news)
                if topic == 'неопределено':
                    continue
                region = self._detect_region(news)
                if region == 'мир' and topic in {'экономика', 'общество'}:
                    # Для мировой экономики/общества используем рубрику мировой политики,
                    # чтобы не терять значимые международные события.
                    bucket_key = self._digest_bucket_key('политика', 'мир')
                else:
                    bucket_key = self._digest_bucket_key(topic, region)
                if bucket_key in buckets:
                    buckets[bucket_key].append(news)

            for bucket_key, items in buckets.items():
                items.sort(
                    key=lambda x: (x.get('priority_score', 0.0), x['published_at']),
                    reverse=True
                )
                # Не обрезаем здесь: иначе overflow всегда пуст и вторая волна не сработает.
                buckets[bucket_key] = items

            used_urls = set()
            used_hashes = set()
            second_wave_posts = []

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

                first_wave_items = unique_items[:config.DIGEST_MAX_ITEMS]
                overflow_items = unique_items[config.DIGEST_MAX_ITEMS:]

                post_text = self.post_generator.format_digest_post(heading, first_wave_items, now_msk)
                await self._send_message(post_text)

                for item in first_wave_items:
                    self.database.save_news(
                        title=item['title'],
                        url=item['url'],
                        source=item['source'],
                        category=bucket_key,
                        published_at=item.get('published_at', now_msk),
                        description=item.get('description', '')
                    )

                if overflow_items:
                    second_wave_posts.append((bucket_key, heading, overflow_items))

                await asyncio.sleep(5)

            if second_wave_posts:
                delay_minutes = config.DIGEST_SECOND_WAVE_DELAY_MINUTES
                logger.info(
                    "Запланирована вторая волна сводки через %d минут для %d рубрик",
                    delay_minutes,
                    len(second_wave_posts)
                )
                await asyncio.sleep(delay_minutes * 60)

                for bucket_key, heading, overflow_items in second_wave_posts:
                    second_wave_heading = f"{heading} (вторая волна)"
                    second_wave_text = self.post_generator.format_digest_post(second_wave_heading, overflow_items, now_msk)
                    await self._send_message(second_wave_text)

                    for item in overflow_items:
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

    def _adaptive_breaking_threshold(self, recent_count: int) -> float:
        base = config.BREAKING_NEWS_MIN_PRIORITY
        delta = max(config.BREAKING_DYNAMIC_THRESHOLD_DELTA, 0)
        if recent_count >= 25:
            return base + delta
        if recent_count <= 5:
            return max(1.0, base - delta * 0.5)
        return base

    def _breaking_limit_reached(self, now_msk: datetime) -> bool:
        cutoff = now_msk - timedelta(hours=1)
        while self.breaking_publish_times and self.breaking_publish_times[0] < cutoff:
            self.breaking_publish_times.popleft()
        return len(self.breaking_publish_times) >= config.BREAKING_MAX_PER_HOUR

    def _record_breaking_publish(self, now_msk: datetime) -> None:
        self.breaking_publish_times.append(now_msk)

    async def _publish_pending_breaking_digest(self, now_msk: datetime) -> None:
        if not self.pending_breaking_digest:
            return
        heading = "Срочное за последний час"
        items = sorted(
            self.pending_breaking_digest,
            key=lambda x: (x.get('priority_score', 0.0), x.get('published_at', now_msk)),
            reverse=True
        )[:config.BREAKING_MINI_DIGEST_MAX_ITEMS]
        text = self.post_generator.format_digest_post(heading, items, now_msk)
        await self._send_message(text)
        for item in items:
            self.database.save_news(
                title=item['title'],
                url=item['url'],
                source=item.get('source', 'Unknown'),
                category='breaking_digest',
                published_at=item.get('published_at', now_msk),
                description=item.get('description', '')
            )
        self.pending_breaking_digest.clear()

    async def _send_admin_report(self, now_msk: datetime) -> None:
        if not config.ADMIN_CHAT_ID:
            return
        stats = self.database.get_news_stats()
        source_stats = self.last_collector_stats
        source_lines = []
        for source, values in sorted(source_stats.items(), key=lambda x: x[0]):
            source_lines.append(
                f"- {source}: ok={values.get('success', 0)} fail={values.get('fail', 0)} items={values.get('items', 0)}"
            )
        if not source_lines:
            source_lines.append("- пока нет данных")
        report = (
            f"*Ежедневный отчёт*\n"
            f"🕛 {now_msk.strftime('%d.%m.%Y %H:%M')} МСК\n\n"
            f"Опубликовано всего: {stats.get('total', 0)}\n"
            f"По категориям: {stats.get('by_category', {})}\n\n"
            f"*Состояние источников*\n" + "\n".join(source_lines)
        )
        try:
            await self.bot.send_message(chat_id=config.ADMIN_CHAT_ID, text=report)
        except Exception as exc:
            logger.warning("Не удалось отправить админ-отчёт: %s", exc)

    async def run_continuously(self):
        logger.info("Бот запущен. Сводки по расписанию МСК + режим срочных новостей.")
        next_digest_in = self._seconds_until_next_digest()
        next_digest_at = datetime.now(self.msk_tz) + timedelta(seconds=next_digest_in)

        while True:
            try:
                now_msk = datetime.now(self.msk_tz)
                if now_msk >= next_digest_at:
                    await self.publish_daily_digest()
                    await self._send_admin_report(now_msk)
                    next_digest_at = next_digest_at + timedelta(days=1)
                    continue

                if config.ENABLE_BREAKING_NEWS:
                    await self.process_and_publish_news(breaking_only=True)
                    await self._publish_pending_breaking_digest(now_msk)

                sleep_seconds = max(30, config.CHECK_INTERVAL_SECONDS)
                await asyncio.sleep(sleep_seconds)
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
