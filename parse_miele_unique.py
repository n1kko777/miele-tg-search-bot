import aiohttp
import re
from typing import Optional, List, Dict
import logging
from bs4 import BeautifulSoup, Tag

# Предполагаем, что utils.py с fetch, normalize_text, remove_miele существует
from utils import fetch, normalize_text, remove_miele

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def extract_title_text(title_elem: Tag) -> str:
    """Извлекает полный текст из элемента названия, включая вложенные теги"""
    parts = []
    for child in title_elem.children:
        if isinstance(child, str):
            parts.append(child.strip())
        elif child.name:
            parts.append(child.get_text(strip=True))
    
    full_title = " ".join(part for part in parts if part)
    return full_title

async def parse_miele_unique(original_title: str, search_query: str) -> List[Dict]:
    """
    Парсинг miele-unique.ru с поиском по регулярному выражению по обоим запросам 
    (original_title и search_query) и возвратом наиболее релевантных уникальных позиций.

    Args:
        original_title (str): Исходное название товара.
        search_query (str): Основной поисковый запрос для поиска на сайте.

    Returns:
        List[Dict]: Список из 3 наиболее релевантных уникальных объектов, каждый со словарями:
                    {'title': str, 'link': str, 'price': float}.
    """
    url = "https://miele-unique.ru/catalog/aksessuary_i_bytovaya_khimiya/moyushchie_i_chistyashchie_sredstva/?SORT_TO=90"
    async with aiohttp.ClientSession() as session:
        html = await fetch(session, url)
        if not html:
            logger.error("Не удалось получить HTML-контент с miele-unique.ru")
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
            logger.warning("Оба поисковых запроса пусты после нормализации.")
            return []
        
        # Объединяем части в одно регулярное выражение с ИЛИ
        regex_pattern = re.compile(
            r'\b(' + '|'.join(search_terms) + r')\b', 
            re.IGNORECASE
        )
        
        logger.info(f"Используемое регулярное выражение: {regex_pattern.pattern}")

        products = soup.select('div.item.product')
        found_products = [] # Будем хранить кортежи (релевантность_score, product_title, product_link, product_price)
        seen_links = set() # Множество для отслеживания уникальных ссылок
        
        for product in products:
            title_elem = product.select_one('span.middle')
            link_elem = product.select_one('a.name') 
            
            if not title_elem or not link_elem:
                continue
                
            product_title = extract_title_text(title_elem)
            product_link_relative = link_elem['href']
            product_link_full = "https://miele-unique.ru" + product_link_relative
            
            # Проверяем уникальность ссылки
            if product_link_full in seen_links:
                logger.debug(f"Пропускаем дубликат ссылки: {product_link_full}")
                continue
            
            clean_product_title = remove_miele(normalize_text(product_title))
            
            if not clean_product_title:
                continue
            
            # Проверяем совпадение с помощью объединенного регулярного выражения
            if regex_pattern.search(clean_product_title):
                price_elem = product.select_one('a.price')
                if price_elem:
                    price_text_raw = price_elem.get_text(strip=True)
                    price_cleaned = re.sub(r'[^\d,\.]', '', price_text_raw)
                    
                    price_match = re.search(r'(\d+[\.,]?\d*)', price_cleaned)
                    if price_match:
                        try:
                            price = float(price_match.group(1).replace(',', '.'))
                            
                            relevance_score = len(clean_product_title) 
                            
                            if clean_original_title and clean_original_title not in clean_product_title:
                                relevance_score += 50
                            if clean_search_query and clean_search_query not in clean_product_title:
                                relevance_score += 25 
                            
                            found_products.append((relevance_score, product_title, product_link_full, price))
                            seen_links.add(product_link_full) # Добавляем ссылку в множество
                        except ValueError:
                            logger.error(f"Ошибка преобразования цены: {price_match.group(1)} из текста '{price_text_raw}'")
        
        # Сортируем найденные товары по оценке релевантности
        found_products.sort(key=lambda x: x[0])
        
        results = []
        for _, title, link, price in found_products[:3]: # Берем до 3х самых релевантных
            results.append({
                'title': title,
                'link': link,
                'price': price
            })
            logger.info(f"Найден релевантный товар: '{title}' (Ссылка: {link}, Цена: {price})")
        
        if not results:
            logger.warning(f"Товары по запросам '{original_title}' и '{search_query}' не найдены.")
            
        return results

# Пример использования
async def main():
    results = await parse_miele_unique(
        original_title="Картридж для очистки от накипи CM7",
        search_query="Картридж CM7"
    )
    
    if results:
        print("\nНайденные товары:")
        for item in results:
            print(f"  Название: {item['title']}")
            print(f"  Ссылка: {item['link']}")
            print(f"  Цена: {item['price']}")
            print("-" * 20)
    else:
        print("Товары не найдены или произошла ошибка.")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())