"""
Конфигурационный файл для телеграм-бота новостей.
Здесь хранятся все основные настройки бота и источники новостей.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
_BASE_DIR = Path(__file__).resolve().parent
# Загружаем только реальные файлы окружения, а не шаблоны с примерами
_ENV_FILENAMES = (".env",)
_ENV_DIRS = (_BASE_DIR, _BASE_DIR.parent, Path.cwd())
for env_dir in _ENV_DIRS:
    for env_name in _ENV_FILENAMES:
        load_dotenv(env_dir / env_name)

# Токен бота, полученный от @BotFather в Telegram
BOT_TOKEN = os.getenv('BOT_TOKEN', '')

# ID канала, куда будут публиковаться новости
# Формат: @channel_username или -1001234567890 (числовой ID)
CHANNEL_ID = os.getenv('CHANNEL_ID', '-1003531603514')

# Максимальная длина поста в символах
MAX_POST_LENGTH = 4500

# Интервал публикации постов в минутах
PUBLISH_INTERVAL_MINUTES = 60

# Минимальная задержка перед публикацией новости, чтобы сгруппировать похожие темы
PUBLISH_DELAY_MINUTES = 30

# Количество новостей для проверки за один раз
NEWS_CHECK_BATCH = 20

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
    {'name': 'Хабр Авто', 'url': 'https://habr.com/ru/rss/hub/cars/', 'category': 'cars'},
    {'name': 'Хабр Гаджеты', 'url': 'https://habr.com/ru/rss/hub/mobile/', 'category': 'tech'},
    {'name': 'CNews Технологии', 'url': 'https://www.cnews.ru/inc/rss/technology.xml', 'category': 'tech'},
    {'name': 'Hi-Tech Mail.ru Технологии', 'url': 'https://hi-tech.mail.ru/rss/technology/', 'category': 'tech'},
    {'name': 'Ferra.ru Гаджеты', 'url': 'https://www.ferra.ru/rss/gadgets/', 'category': 'tech'},
    {'name': 'Ferra.ru Авто', 'url': 'https://www.ferra.ru/rss/auto/', 'category': 'cars'},
    {'name': '3DNews Технологии', 'url': 'https://3dnews.ru/news/rss/', 'category': 'tech'},
    {'name': 'N+1 Технологии', 'url': 'https://nplus1.ru/rss/technology', 'category': 'tech'},
    {'name': 'Популярная Механика Технологии', 'url': 'https://www.popmech.ru/rss/technology/', 'category': 'tech'},
]

# Категории для балансировки контента
CATEGORIES = ['general', 'politics', 'world', 'tech', 'cars']

# Минимальный интервал между постами одной категории (в минутах)
MIN_INTERVAL_BETWEEN_SAME_CATEGORY = 30

# Ключевые слова для отсева локальной криминальной хроники
LOCAL_NOISE_CRIME_KEYWORDS = [
    'пья', 'пьян', 'алкогол', 'дебош', 'мелк', 'карманн', 'краж', 'вор', 'граб',
    'хулиган', 'свалил', 'угнал велосипед', 'украл велосипед'
]

# Маркеры локальных новостей уровня района/города
LOCAL_NEWS_MARKERS = [
    'в районе', 'на улице', 'местный житель', 'житель ', 'в городе', 'в посёлке', 'в поселке',
    'по области', 'районный', 'городской суд', 'в администрации города'
]

# Признаки «новостей-затычек» (малополезные/пустые материалы)
LOW_VALUE_NEWS_PATTERNS = [
    'без подробностей',
    'детали уточняются',
    'следите за обновлениями',
    'подробности позже',
    'стало известно',
    'шок',
    'срочно',
    'видео',
    'фото'
]

# Минимальная длина осмысленного описания новости
MIN_DESCRIPTION_LENGTH = 80

# Общие криминальные маркеры (фильтруем по умолчанию)
CRIME_CONTENT_KEYWORDS = [
    'убил', 'убий', 'зарезал', 'расстрел', 'стрельб', 'нападен', 'ограб', 'граб', 'краж',
    'вор', 'изнасил', 'мошенн', 'преступ', 'задержан', 'арестован', 'суд приговорил',
    'полиция', 'прокуратур', 'свoдка', 'поножовщина', 'драка', 'разбой', 'хулиган'
]

# Исключения: криминальные события глобального масштаба/террор, которые публикуем
ALLOWED_GLOBAL_CRIME_KEYWORDS = [
    'теракт', 'террорист', 'terror', 'isis', 'игил', 'аль-каида',
    'массовая стрельба', 'вооруженное нападение', 'чрезвычайное положение',
    'санкции', 'международн', 'оон', 'евросоюз', 'нато', 'глобальн',
    'энергетическ', 'кибератак', 'инфраструктур', 'авиасообщени', 'границ'
]
