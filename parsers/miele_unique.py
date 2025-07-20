import aiohttp
import re
from typing import Optional, List, Dict
import logging
from bs4 import BeautifulSoup, Tag
import urllib.parse # <-- Добавляем импорт для URL-кодирования

# Предполагаем, что utils.py с fetch, normalize_text, remove_miele существует
from utils import fetch, normalize_text, remove_miele, extract_price_from_text

# Настройка логирования
logger = logging.getLogger(__name__) # Использует корневой логгер, если он настроен в config.py или main.py

def extract_title_text(title_elem: Tag) -> str:
    """Извлекает полный текст из элемента названия, включая вложенные теги"""
    parts = []
    for child in title_elem.children:
        if isinstance(child, str):
            parts.append(child.strip())
        elif child.name:
            parts.append(child.get_text(strip=True))
    
    full_title = " ".join(part for part in parts if part)
    return full_title.strip() # Добавил strip() для окончательной очистки

async def parse_miele_unique(original_title: str, search_query: str) -> List[Dict]:
    """
    Парсинг miele-unique.ru с использованием поисковой строки
    и возвратом наиболее релевантных уникальных позиций,
    используя как original_title, так и search_query для релевантности.

    Args:
        original_title (str): Исходное, более полное название товара.
        search_query (str): Сокращенный или основной поисковый запрос (ввод пользователя).

    Returns:
        List[Dict]: Список из 3 наиболее релевантных уникальных объектов, каждый со словарями:
                    {'title': str, 'link': str, 'price': float}.
    """
    # URL-кодируем поисковый запрос
    encoded_query = urllib.parse.quote_plus(search_query) 
    # Обновленный базовый URL для поиска
    search_url = f"https://miele-unique.ru/search/?q={encoded_query}&r=Y"

    async with aiohttp.ClientSession() as session:
        logger.info(f"Запрос к Miele-Unique: {search_url}")
        html = await fetch(session, search_url)
        if not html:
            logger.error(f"Не удалось получить HTML-контент с Miele-Unique по URL: {search_url}")
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        
        # Обрабатываем оба поисковых запроса
        clean_original_title = remove_miele(normalize_text(original_title))
        clean_search_query = remove_miele(normalize_text(search_query))
        
        # Создаем список частей для регулярного выражения
        search_terms = []
        if clean_original_title:
            search_terms.append(re.escape(clean_original_title))
        if clean_search_query and clean_search_query != clean_original_title:
            search_terms.append(re.escape(clean_search_query))
        
        if not search_terms:
            logger.warning("Оба поисковых запроса пусты после нормализации для Miele-Unique.")
            return []
        
        # Объединяем части в одно регулярное выражение с ИЛИ
        regex_pattern = re.compile(
            r'\b(' + '|'.join(search_terms) + r')\b', 
            re.IGNORECASE
        )
        
        logger.info(f"Используемое регулярное выражение для Miele-Unique: {regex_pattern.pattern}")

        # Селектор для товаров на странице поиска (может потребоваться корректировка)
        # Судя по предоставленному коду, 'div.item.product' может быть универсальным.
        products = soup.select('div.item.product')
        found_products = [] 
        seen_links = set() 
        
        for product in products:
            title_elem = product.select_one('a.name') # Часто название и ссылка в одном элементе на miele-unique
            link_elem = product.select_one('a.name') 
            
            if not title_elem or not link_elem:
                continue
                
            product_title = extract_title_text(title_elem) # Используем extract_title_text для извлечения полного названия
            product_link_relative = link_elem.get('href') # Используем .get('href') вместо прямого ['href'] для безопасности
            
            if not product_link_relative:
                continue
            
            # Убедитесь, что ссылка абсолютная
            product_link_full = urllib.parse.urljoin("https://miele-unique.ru", product_link_relative)
            
            # Проверяем уникальность ссылки
            if product_link_full in seen_links:
                logger.debug(f"Пропускаем дубликат ссылки на Miele-Unique: {product_link_full}")
                continue
            
            clean_product_title = remove_miele(normalize_text(product_title))
            
            if not clean_product_title:
                continue
            
            # Проверяем совпадение с помощью объединенного регулярного выражения
            if regex_pattern.search(clean_product_title):
                price_elem = product.select_one('a.price') # Селектор для цены
                if price_elem:
                    price_text_raw = price_elem.get_text(strip=True)
                    price = extract_price_from_text(price_text_raw) # <-- Используем extract_price_from_text из utils
                    
                    if price is not None:
                        relevance_score = float('inf') 
                        
                        # Приоритет точного совпадения названия
                        if clean_original_title and clean_original_title == clean_product_title:
                            relevance_score = min(relevance_score, 0)
                        elif clean_search_query and clean_search_query == clean_product_title:
                            relevance_score = min(relevance_score, 1)
                        
                        # Приоритет вхождения запроса в название
                        if clean_original_title and clean_original_title in clean_product_title:
                            relevance_score = min(relevance_score, 2)
                        elif clean_search_query and clean_search_query in clean_product_title:
                            relevance_score = min(relevance_score, 3)

                        # Приоритет совпадения всех слов запроса в названии
                        if clean_original_title:
                            original_title_words = clean_original_title.split()
                            if all(word in clean_product_title for word in original_title_words):
                                relevance_score = min(relevance_score, 4)
                        
                        if clean_search_query:
                            search_query_words = clean_search_query.split()
                            if all(word in clean_product_title for word in search_query_words):
                                relevance_score = min(relevance_score, 5)

                        if relevance_score != float('inf'): # Убеждаемся, что какой-то критерий релевантности сработал
                            # Добавляем длину названия как мелкий фактор для сортировки
                            relevance_score += len(clean_product_title) * 0.01 
                            
                            found_products.append((relevance_score, product_title, product_link_full, price))
                            seen_links.add(product_link_full)
                            logger.info(f"Найден потенциально релевантный товар на Miele-Unique: '{product_title}' (Цена: {price}, Ссылка: {product_link_full}, Score: {relevance_score})")
        
        # Сортируем найденные товары по оценке релевантности
        found_products.sort(key=lambda x: x[0])
        
        results = []
        for _, title, link, price in found_products[:3]: # Берем до 3х самых релевантных
            results.append({
                'title': title,
                'link': link,
                'price': price
            })
            logger.info(f"Выбран релевантный товар: '{title}' (Ссылка: {link}, Цена: {price})") # Изменил лог, чтобы не дублировать
        
        if not results:
            logger.warning(f"Товары по запросам '{original_title}' и '{search_query}' не найдены на Miele-Unique.ru.")
            
        return results
