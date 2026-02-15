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

        # Изображения отправляются как вложения в Telegram, ссылки не добавляем в текст поста.
        
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

    def summarize_description(self, description: str, max_length: int = 180) -> str:
        """
        Возвращает краткую суть из описания новости.

        Args:
            description: Описание новости
            max_length: Максимальная длина краткой сути

        Returns:
            Короткий фрагмент без «воды»
        """
        clean_description = self.clean_text(description)
        if not clean_description:
            return ""

        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', clean_description) if s.strip()]
        if not sentences:
            return ""

        # Выбираем максимально информативное предложение из первых нескольких.
        candidates = sentences[:4]

        def sentence_score(sentence: str) -> int:
            score = min(len(sentence), 220)
            if re.search(r'\d', sentence):
                score += 40
            if any(marker in sentence.lower() for marker in ['заявил', 'сообщил', 'принял', 'подписал', 'одобрил']):
                score += 25
            return score

        summary = max(candidates, key=sentence_score)

        if len(summary) > max_length:
            summary = summary[:max_length - 1].rstrip() + "…"

        return summary

    def format_digest_post(self, heading: str, items: List[Dict], generated_at: Optional[datetime] = None) -> str:
        """
        Формирует ежедневную сводку по выбранной теме.

        Args:
            heading: Заголовок сводки
            items: Список новостей
            generated_at: Время формирования

        Returns:
            Текст сводки
        """
        post_parts = [f"*{heading}*"]

        if generated_at:
            post_parts.append(f"🕛 {generated_at.strftime('%d.%m.%Y %H:%M')} МСК")

        post_parts.append("")

        if not items:
            post_parts.append("Сегодня без значимых новостей.")
            return "\n".join(post_parts)

        for item in items:
            title = self.clean_text(item.get('title', ''))
            summary = self.summarize_description(item.get('description', ''))
            url = item.get('url', '')
            if summary:
                post_parts.append(f"• [{title}]({url}) — {summary}")
            else:
                post_parts.append(f"• [{title}]({url})")

        return "\n".join(post_parts)


    def compress_to_fact_line(self, news: Dict, max_length: int = 180) -> str:
        """Сжимает новость до 1 строки факта без оценок и «воды»."""
        title = self.clean_text(news.get('title', ''))
        description = self.clean_text(news.get('description', ''))

        base = title
        if description:
            summary = self.summarize_description(description, max_length=110)
            if summary and summary.lower() not in title.lower():
                base = f"{title} — {summary}"

        # Убираем цитаты/оценочные хвосты
        base = re.sub(r'[«"].{0,120}?[»"]', '', base)
        base = re.sub(r'\b(по его словам|по её словам|как считает|как полагает)\b.*$', '', base, flags=re.IGNORECASE)
        base = re.sub(r'\s+', ' ', base).strip(' .,-')

        if len(base) > max_length:
            base = base[:max_length - 1].rstrip() + '…'

        return base

    def format_structured_digest(self, title: str, grouped_news: Dict[str, List[Dict]], generated_at: Optional[datetime] = None) -> List[str]:
        """Формирует структурированный дневной отчёт в формате ТЗ."""
        ordered_sections = [
            ('РОССИЯ', ['Политика', 'Экономика', 'Безопасность']),
            ('МИР', ['Геополитика', 'Экономика', 'Жизнь за рубежом']),
        ]

        lines = [f"*{title}*"]
        if generated_at:
            lines.append(f"🕛 {generated_at.strftime('%d.%m.%Y %H:%M')} МСК")
        lines.append('')

        for block_name, rubrics in ordered_sections:
            lines.append(f"*{block_name}*")
            for rubric in rubrics:
                lines.append(f"_{rubric}_")
                bucket_key = f"{block_name}|{rubric}"
                bucket_items = grouped_news.get(bucket_key, [])
                if not bucket_items:
                    lines.append('• —')
                    continue
                for item in bucket_items:
                    lines.append(f"• {self.compress_to_fact_line(item)}")
                lines.append('')

        full_text = "\n".join(lines).strip()
        if len(full_text) <= self.max_length:
            return [full_text]

        chunks: List[str] = []
        current = ''
        for line in lines:
            candidate = (current + "\n" + line).strip() if current else line
            if len(candidate) <= self.max_length:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                current = f"*{title} (продолжение)*\n{line}"

        if current:
            chunks.append(current)

        return chunks
    def format_currency_post(self, rates: Dict, updated_at: datetime) -> str:
        """Формирует краткий сервисный пост с курсами."""
        date_line = updated_at.strftime('%d.%m.%Y')
        time_line = updated_at.strftime('%H:%M')

        usd_rub = float(rates['usd_rub'])
        eur_rub = float(rates['eur_rub'])
        cny_rub = float(rates['cny_rub'])
        rub_usd = float(rates['rub_usd'])
        btc_usd = float(rates['btc_usd'])
        btc_rub = float(rates['btc_rub'])

        return (
            "*Курсы валют*\n"
            f"{date_line}\n\n"
            f"$ Доллар — {usd_rub:.2f} ₽\n"
            f"€ Евро — {eur_rub:.2f} ₽\n"
            f"¥ Юань — {cny_rub:.2f} ₽\n"
            f"₽ Рубль — {rub_usd:.4f} $\n"
            f"₿ Bitcoin — {btc_usd:,.0f} $ / {btc_rub:,.0f} ₽\n\n"
            f"Обновлено: {time_line} МСК"
        ).replace(',', ' ')

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
            'мир': '🌍',
            'россия': '🇷🇺',
            'экономика': '💹',
            'экономика рф': '💹🇷🇺',
            'политика рф': '🏛️🇷🇺',
            'политика мир': '🏛️🌍',
            'общество рф': '👥🇷🇺',
            'вооружённые конфликты мир': '🌍⚔️',
            'вооружённые конфликты рф': '🇷🇺⚔️',
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
