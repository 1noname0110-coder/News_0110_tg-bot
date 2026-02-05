"""
Основной файл телеграм-бота для публикации новостей в канал.
Бот работает круглосуточно, собирая и публикуя новости из различных источников.
"""

import asyncio
import logging
import time
from datetime import datetime
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
    """
    Главный класс бота для публикации новостей в канал.
    Управляет сбором, фильтрацией и публикацией новостей.
    """
    
    def __init__(self):
        """
        Инициализация бота и всех необходимых компонентов.
        """
        # Инициализация Telegram бота с токеном от @BotFather
        self.bot = Bot(token=config.BOT_TOKEN)
        
        # ID канала, куда будут публиковаться новости
        self.channel_id = config.CHANNEL_ID
        
        # Инициализация базы данных для отслеживания опубликованных новостей
        self.database = NewsDatabase(config.DATABASE_PATH)
        
        # Инициализация сборщика новостей с источниками из конфига
        self.news_collector = NewsCollector(config.NEWS_SOURCES)
        
        # Инициализация генератора постов с максимальной длиной
        self.post_generator = PostGenerator(config.MAX_POST_LENGTH)
        
        # Переменная для хранения времени последней публикации по категориям
        # Используется для балансировки контента (не публикуем одинаковые категории слишком часто)
        self.last_publish_time_by_category = {category: None for category in config.CATEGORIES}
        
        logger.info("Бот инициализирован")
    
    async def publish_news(self, news: dict, related_news: Optional[dict] = None) -> bool:
        """
        Публикует новость в канал Telegram.
        
        Args:
            news: Словарь с информацией о новости
            related_news: Связанная новость (если создается дополняющий пост)
            
        Returns:
            True, если публикация успешна, False в противном случае
        """
        try:
            # Генерируем текст поста из новости
            post_text = self.post_generator.format_post(news, related_news)
            
            # Добавляем тег категории (или категорий) в начало поста
            # Поддерживаем как старый формат (одна категория), так и новый (список категорий)
            if 'categories' in news and isinstance(news['categories'], list):
                categories = news['categories']
            else:
                categories = news.get('category', 'general')
            
            post_text = self.post_generator.add_category_tag(post_text, categories)
            
            # Публикуем пост в канал
            # parse_mode=ParseMode.MARKDOWN позволяет использовать форматирование Markdown (*жирный*, [ссылки](url))
            try:
                await self.bot.send_message(
                    chat_id=self.channel_id,
                    text=post_text,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=False  # Показываем превью ссылок
                )
            except Exception as markdown_error:
                # Если возникла ошибка форматирования Markdown, пытаемся опубликовать без разметки
                logger.warning(f"Ошибка Markdown форматирования, публикуем без разметки: {str(markdown_error)}")
                # Удаляем Markdown символы для plain текста
                plain_text = post_text.replace('*', '').replace('[', '').replace(']', '').replace('(', '').replace(')', '')
                await self.bot.send_message(
                    chat_id=self.channel_id,
                    text=plain_text,
                    disable_web_page_preview=False
                )
            
            logger.info(f"Опубликована новость: {news['title'][:50]}...")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка при публикации новости '{news['title']}': {str(e)}")
            return False
    
    def should_publish_category(self, category: str) -> bool:
        """
        Проверяет, можно ли публиковать новость данной категории.
        Используется для балансировки контента - не публикуем одинаковые категории слишком часто.
        
        Args:
            category: Категория новости
            
        Returns:
            True, если можно публиковать, False в противном случае
        """
        last_time = self.last_publish_time_by_category.get(category)
        
        # Если категория еще не публиковалась, можно публиковать
        if last_time is None:
            return True
        
        # Проверяем, прошло ли достаточно времени с последней публикации этой категории
        time_diff = (datetime.now() - last_time).total_seconds() / 60  # Разница в минутах
        
        # Если прошло больше минимального интервала, можно публиковать
        return time_diff >= config.MIN_INTERVAL_BETWEEN_SAME_CATEGORY
    
    def group_news_by_url(self, news_list: List[Dict]) -> Dict[str, Dict]:
        """
        Группирует новости по URL. Если одна новость подходит под несколько категорий,
        объединяет их в одну запись со всеми категориями.
        
        Args:
            news_list: Список новостей для группировки
            
        Returns:
            Словарь, где ключ - нормализованный URL, значение - объединенная новость со всеми категориями
        """
        grouped = {}
        
        for news in news_list:
            # Нормализуем URL для группировки
            normalized_url = self.database.normalize_url(news['url'])
            
            if normalized_url not in grouped:
                # Первая новость с этим URL - создаем запись
                grouped[normalized_url] = {
                    'title': news['title'],
                    'url': news['url'],
                    'description': news.get('description', ''),
                    'source': news['source'],
                    'categories': [news['category']],  # Список категорий
                    'sources': [news['source']],  # Список источников
                    'published_at': news['published_at']
                }
            else:
                # Новость с таким же URL - добавляем категорию и источник
                if news['category'] not in grouped[normalized_url]['categories']:
                    grouped[normalized_url]['categories'].append(news['category'])
                
                if news['source'] not in grouped[normalized_url]['sources']:
                    grouped[normalized_url]['sources'].append(news['source'])
                
                # Берем более полное описание, если есть
                if news.get('description') and len(news['description']) > len(grouped[normalized_url]['description']):
                    grouped[normalized_url]['description'] = news['description']
                
                # Берем более свежую дату публикации
                if news['published_at'] > grouped[normalized_url]['published_at']:
                    grouped[normalized_url]['published_at'] = news['published_at']
        
        return grouped
    
    async def process_and_publish_news(self):
        """
        Основной метод обработки и публикации новостей.
        Собирает новости, фильтрует дубликаты, группирует по URL и публикует их в канал.
        Если новость подходит под несколько категорий, публикует один раз со всеми категориями.
        """
        try:
            logger.info("Начало сбора новостей...")
            
            # Собираем новости из всех источников
            all_news = await self.news_collector.collect_all_news()
            
            # Фильтруем новости, оставляя только те, которые еще не были опубликованы
            new_news = self.news_collector.filter_new_news(all_news, self.database)
            
            if not new_news:
                logger.info("Нет новых новостей для публикации")
                return
            
            # Группируем новости по URL (если одна новость в разных категориях - объединяем)
            grouped_news = self.group_news_by_url(new_news)
            
            # Преобразуем в список для сортировки
            unique_news = list(grouped_news.values())
            
            # Сортируем новости по дате публикации (новые первыми)
            unique_news.sort(key=lambda x: x['published_at'], reverse=True)
            
            # Публикуем новости по очереди
            published_count = 0
            
            for news in unique_news:
                # Определяем основную категорию (первую из списка или наиболее подходящую)
                # Если категорий несколько, используем первую, но в посте покажем все
                main_category = news['categories'][0]
                
                # Проверяем, можно ли публиковать эту категорию (балансировка контента)
                # Проверяем все категории - если хотя бы одну можно публиковать, публикуем
                can_publish = any(
                    self.should_publish_category(cat) for cat in news['categories']
                )
                
                if not can_publish:
                    logger.debug(f"Пропущена новость категорий {news['categories']} (слишком недавно публиковались)")
                    continue
                
                # Пытаемся найти связанную новость для создания дополняющего поста
                related_news = None
                
                # Ищем недавние новости по любой из категорий
                for category in news['categories']:
                    recent_news = self.database.get_recent_news_by_category(category, hours=24, limit=3)
                    
                    # Простая проверка на связь: если заголовки имеют общие слова
                    if recent_news:
                        news_words = set(news['title'].lower().split())
                        for recent in recent_news:
                            recent_words = set(recent['title'].lower().split())
                            # Если есть хотя бы 2 общих значимых слова (длиной > 4 символов)
                            common_words = {w for w in news_words & recent_words if len(w) > 4}
                            if len(common_words) >= 2:
                                related_news = recent
                                break
                    
                    if related_news:
                        break
                
                # Публикуем новость (со всеми категориями)
                success = await self.publish_news(news, related_news)
                
                if success:
                    # Сохраняем новость в базу данных для каждой категории
                    # Это нужно для правильной работы статистики и связанных постов
                    news_ids = []
                    for category in news['categories']:
                        news_id = self.database.save_news(
                            title=news['title'],
                            url=news['url'],
                            source=news['sources'][0] if news['sources'] else 'Unknown',
                            category=category,
                            published_at=news['published_at']
                        )
                        if news_id:
                            news_ids.append(news_id)
                    
                    # Если есть связанная новость, сохраняем связь
                    if related_news and news_ids and 'id' in related_news:
                        related_id = related_news['id']
                        for news_id in news_ids:
                            self.database.link_related_posts(related_id, news_id)
                    
                    # Обновляем время последней публикации для всех категорий
                    for category in news['categories']:
                        self.last_publish_time_by_category[category] = datetime.now()
                    
                    published_count += 1
                    
                    # Небольшая задержка между публикациями, чтобы не перегружать канал
                    await asyncio.sleep(5)
            
            logger.info(f"Опубликовано новостей: {published_count}")
            
        except Exception as e:
            logger.error(f"Ошибка при обработке новостей: {str(e)}", exc_info=True)
    
    async def run_continuously(self):
        """
        Запускает бота в режиме непрерывной работы.
        Бот будет автоматически собирать и публиковать новости с заданным интервалом.
        """
        logger.info("Бот запущен и работает...")
        
        # Первая публикация сразу после запуска
        await self.process_and_publish_news()
        
        # Запускаем бесконечный цикл с заданным интервалом
        while True:
            try:
                # Ждем заданный интервал (в минутах, переводим в секунды)
                await asyncio.sleep(config.PUBLISH_INTERVAL_MINUTES * 60)
                
                # Обрабатываем и публикуем новости
                await self.process_and_publish_news()
                
            except KeyboardInterrupt:
                # Если пользователь нажал Ctrl+C, корректно завершаем работу
                logger.info("Получен сигнал остановки, завершение работы...")
                break
            except Exception as e:
                logger.error(f"Ошибка в основном цикле: {str(e)}", exc_info=True)
                # Небольшая задержка перед повтором при ошибке
                await asyncio.sleep(60)

def main():
    """
    Главная функция для запуска бота.
    Создает экземпляр бота и запускает его в режиме непрерывной работы.
    """
    # Проверяем, что все необходимые параметры настроены
    if not config.BOT_TOKEN:
        logger.error("BOT_TOKEN не установлен! Установите его в файле .env")
        return
    
    if not config.CHANNEL_ID:
        logger.error("CHANNEL_ID не установлен! Установите его в файле .env")
        return
    
    # Создаем экземпляр бота
    news_bot = NewsBot()
    
    # Запускаем бота в асинхронном режиме
    # asyncio.run() автоматически создает event loop и запускает асинхронную функцию
    try:
        asyncio.run(news_bot.run_continuously())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")

if __name__ == "__main__":
    # Запускаем бота при выполнении скрипта
    main()


