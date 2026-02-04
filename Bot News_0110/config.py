"""
Конфигурационный файл для телеграм-бота новостей.
Здесь хранятся все основные настройки бота и источники новостей.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
_BASE_DIR = Path(__file__).resolve().parent
load_dotenv(_BASE_DIR / ".env")
load_dotenv(Path.cwd() / ".env")

# Токен бота, полученный от @BotFather в Telegram
BOT_TOKEN = os.getenv('BOT_TOKEN', '')

# ID канала, куда будут публиковаться новости
# Формат: @channel_username или -1001234567890 (числовой ID)
CHANNEL_ID = os.getenv('CHANNEL_ID', '')

# Максимальная длина поста в символах
MAX_POST_LENGTH = 4500

# Интервал публикации постов в минутах
PUBLISH_INTERVAL_MINUTES = 30

# Количество новостей для проверки за один раз
NEWS_CHECK_BATCH = 10

# База данных для хранения опубликованных новостей
DATABASE_PATH = 'news_bot.db'

# Дней хранения истории опубликованных новостей в базе
# После этого срока старые записи автоматически удаляются (экономия места)
DAYS_TO_KEEP_HISTORY = 30

# Список источников новостей (RSS фиды)
# Каждый источник содержит название и URL RSS фида
NEWS_SOURCES = [
    # Российские новостные источники
    {'name': 'РИА Новости', 'url': 'https://ria.ru/export/rss2/index.xml', 'category': 'general'},
    {'name': 'ТАСС', 'url': 'https://tass.ru/rss/v2.xml', 'category': 'general'},
    {'name': 'Интерфакс', 'url': 'https://www.interfax.ru/rss.asp', 'category': 'general'},
    {'name': 'Коммерсант', 'url': 'https://www.kommersant.ru/RSS/news.xml', 'category': 'politics'},
    {'name': 'РБК', 'url': 'https://www.rbc.ru/rssall.xml', 'category': 'general'},
    {'name': 'Ведомости', 'url': 'https://www.vedomosti.ru/rss/news', 'category': 'politics'},
    {'name': 'Лента.ру', 'url': 'https://lenta.ru/rss', 'category': 'general'},
    {'name': 'Газета.ру', 'url': 'https://www.gazeta.ru/export/rss/lenta.xml', 'category': 'general'},
    {'name': 'Российская Газета', 'url': 'https://rg.ru/xml/index.xml', 'category': 'general'},
    {'name': 'RT', 'url': 'https://russian.rt.com/rss', 'category': 'general'},
    {'name': 'RT Мир', 'url': 'https://russian.rt.com/rss/news', 'category': 'world'},
    {'name': 'RT Политика', 'url': 'https://russian.rt.com/rss/politics', 'category': 'politics'},
    {'name': 'RT Технологии', 'url': 'https://russian.rt.com/rss/tech', 'category': 'tech'},
    {'name': 'RT Наука', 'url': 'https://russian.rt.com/rss/science', 'category': 'science'},
    {'name': 'Регнум', 'url': 'https://regnum.ru/rss', 'category': 'general'},
    {'name': 'Новости Mail.ru', 'url': 'https://news.mail.ru/rss/all/', 'category': 'general'},
    {'name': 'Яндекс.Новости', 'url': 'https://news.yandex.ru/index.rss', 'category': 'general'},
    {'name': 'Meduza', 'url': 'https://meduza.io/rss/all', 'category': 'general'},
    
    # Международные источники (с переводом на русский или с русскоязычными версиями)
    {'name': 'BBC Russian', 'url': 'https://www.bbc.com/russian/index.xml', 'category': 'world'},
    {'name': 'BBC Technology', 'url': 'https://www.bbc.com/russian/science/index.xml', 'category': 'tech'},
    {'name': 'Deutsche Welle Russian', 'url': 'https://www.dw.com/ru/rss/rss-ru-all', 'category': 'world'},
    {'name': 'Voice of America Russian', 'url': 'https://www.golosameriki.com/api/zq$omekvi_1q', 'category': 'world'},
    
    # Технологии и гаджеты
    {'name': 'Хабр', 'url': 'https://habr.com/ru/rss/all/all/', 'category': 'tech'},
    {'name': 'iXBT.com', 'url': 'https://www.ixbt.com/export/news.rss', 'category': 'tech'},
    {'name': '3DNews', 'url': 'https://3dnews.ru/breaking/rss/', 'category': 'tech'},
    {'name': 'Ferra.ru', 'url': 'https://www.ferra.ru/rss/news/', 'category': 'tech'},
    {'name': 'CNews', 'url': 'https://www.cnews.ru/inc/rss/news.xml', 'category': 'tech'},
    {'name': 'Hi-Tech Mail.ru', 'url': 'https://hi-tech.mail.ru/rss/all/', 'category': 'tech'},
    {'name': 'TechCrunch (переводы)', 'url': 'https://habr.com/ru/rss/hub/techcrunch/', 'category': 'tech'},
    
    # Автомобили
    {'name': 'Авто.ру Новости', 'url': 'https://auto.ru/news.rss', 'category': 'cars'},
    {'name': 'Drive.ru', 'url': 'https://www.drive.ru/rss/news/', 'category': 'cars'},
    {'name': 'Автовести', 'url': 'https://www.autovesti.ru/rss', 'category': 'cars'},
    {'name': 'Колёса.ру', 'url': 'https://www.kolesa.ru/news/rss', 'category': 'cars'},
    {'name': 'Motor.ru', 'url': 'https://motor.ru/rss/news/', 'category': 'cars'},
    
    # Наука
    {'name': 'N+1', 'url': 'https://nplus1.ru/rss', 'category': 'science'},
    {'name': 'Элементы', 'url': 'https://elementy.ru/rss/news', 'category': 'science'},
    {'name': 'Indicator.ru', 'url': 'https://indicator.ru/rss', 'category': 'science'},
    {'name': 'Популярная Механика', 'url': 'https://www.popmech.ru/rss/', 'category': 'science'},
    {'name': 'Scientific American Russian', 'url': 'https://www.scientificamerican.com/rss/', 'category': 'science'},
    {'name': 'Science.ru', 'url': 'https://science.ru/rss', 'category': 'science'},
    
    # Политика
    {'name': 'Коммерсант Политика', 'url': 'https://www.kommersant.ru/RSS/section-politics.xml', 'category': 'politics'},
    {'name': 'Независимая газета', 'url': 'https://www.ng.ru/rss/', 'category': 'politics'},
    {'name': 'Известия', 'url': 'https://iz.ru/xml/rss/all.xml', 'category': 'politics'},
    {'name': 'Московский комсомолец', 'url': 'https://www.mk.ru/rss/index.xml', 'category': 'politics'},
    
    # Мировые новости
    {'name': 'ТАСС Мир', 'url': 'https://tass.ru/rss/v2.xml', 'category': 'world'},
    {'name': 'Российская Газета Мир', 'url': 'https://rg.ru/xml/index.xml', 'category': 'world'},
    
    # Дополнительные источники для разнообразия
    {'name': 'Регнум Политика', 'url': 'https://regnum.ru/rss/politics', 'category': 'politics'},
    {'name': 'Регнум Экономика', 'url': 'https://regnum.ru/rss/economics', 'category': 'general'},
    {'name': 'Регнум Наука', 'url': 'https://regnum.ru/rss/science', 'category': 'science'},
    {'name': 'Хабр Авто', 'url': 'https://habr.com/ru/rss/hub/cars/', 'category': 'cars'},
    {'name': 'Хабр Наука', 'url': 'https://habr.com/ru/rss/hub/science/', 'category': 'science'},
    {'name': 'Хабр Гаджеты', 'url': 'https://habr.com/ru/rss/hub/mobile/', 'category': 'tech'},
    {'name': 'CNews Технологии', 'url': 'https://www.cnews.ru/inc/rss/technology.xml', 'category': 'tech'},
    {'name': 'CNews Наука', 'url': 'https://www.cnews.ru/inc/rss/science.xml', 'category': 'science'},
    {'name': 'Hi-Tech Mail.ru Технологии', 'url': 'https://hi-tech.mail.ru/rss/technology/', 'category': 'tech'},
    {'name': 'Hi-Tech Mail.ru Наука', 'url': 'https://hi-tech.mail.ru/rss/science/', 'category': 'science'},
    {'name': 'Ferra.ru Гаджеты', 'url': 'https://www.ferra.ru/rss/gadgets/', 'category': 'tech'},
    {'name': 'Ferra.ru Авто', 'url': 'https://www.ferra.ru/rss/auto/', 'category': 'cars'},
    {'name': '3DNews Технологии', 'url': 'https://3dnews.ru/news/rss/', 'category': 'tech'},
    {'name': 'N+1 Технологии', 'url': 'https://nplus1.ru/rss/technology', 'category': 'tech'},
    {'name': 'Популярная Механика Технологии', 'url': 'https://www.popmech.ru/rss/technology/', 'category': 'tech'},
]

# Категории для балансировки контента
CATEGORIES = ['general', 'politics', 'world', 'tech', 'cars', 'science']

# Минимальный интервал между постами одной категории (в минутах)
MIN_INTERVAL_BETWEEN_SAME_CATEGORY = 30
