"""
Модуль для генерации текста постов из новостей.
Форматирует новости в читаемый вид для публикации в канале.
"""

import re
import html
from typing import Dict, Optional, List
from datetime import datetime

class PostGenerator:
    """
    Класс для генерации текста постов из новостей.
    Форматирует новости в удобочитаемый формат для канала.
    """
    
    def __init__(self, max_length: int = 4500):
        """
        Инициализация генератора постов.
        
        Args:
            max_length: Максимальная длина поста в символах
        """
        self.max_length = max_length
    
    def clean_text(self, text: str) -> str:
        """
        Очищает текст от лишних символов и форматирует его.
        Удаляет HTML-сущности и нормализует пробелы.
        
        Args:
            text: Исходный текст
            
        Returns:
            Очищенный текст
        """
        if not text:
            return ""
        
        # Декодируем HTML-сущности (например, &nbsp; -> пробел, &amp; -> &, &quot; -> ")
        text = html.unescape(text)
        
        # Заменяем неразрывные пробелы и другие специальные пробелы на обычные
        text = text.replace('\u00A0', ' ')  # Неразрывный пробел
        text = text.replace('\u2009', ' ')  # Тонкий пробел
        text = text.replace('\u2006', ' ')  # Шестипунктовый пробел
        
        # Удаляем множественные пробелы
        text = re.sub(r'\s+', ' ', text)
        
        # Удаляем пробелы в начале и конце
        text = text.strip()
        
        # Удаляем специальные символы, которые могут мешать форматированию
        text = text.replace('\r\n', '\n')
        text = text.replace('\r', '\n')
        
        return text
    
    def escape_markdown(self, text: str) -> str:
        """
        Экранирует специальные символы Markdown в тексте.
        Это необходимо для безопасного использования текста в Markdown-разметке Telegram.
        
        Args:
            text: Текст для экранирования
            
        Returns:
            Текст с экранированными Markdown символами
        """
        # Символы, которые нужно экранировать в Markdown
        markdown_chars = ['*', '_', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        for char in markdown_chars:
            # Исключаем символы, которые могут быть частью URL или уже экранированы
            text = text.replace(char, f'\\{char}')
        return text
    
    def remove_title_echo(self, title: str, description: str) -> str:
        """Удаляет дублирование заголовка в начале описания."""
        clean_title = self.clean_text(title)
        clean_title_lc = clean_title.lower().strip(' .:;-')
        clean_description = self.clean_text(description)
        description_lc = clean_description.lower().strip()

        if not clean_description:
            return clean_description

        if description_lc == clean_title_lc:
            return ''

        if description_lc.startswith(clean_title_lc):
            trimmed = clean_description[len(clean_title):].lstrip(' .,:;-\n\t')
            return trimmed

        return clean_description

    def format_post(self, news: Dict, related_news: Optional[Dict] = None) -> str:
        """
        Форматирует новость в текст поста для публикации.
        
        Args:
            news: Словарь с информацией о новости (может содержать 'categories' - список категорий)
            related_news: Связанная новость (если создается дополняющий пост)
            
        Returns:
            Отформатированный текст поста
        """
        title = self.clean_text(news['title'])
        description = self.clean_text(news.get('description', ''))
        description = self.remove_title_echo(title, description)
        url = news['url']
        # Поддерживаем как старый формат (одна категория), так и новый (список категорий)
        if 'sources' in news and isinstance(news['sources'], list):
            source = ', '.join(news['sources']) if len(news['sources']) > 1 else (news['sources'][0] if news['sources'] else 'Unknown')
        else:
            source = news.get('source', 'Unknown')
        
        # Начинаем формировать пост
        post_parts = []
        
        if news.get('is_merged_topic'):
            topic_size = news.get('topic_size', 1)
            post_parts.append(f"🧩 *Сводка по теме* · объединено источников: {topic_size}")
            post_parts.append("")
        elif related_news:
            post_parts.append(f"📰 *Дополнение к новости*")
            post_parts.append("")
        
        # Добавляем заголовок
        post_parts.append(f"*{title}*")
        post_parts.append("")
        
        # Добавляем описание, если оно есть
        if description:
            # Ограничиваем длину описания, чтобы весь пост не превышал лимит
            max_desc_length = self.max_length - len(title) - len(source) - 200  # Резерв для форматирования
            
            if len(description) > max_desc_length:
                # Обрезаем описание и добавляем многоточие
                description = description[:max_desc_length - 3] + "..."
            
            post_parts.append(description)
            post_parts.append("")
        
        # Добавляем источник и ссылку
        post_parts.append(f"📌 Источник: {source}")
        post_parts.append(f"🔗 [Читать полностью]({url})")

        for extra_url in news.get('alternate_urls', [])[:3]:
            post_parts.append(f"🔗 [Дополнительный источник]({extra_url})")

        image_urls = news.get('images', [])
        if image_urls:
            post_parts.append("")
            post_parts.append("🖼 Изображения по теме:")
            for image_url in image_urls[:3]:
                post_parts.append(f"• {image_url}")
        
        # Если есть связанная новость, добавляем ссылку на неё
        if related_news and not news.get('is_merged_topic'):
            post_parts.append("")
            post_parts.append(f"📖 *Связанная новость:* {related_news['title']}")
        
        # Объединяем все части
        post_text = "\n".join(post_parts)
        
        # Проверяем длину поста
        if len(post_text) > self.max_length:
            # Если пост слишком длинный, обрезаем его
            post_text = post_text[:self.max_length - 3] + "..."
        
        return post_text
    
    def can_combine_with_related(self, news: Dict, related_news: Dict) -> bool:
        """
        Проверяет, можно ли объединить новость со связанной в один пост.
        
        Args:
            news: Текущая новость
            related_news: Связанная новость
            
        Returns:
            True, если новости можно объединить, False в противном случае
        """
        # Создаем тестовый пост для проверки длины
        combined_post = self.format_post(news, related_news)
        return len(combined_post) <= self.max_length
    
    def get_category_emoji(self, category: str) -> str:
        """
        Возвращает emoji для категории новости.
        
        Args:
            category: Категория новости
            
        Returns:
            Emoji символ для категории
        """
        emoji_map = {
            'general': '📰',
            'politics': '🏛️',
            'world': '🌍',
            'tech': '💻',
            'cars': '🚗'
        }
        return emoji_map.get(category, '📰')
    
    def add_category_tag(self, post_text: str, categories) -> str:
        """
        Добавляет тег категории (или категорий) в начало поста.
        
        Args:
            post_text: Текст поста
            categories: Категория новости (строка) или список категорий
            
        Returns:
            Текст поста с добавленным тегом категории
        """
        # Поддерживаем как одну категорию (строка), так и несколько (список)
        if isinstance(categories, list):
            # Если категорий несколько, показываем все с соответствующими emoji
            category_tags = []
            for cat in categories:
                emoji = self.get_category_emoji(cat)
                category_tags.append(f"{emoji} {cat.upper()}")
            category_line = " | ".join(category_tags)
        else:
            # Одна категория (старый формат)
            emoji = self.get_category_emoji(categories)
            category_line = f"{emoji} {categories.upper()}"
        
        return f"{category_line}\n\n{post_text}"
