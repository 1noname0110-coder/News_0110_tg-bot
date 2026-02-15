"""
Модуль для работы с базой данных.
Хранит информацию об уже опубликованных новостях для избежания дубликатов.
"""

import sqlite3
import hashlib
import re
from datetime import datetime
from typing import Optional, List, Dict

class NewsDatabase:
    """
    Класс для работы с базой данных опубликованных новостей.
    Использует SQLite для хранения информации о новостях.
    """
    
    def __init__(self, db_path: str = 'news_bot.db'):
        """
        Инициализация подключения к базе данных.
        
        Args:
            db_path: Путь к файлу базы данных SQLite
        """
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """
        Создание таблиц в базе данных, если они не существуют.
        Таблица news хранит информацию о опубликованных новостях.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Создаем таблицу для хранения опубликованных новостей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                news_hash TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                source TEXT NOT NULL,
                url TEXT NOT NULL,
                category TEXT NOT NULL,
                content_hash TEXT,
                published_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Обновляем схему базы данных при необходимости
        cursor.execute("PRAGMA table_info(news)")
        existing_columns = {row[1] for row in cursor.fetchall()}
        if 'content_hash' not in existing_columns:
            cursor.execute('ALTER TABLE news ADD COLUMN content_hash TEXT')
        
        # Создаем таблицу для хранения связанных постов (для дополняющих постов)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS related_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_post_id INTEGER NOT NULL,
                related_post_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (original_post_id) REFERENCES news(id),
                FOREIGN KEY (related_post_id) REFERENCES news(id)
            )
        ''')
        
        # Таблица снимков курсов валют (для антидублирования сервисных постов)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS currency_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_hash TEXT UNIQUE NOT NULL,
                post_type TEXT NOT NULL,
                usd_rub REAL NOT NULL,
                eur_rub REAL NOT NULL,
                cny_rub REAL NOT NULL,
                rub_usd REAL NOT NULL,
                btc_usd REAL NOT NULL,
                btc_rub REAL NOT NULL,
                published_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Создаем индексы для быстрого поиска
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_news_hash ON news(news_hash)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_news_published_at ON news(published_at)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_news_category ON news(category)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_news_url ON news(url)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_news_content_hash ON news(content_hash)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_currency_published_at ON currency_snapshots(published_at)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_currency_post_type ON currency_snapshots(post_type)')
        
        conn.commit()
        conn.close()
    
    def generate_hash(self, title: str, url: str, source: str) -> str:
        """
        Генерирует уникальный хеш для новости на основе заголовка, URL и источника.
        Это позволяет определять, была ли новость уже опубликована.
        
        Args:
            title: Заголовок новости
            url: URL новости
            source: Источник новости
            
        Returns:
            MD5 хеш строки, составленной из параметров
        """
        # Составляем строку для хеширования
        hash_string = f"{source}|{url}|{title.lower().strip()}"
        return hashlib.md5(hash_string.encode('utf-8')).hexdigest()

    def normalize_content(self, title: str, description: str) -> str:
        """
        Нормализует содержимое новости для сравнения по смыслу.

        Args:
            title: Заголовок новости
            description: Описание новости

        Returns:
            Нормализованный текст
        """
        text = f"{title} {description}".lower().strip()
        text = re.sub(r'[^\w\s]', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    def generate_content_hash(self, title: str, description: str) -> str:
        """
        Генерирует хеш на основе содержания новости (заголовок + описание).

        Args:
            title: Заголовок новости
            description: Описание новости

        Returns:
            MD5 хеш нормализованного текста
        """
        normalized = self.normalize_content(title, description)
        return hashlib.md5(normalized.encode('utf-8')).hexdigest() if normalized else ''
    
    def normalize_title(self, title: str) -> str:
        """
        Нормализует заголовок для сравнения: приводит к нижнему регистру,
        удаляет знаки препинания и лишние пробелы.
        
        Args:
            title: Исходный заголовок
            
        Returns:
            Нормализованный заголовок
        """
        # Приводим к нижнему регистру
        normalized = title.lower().strip()
        
        # Удаляем знаки препинания и специальные символы
        normalized = re.sub(r'[^\w\s]', '', normalized)
        
        # Удаляем множественные пробелы
        normalized = re.sub(r'\s+', ' ', normalized)
        
        return normalized.strip()
    
    def normalize_url(self, url: str) -> str:
        """
        Нормализует URL для сравнения: удаляет параметры запроса и фрагменты,
        приводит к единому виду.
        
        Args:
            url: Исходный URL
            
        Returns:
            Нормализованный URL
        """
        if not url:
            return ""
        
        # Приводим к нижнему регистру
        normalized = url.lower().strip()
        
        # Удаляем фрагменты (все что после #)
        if '#' in normalized:
            normalized = normalized.split('#')[0]
        
        # Удаляем параметры запроса (все что после ?), но только если это не важные параметры
        # Некоторые сайты используют параметры для отслеживания, но URL по сути тот же
        if '?' in normalized:
            base_url = normalized.split('?')[0]
            # Сохраняем только базовый URL без параметров
            normalized = base_url
        
        # Удаляем завершающий слэш
        normalized = normalized.rstrip('/')
        
        return normalized
    
    def is_news_published(self, title: str, url: str, source: str, description: str = '') -> bool:
        """
        Проверяет, была ли новость уже опубликована.
        Проверяет как точное совпадение (хеш), так и похожие заголовки/URL из разных категорий.
        
        Args:
            title: Заголовок новости
            url: URL новости
            source: Источник новости
            
        Returns:
            True, если новость уже опубликована, False в противном случае
        """
        # Сначала проверяем точное совпадение по хешу
        news_hash = self.generate_hash(title, url, source)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT id FROM news WHERE news_hash = ?', (news_hash,))
        result = cursor.fetchone()
        
        if result:
            conn.close()
            return True
        
        # ВАЖНО: Проверяем URL независимо от категории и источника
        # Если тот же URL уже был опубликован, это дубликат
        normalized_url = self.normalize_url(url)
        
        if normalized_url:
            # Получаем все URL за последние 30 дней и проверяем нормализованные версии
            cursor.execute('''
                SELECT url FROM news 
                WHERE datetime(published_at) > datetime('now', '-30 days')
            ''')
            
            published_urls = cursor.fetchall()
            
            for (published_url,) in published_urls:
                normalized_published = self.normalize_url(published_url)
                # Если нормализованные URL совпадают, это дубликат
                if normalized_url and normalized_published and normalized_url == normalized_published:
                    conn.close()
                    return True
        
        # Проверяем похожий контент независимо от категории
        content_hash = self.generate_content_hash(title, description)
        if content_hash:
            cursor.execute('SELECT id FROM news WHERE content_hash = ?', (content_hash,))
            result = cursor.fetchone()
            if result:
                conn.close()
                return True

        # Проверяем похожие заголовки независимо от категории
        # Нормализуем текущий заголовок
        normalized_title = self.normalize_title(title)
        
        # Получаем все опубликованные заголовки за последние 7 дней
        cursor.execute('''
            SELECT title FROM news 
            WHERE datetime(published_at) > datetime('now', '-7 days')
        ''')
        
        published_titles = cursor.fetchall()
        conn.close()
        
        # Проверяем, есть ли похожий заголовок
        for (published_title,) in published_titles:
            normalized_published = self.normalize_title(published_title)
            
            # Если нормализованные заголовки совпадают, это дубликат
            if normalized_title == normalized_published:
                return True
            
            # Дополнительная проверка: если заголовки очень похожи (более 90% совпадения)
            # Используем простое сравнение по словам
            current_words = set(normalized_title.split())
            published_words = set(normalized_published.split())
            
            if len(current_words) > 0 and len(published_words) > 0:
                # Вычисляем коэффициент совпадения
                common_words = current_words & published_words
                similarity = len(common_words) / max(len(current_words), len(published_words))
                
                # Если совпадение более 90%, считаем это дубликатом
                if similarity > 0.9:
                    return True
        
        return False
    
    def get_categories_by_url(self, url: str) -> List[str]:
        """
        Получает все категории, под которые подходит новость с данным URL.
        Это позволяет определить, если одна новость подходит под несколько категорий.
        
        Args:
            url: URL новости
            
        Returns:
            Список категорий для данного URL
        """
        normalized_url = self.normalize_url(url)
        if not normalized_url:
            return []
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Получаем все категории для похожих URL за последние 7 дней
        cursor.execute('''
            SELECT DISTINCT category FROM news 
            WHERE datetime(published_at) > datetime('now', '-7 days')
        ''')
        
        all_categories = [row[0] for row in cursor.fetchall()]
        
        # Проверяем, есть ли уже опубликованная новость с таким же URL
        cursor.execute('''
            SELECT DISTINCT category FROM news 
            WHERE datetime(published_at) > datetime('now', '-30 days')
        ''')
        
        published_categories = [row[0] for row in cursor.fetchall()]
        
        conn.close()
        
        # Возвращаем все категории, которые могут подходить
        return list(set(published_categories))
    
    def save_news(self, title: str, url: str, source: str, category: str, published_at: datetime,
                  description: str = '') -> int:
        """
        Сохраняет информацию о опубликованной новости в базе данных.
        
        Args:
            title: Заголовок новости
            url: URL новости
            source: Источник новости
            category: Категория новости
            published_at: Дата публикации новости в источнике
            
        Returns:
            ID сохраненной записи в базе данных
        """
        news_hash = self.generate_hash(title, url, source)
        content_hash = self.generate_content_hash(title, description)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO news (news_hash, title, source, url, category, content_hash, published_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (news_hash, title, source, url, category, content_hash, published_at))
            news_id = cursor.lastrowid
            conn.commit()
            return news_id
        except sqlite3.IntegrityError:
            # Если новость уже существует (по хешу), возвращаем её ID
            cursor.execute('SELECT id FROM news WHERE news_hash = ?', (news_hash,))
            result = cursor.fetchone()
            return result[0] if result else None
        finally:
            conn.close()
    
    def get_recent_news_by_category(self, category: str, hours: int = 24, limit: int = 5) -> List[Dict]:
        """
        Получает недавние новости по категории для создания дополняющих постов.
        
        Args:
            category: Категория новостей
            hours: Количество часов для выборки
            limit: Максимальное количество записей
            
        Returns:
            Список словарей с информацией о новостях
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Позволяет обращаться к колонкам по имени
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, title, url, source, category, published_at
            FROM news
            WHERE category = ? AND datetime(published_at) > datetime('now', '-' || ? || ' hours')
            ORDER BY published_at DESC
            LIMIT ?
        ''', (category, hours, limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def link_related_posts(self, original_post_id: int, related_post_id: int):
        """
        Связывает два поста как связанные (один дополняет другой).
        
        Args:
            original_post_id: ID оригинального поста
            related_post_id: ID связанного поста
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR IGNORE INTO related_posts (original_post_id, related_post_id)
            VALUES (?, ?)
        ''', (original_post_id, related_post_id))
        
        conn.commit()
        conn.close()
    
    def get_news_stats(self, hours: int | None = None) -> Dict:
        """
        Получает статистику по опубликованным новостям.
        
        Returns:
            Словарь со статистикой (общее количество, по категориям и т.д.)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if hours is None:
            cursor.execute('SELECT COUNT(*) FROM news')
            total = cursor.fetchone()[0]
            cursor.execute('''
                SELECT category, COUNT(*) as count
                FROM news
                GROUP BY category
            ''')
        else:
            safe_hours = max(int(hours), 1)
            cursor.execute('''
                SELECT COUNT(*) FROM news
                WHERE datetime(created_at) > datetime('now', '-' || ? || ' hours')
            ''', (safe_hours,))
            total = cursor.fetchone()[0]
            cursor.execute('''
                SELECT category, COUNT(*) as count
                FROM news
                WHERE datetime(created_at) > datetime('now', '-' || ? || ' hours')
                GROUP BY category
            ''', (safe_hours,))

        by_category = {row[0]: row[1] for row in cursor.fetchall()}
        
        conn.close()
        
        return {
            'total': total,
            'by_category': by_category
        }

    def _currency_snapshot_hash(self, rates: Dict) -> str:
        payload = (
            f"{rates['usd_rub']:.4f}|{rates['eur_rub']:.4f}|{rates['cny_rub']:.4f}|"
            f"{rates['rub_usd']:.6f}|{rates['btc_usd']:.2f}|{rates['btc_rub']:.2f}"
        )
        return hashlib.md5(payload.encode('utf-8')).hexdigest()

    def save_currency_snapshot(self, rates: Dict, post_type: str, published_at: datetime) -> bool:
        snapshot_hash = self._currency_snapshot_hash(rates)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute(
                '''
                INSERT INTO currency_snapshots (
                    snapshot_hash, post_type, usd_rub, eur_rub, cny_rub, rub_usd, btc_usd, btc_rub, published_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    snapshot_hash,
                    post_type,
                    float(rates['usd_rub']),
                    float(rates['eur_rub']),
                    float(rates['cny_rub']),
                    float(rates['rub_usd']),
                    float(rates['btc_usd']),
                    float(rates['btc_rub']),
                    published_at,
                )
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    def get_latest_currency_snapshot(self) -> Optional[Dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            '''
            SELECT post_type, usd_rub, eur_rub, cny_rub, rub_usd, btc_usd, btc_rub, published_at
            FROM currency_snapshots
            ORDER BY datetime(published_at) DESC
            LIMIT 1
            '''
        )

        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def has_currency_post_for_day(self, date_str: str, post_type: str) -> bool:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            '''
            SELECT 1 FROM currency_snapshots
            WHERE date(published_at) = ? AND post_type = ?
            LIMIT 1
            ''',
            (date_str, post_type)
        )

        exists = cursor.fetchone() is not None
        conn.close()
        return exists

