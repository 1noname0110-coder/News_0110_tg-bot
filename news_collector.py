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
        try:
            # Выполняем HTTP запрос к RSS фиду
            async with session.get(source['url'], timeout=aiohttp.ClientTimeout(total=self.timeout)) as response:
                if response.status == 200:
                    # Читаем содержимое ответа
                    content = await response.text()
                    
                    # Парсим RSS с помощью feedparser
                    feed = feedparser.parse(content)
                    
                    news_items = []
                    for entry in feed.entries[:10]:  # Берем последние 10 новостей из каждого источника
                        # Извлекаем информацию о новости
                        title = entry.get('title', '').strip()
                        link = entry.get('link', '')
                        
                        # Получаем описание новости
                        description = ''
                        if hasattr(entry, 'summary'):
                            description = entry.summary
                        elif hasattr(entry, 'description'):
                            description = entry.description
                        
                        image_urls = self.extract_image_urls(entry)

                        # Очищаем описание от HTML тегов
                        description = re.sub(r'<[^>]+>', '', description)
                        
                        # Декодируем HTML-сущности (например, &nbsp; -> пробел, &amp; -> &)
                        description = html.unescape(description)
                        
                        # Очищаем заголовок от HTML-сущностей
                        title = html.unescape(title)
                        
                        description = description.strip()
                        
                        # Получаем дату публикации
                        published_time = datetime.now()
                        if hasattr(entry, 'published_parsed') and entry.published_parsed:
                            try:
                                published_time = datetime(*entry.published_parsed[:6])
                            except:
                                pass
                        elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                            try:
                                published_time = datetime(*entry.updated_parsed[:6])
                            except:
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
                else:
                    logger.warning(f"Не удалось загрузить {source['name']}: HTTP {response.status}")
                    return None
                    
        except asyncio.TimeoutError:
            logger.warning(f"Таймаут при загрузке {source['name']}")
            return None
        except Exception as e:
            logger.error(f"Ошибка при загрузке {source['name']}: {str(e)}")
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
            for result in results:
                if isinstance(result, list):
                    all_news.extend(result)
                elif isinstance(result, Exception):
                    logger.error(f"Ошибка при сборе новостей: {str(result)}")
        
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
            if not database.is_news_published(news['title'], news['url'], news['source']):
                new_news.append(news)
        
        logger.info(f"Новых новостей для публикации: {len(new_news)}")
        return new_news
