"""
Основной файл телеграм-бота для публикации новостей в канал.
Бот работает круглосуточно, собирая и публикуя новости из различных источников.
"""

import asyncio
import logging
import re
import time
from datetime import datetime, timedelta
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
        self.last_publish_time_by_category = {category: None for category in config.CATEGORIES}
        self.pending_news: Dict[str, Dict] = {}

        logger.info("Бот инициализирован")

    async def publish_news(self, news: dict, related_news: Optional[dict] = None) -> bool:
        """Публикует новость в канал Telegram."""
        try:
            post_text = self.post_generator.format_post(news, related_news)
            categories = news.get('categories', news.get('category', 'general'))
            post_text = self.post_generator.add_category_tag(post_text, categories)

            try:
                await self.bot.send_message(
                    chat_id=self.channel_id,
                    text=post_text,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=False
                )
            except Exception as markdown_error:
                logger.warning(f"Ошибка Markdown форматирования, публикуем без разметки: {str(markdown_error)}")
                plain_text = post_text.replace('*', '').replace('[', '').replace(']', '').replace('(', '').replace(')', '')
                await self.bot.send_message(
                    chat_id=self.channel_id,
                    text=plain_text,
                    disable_web_page_preview=False
                )

            logger.info(f"Опубликована новость: {news['title'][:80]}...")
            return True
        except Exception as e:
            logger.error(f"Ошибка при публикации новости '{news['title']}': {str(e)}")
            return False

    def should_publish_category(self, category: str) -> bool:
        last_time = self.last_publish_time_by_category.get(category)
        if last_time is None:
            return True
        time_diff = (datetime.now() - last_time).total_seconds() / 60
        return time_diff >= config.MIN_INTERVAL_BETWEEN_SAME_CATEGORY

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

    def group_news_by_url(self, news_list: List[Dict]) -> Dict[str, Dict]:
        grouped = {}
        now = datetime.now()

        for news in news_list:
            normalized_url = self.database.normalize_url(news['url'])
            if normalized_url not in grouped:
                grouped[normalized_url] = {
                    'title': news['title'],
                    'url': news['url'],
                    'description': news.get('description', ''),
                    'source': news['source'],
                    'categories': [news['category']],
                    'sources': [news['source']],
                    'images': news.get('images', []),
                    'published_at': news['published_at'],
                    'first_seen_at': now,
                    'combined_items': [news]
                }
            else:
                if news['category'] not in grouped[normalized_url]['categories']:
                    grouped[normalized_url]['categories'].append(news['category'])
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

    def add_to_pending(self, grouped_news: Dict[str, Dict]):
        for normalized_url, news in grouped_news.items():
            existing = self.pending_news.get(normalized_url)
            if not existing:
                self.pending_news[normalized_url] = news
                continue

            for category in news['categories']:
                if category not in existing['categories']:
                    existing['categories'].append(category)
            for source in news['sources']:
                if source not in existing['sources']:
                    existing['sources'].append(source)
            for image_url in news.get('images', []):
                if image_url not in existing['images']:
                    existing['images'].append(image_url)
            if len(news.get('description', '')) > len(existing.get('description', '')):
                existing['description'] = news['description']
            existing['combined_items'].extend(news.get('combined_items', []))

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

            filtered_news = [news for news in new_news if not self.is_unwanted_local_news(news)]
            dropped_count = len(new_news) - len(filtered_news)
            if dropped_count:
                logger.info(f"Отфильтровано локальных криминальных новостей: {dropped_count}")

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
                can_publish = any(self.should_publish_category(cat) for cat in news.get('categories', []))
                if not can_publish:
                    continue

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
                            published_at=item.get('published_at', news['published_at'])
                        )
                    normalized_url = self.database.normalize_url(item['url'])
                    published_urls.add(normalized_url)

                for category in news.get('categories', []):
                    self.last_publish_time_by_category[category] = datetime.now()

                published_count += 1
                await asyncio.sleep(5)

            for normalized_url in published_urls:
                self.pending_news.pop(normalized_url, None)

            logger.info(f"Опубликовано новостей: {published_count}")
        except Exception as e:
            logger.error(f"Ошибка при обработке новостей: {str(e)}", exc_info=True)

    async def run_continuously(self):
        logger.info("Бот запущен и работает 24/7...")
        await self.process_and_publish_news()

        while True:
            try:
                await asyncio.sleep(config.PUBLISH_INTERVAL_MINUTES * 60)
                await self.process_and_publish_news()
            except KeyboardInterrupt:
                logger.info("Получен сигнал остановки, завершение работы...")
                break
            except Exception as e:
                logger.error(f"Ошибка в основном цикле: {str(e)}", exc_info=True)
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
