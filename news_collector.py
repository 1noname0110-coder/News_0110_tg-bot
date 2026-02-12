"""
Модуль для сбора новостей из различных RSS источников.
Обеспечивает получение актуальных новостей из 60+ источников.
"""

import feedparser
import aiohttp
import asyncio
import html
import re
from datetime import datetime
from urllib.parse import urlparse
from typing import List, Dict, Optional
import logging

import config

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class NewsCollector:
    """
    Класс для сбора новостей из RSS источников.
    Обрабатывает множество источников параллельно для эффективности.
    """
    
    def __init__(self, sources: List[Dict]):
        """
        Инициализация сборщика новостей.
        
        Args:
            sources: Список источников новостей (словари с полями name, url, category)
        """
        self.sources = sources
        self.timeout = 10  # Таймаут для запросов в секундах
        self.retry_attempts = max(getattr(config, "RSS_FETCH_RETRY_ATTEMPTS", 3), 1)
        self.retry_backoff_seconds = max(getattr(config, "RSS_FETCH_RETRY_BACKOFF_SECONDS", 1.5), 0.1)
        self.last_fetch_stats: Dict[str, Dict[str, int]] = {}
    

    def extract_image_urls(self, entry) -> List[str]:
        """Извлекает URL изображений из RSS entry."""
        image_urls = []

        for media in entry.get('media_content', []):
            url = media.get('url')
            if url:
                image_urls.append(url)

        for media in entry.get('media_thumbnail', []):
            url = media.get('url')
            if url:
                image_urls.append(url)

        for enclosure in entry.get('enclosures', []):
            url = enclosure.get('href') or enclosure.get('url')
            media_type = enclosure.get('type', '')
            if url and media_type.startswith('image/'):
                image_urls.append(url)

        summary = entry.get('summary', '') or entry.get('description', '')
        summary_img_urls = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', summary, flags=re.IGNORECASE)
        image_urls.extend(summary_img_urls)

        deduplicated = []
        seen = set()
        for url in image_urls:
            parsed = urlparse(url)
            if parsed.scheme in {'http', 'https'} and url not in seen:
                seen.add(url)
                deduplicated.append(url)

        return deduplicated

    async def fetch_feed(self, session: aiohttp.ClientSession, source: Dict) -> Optional[List[Dict]]:
        """
        Асинхронно получает новости из одного RSS источника.

        Args:
            session: Сессия aiohttp для выполнения HTTP запросов
            source: Словарь с информацией об источнике (name, url, category)

        Returns:
            Список словарей с новостями или None в случае ошибки
        """
        for attempt in range(1, self.retry_attempts + 1):
            try:
                async with session.get(source['url'], timeout=aiohttp.ClientTimeout(total=self.timeout)) as response:
                    if response.status == 200:
                        content = await response.text()
                        feed = feedparser.parse(content)

                        news_items = []
                        for entry in feed.entries[:10]:
                            title = entry.get('title', '').strip()
                            link = entry.get('link', '')

                            description = ''
                            if hasattr(entry, 'summary'):
                                description = entry.summary
                            elif hasattr(entry, 'description'):
                                description = entry.description

                            image_urls = self.extract_image_urls(entry)
                            description = re.sub(r'<[^>]+>', '', description)
                            description = html.unescape(description)
                            title = html.unescape(title)
                            description = description.strip()

                            published_time = datetime.now()
                            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                                try:
                                    published_time = datetime(*entry.published_parsed[:6])
                                except Exception:
                                    pass
                            elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                                try:
                                    published_time = datetime(*entry.updated_parsed[:6])
                                except Exception:
                                    pass

                            if title and link:
                                news_items.append({
                                    'title': title,
                                    'url': link,
                                    'description': description,
                                    'source': source['name'],
                                    'category': source.get('category', 'general'),
                                    'published_at': published_time,
                                    'images': image_urls
                                })

                        return news_items

                    logger.warning(
                        "Не удалось загрузить %s: HTTP %s (попытка %s/%s)",
                        source['name'],
                        response.status,
                        attempt,
                        self.retry_attempts,
                    )
                    if response.status < 500 and response.status != 429:
                        return None

            except asyncio.TimeoutError:
                logger.warning(
                    "Таймаут при загрузке %s (попытка %s/%s)",
                    source['name'],
                    attempt,
                    self.retry_attempts,
                )
            except Exception as e:
                logger.error(
                    "Ошибка при загрузке %s (попытка %s/%s): %s",
                    source['name'],
                    attempt,
                    self.retry_attempts,
                    str(e),
                )

            if attempt < self.retry_attempts:
                await asyncio.sleep(self.retry_backoff_seconds * attempt)

        return None

    async def collect_all_news(self) -> List[Dict]:
        """
        Собирает новости из всех источников параллельно.
        
        Returns:
            Список всех собранных новостей из всех источников
        """
        all_news = []
        
        # Создаем HTTP сессию
        async with aiohttp.ClientSession() as session:
            # Создаем задачи для параллельного получения новостей из всех источников
            tasks = [self.fetch_feed(session, source) for source in self.sources]
            
            # Ждем выполнения всех задач
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Обрабатываем результаты
            self.last_fetch_stats = {}
            for source, result in zip(self.sources, results):
                source_name = source.get('name', 'Unknown')
                self.last_fetch_stats[source_name] = {'success': 0, 'fail': 0, 'items': 0}
                if isinstance(result, list):
                    all_news.extend(result)
                    self.last_fetch_stats[source_name]['success'] = 1
                    self.last_fetch_stats[source_name]['items'] = len(result)
                elif isinstance(result, Exception):
                    logger.error(f"Ошибка при сборе новостей: {str(result)}")
                    self.last_fetch_stats[source_name]['fail'] = 1
                else:
                    self.last_fetch_stats[source_name]['fail'] = 1
        
        # Сортируем новости по дате публикации (новые первыми)
        all_news.sort(key=lambda x: x['published_at'], reverse=True)
        
        logger.info(f"Собрано новостей: {len(all_news)}")
        return all_news
    
    def filter_new_news(self, all_news: List[Dict], database) -> List[Dict]:
        """
        Фильтрует новости, оставляя только те, которые еще не были опубликованы.
        
        Args:
            all_news: Список всех собранных новостей
            database: Объект NewsDatabase для проверки опубликованных новостей
            
        Returns:
            Список новостей, которые еще не были опубликованы
        """
        new_news = []
        
        for news in all_news:
            # Проверяем, была ли новость уже опубликована
            if not database.is_news_published(
                news['title'],
                news['url'],
                news['source'],
                news.get('description', '')
            ):
                new_news.append(news)
        
        logger.info(f"Новых новостей для публикации: {len(new_news)}")
        return new_news
