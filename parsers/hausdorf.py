import aiohttp
import re
from typing import Optional, List, Dict
import logging
from bs4 import BeautifulSoup, Tag
import urllib.parse

# Предполагаем, что utils.py с fetch, normalize_text, remove_miele существует
from utils import fetch, normalize_text, remove_miele

# Настройка логирования (можете использовать логгер из config.py, если он там настроен глобально)
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
    return full_title.strip()

def extract_price(product_elem: Tag) -> Optional[float]:
    """
    Извлекает цену из элемента товара, используя более надежный парсинг.
    Ожидается price_elem: <div class="catalog-thumb__price">...</div>
    """
    price_elem = product_elem.select_one('div.catalog-thumb__price')
    if price_elem:
        price_text_raw = price_elem.get_text(strip=True)
        # Удаляем все символы, кроме цифр, точек и запятых
        price_cleaned = re.sub(r'[^\d,\.]', '', price_text_raw)
        
        price_match = re.search(r'(\d+[\.,]?\d*)', price_cleaned)
        if price_match:
            try:
                # Заменяем запятые на точки для корректного преобразования во float
                return float(price_match.group(1).replace(',', '.'))
            except ValueError:
                logger.error(f"Ошибка преобразования цены: {price_match.group(1)} из текста '{price_text_raw}'")
    return None

# ВОССТАНАВЛИВАЕМ original_title в сигнатуре функции
async def parse_hausdorf(original_title: str, search_query: str) -> List[Dict]:
    """
    Парсинг hausdorf.ru с использованием поисковой строки
    и возвратом наиболее релевантных уникальных позиций,
    используя как original_title, так и search_query для релевантности.

    Args:
        original_title (str): Исходное, более полное название товара.
        search_query (str): Сокращенный или основной поисковый запрос (ввод пользователя).

    Returns:
        List[Dict]: Список из 3 наиболее релевантных уникальных объектов, каждый со словарями:
                    {'title': str, 'link': str, 'price': float}.
    """
    # Для поискового URL используем search_query (пользовательский ввод),
    # так как он может быть артикулом или более конкретным запросом.
    encoded_query = urllib.parse.quote_plus(search_query) 
    search_url = f"https://www.hausdorf.ru/search/?q={encoded_query}"

    async with aiohttp.ClientSession() as session:
        logger.info(f"Запрос к Hausdorf: {search_url}")
        html = await fetch(session, search_url)
        if not html:
            logger.error(f"Не удалось получить HTML-контент с Hausdorf по URL: {search_url}")
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        
        # Готовим поисковые регулярные выражения для обоих запросов
        clean_original_title = remove_miele(normalize_text(original_title))
        clean_search_query = remove_miele(normalize_text(search_query))
        
        search_terms = []
        if clean_original_title:
            search_terms.append(re.escape(clean_original_title))
        if clean_search_query and clean_search_query != clean_original_title:
            search_terms.append(re.escape(clean_search_query))
        
        if not search_terms:
            logger.warning("Оба поисковых запроса пусты после нормализации для Hausdorf.")
            return []
        
        regex_pattern = re.compile(
            r'\b(' + '|'.join(search_terms) + r')\b', 
            re.IGNORECASE
        )
        
        logger.info(f"Используемое регулярное выражение для Hausdorf: {regex_pattern.pattern}")

        found_products = [] 
        seen_links = set() 
        
        products = soup.select('div.catalog-thumb')
        
        for product in products:
            title_elem = product.select_one('a.catalog-thumb__titlelink')
            link_elem = product.select_one('a.catalog-thumb__titlelink')
            
            if not title_elem or not link_elem:
                continue
                
            product_title = extract_title_text(title_elem)
            product_link_relative = link_elem.get('href')
            if not product_link_relative:
                continue

            product_link_full = urllib.parse.urljoin("https://www.hausdorf.ru/", product_link_relative)
            
            if product_link_full in seen_links:
                logger.debug(f"Пропускаем дубликат ссылки на Hausdorf: {product_link_full}")
                continue
            
            clean_product_title = normalize_text(remove_miele(product_title))

            if not clean_product_title:
                continue
            
            # Проверяем, соответствует ли товар хотя бы одному из запросов
            if regex_pattern.search(clean_product_title):
                price = extract_price(product)
                if price is not None:
                    # Оценка релевантности (чем меньше, тем лучше)
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
                        logger.info(f"Найден потенциально релевантный товар на Hausdorf: '{product_title}' (Цена: {price}, Ссылка: {product_link_full}, Score: {relevance_score})")
        
        # Сортируем найденные товары по оценке релевантности
        found_products.sort(key=lambda x: x[0])
        
        results = []
        for _, title, link, price in found_products[:3]:
            results.append({
                'title': title,
                'link': link,
                'price': price
            })
        
        if not results:
            logger.warning(f"Товары по запросам '{original_title}' и '{search_query}' не найдены на Hausdorf.ru.")
            
        return results
