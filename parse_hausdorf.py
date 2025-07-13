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
    return full_title.strip()

# Сделал функцию не-асинхронной, так как она не выполняет I/O операции
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

async def parse_hausdorf(original_title: str, search_query: str) -> List[Dict]:
    """
    Парсинг hausdorf.ru с поиском по обоим запросам (original_title и search_query)
    и возвратом наиболее релевантных уникальных позиций.

    Args:
        original_title (str): Исходное, более полное название товара.
        search_query (str): Сокращенный или основной поисковый запрос.

    Returns:
        List[Dict]: Список из 3 наиболее релевантных уникальных объектов, каждый со словарями:
                    {'title': str, 'link': str, 'price': float}.
    """
    base_url = "https://www.hausdorf.ru/catalog/aksessuary/miele/"
    async with aiohttp.ClientSession() as session:
        all_pages_html = []
        
        # Получаем первую страницу для определения пагинации и сразу обрабатываем ее
        html = await fetch(session, base_url)
        if not html:
            logger.error("Не удалось получить HTML-контент с hausdorf.ru")
            return []
        
        all_pages_html.append(html) # Добавляем HTML первой страницы
        
        soup = BeautifulSoup(html, 'html.parser')
        pages_to_fetch = set() # Используем set для уникальных URL пагинации
        
        # Находим все ссылки пагинации
        pagination = soup.select('div.pagination__list a')
        for page_link in pagination:
            href = page_link.get('href')
            if href and 'PAGEN' in href:
                full_url = f"https://www.hausdorf.ru{href}"
                pages_to_fetch.add(full_url) # Добавляем в set
        
        # Загружаем остальные страницы пагинации
        for page_url in sorted(list(pages_to_fetch)): # Сортируем для детерминированности, но не обязательно
            html = await fetch(session, page_url)
            if html:
                all_pages_html.append(html)
        
        # Обрабатываем оба поисковых запроса
        clean_original_title = remove_miele(normalize_text(original_title))
        clean_search_query = remove_miele(normalize_text(search_query))
        
        search_terms = []
        if clean_original_title:
            search_terms.append(re.escape(clean_original_title))
        if clean_search_query and clean_search_query != clean_original_title:
            search_terms.append(re.escape(clean_search_query))
        
        if not search_terms:
            logger.warning("Оба поисковых запроса пусты после нормализации.")
            return []
        
        regex_pattern = re.compile(
            r'\b(' + '|'.join(search_terms) + r')\b', 
            re.IGNORECASE
        )
        
        logger.info(f"Используемое регулярное выражение для Hausdorf: {regex_pattern.pattern}")

        found_products = [] 
        seen_links = set() # Множество для отслеживания уникальных ссылок
        
        # Теперь перебираем HTML всех загруженных страниц
        for page_html in all_pages_html:
            soup = BeautifulSoup(page_html, 'html.parser')
            products = soup.select('div.catalog-thumb')
            
            for product in products:
                title_elem = product.select_one('a.catalog-thumb__titlelink')
                link_elem = product.select_one('a.catalog-thumb__titlelink') # Ссылка на товар обычно в этом же элементе
                
                if not title_elem or not link_elem:
                    continue
                    
                product_title = extract_title_text(title_elem)
                product_link_relative = link_elem.get('href')
                if not product_link_relative:
                    continue

                product_link_full = f"https://www.hausdorf.ru{product_link_relative}"
                
                # Проверяем уникальность ссылки
                if product_link_full in seen_links:
                    logger.debug(f"Пропускаем дубликат ссылки: {product_link_full}")
                    continue
                
                clean_product_title = normalize_text(remove_miele(product_title))

                if not clean_product_title:
                    continue
                
                # Ищем совпадение с помощью объединенного регулярного выражения
                if regex_pattern.search(clean_product_title):
                    price = extract_price(product) # Теперь вызываем не-асинхронную функцию
                    if price is not None: # Проверяем на None, так как price может быть 0
                        # Оценка релевантности (чем меньше, тем лучше)
                        relevance_score = len(clean_product_title) 
                        
                        if clean_original_title and clean_original_title not in clean_product_title:
                            relevance_score += 50
                        if clean_search_query and clean_search_query not in clean_product_title:
                            relevance_score += 25 
                        
                        found_products.append((relevance_score, product_title, product_link_full, price))
                        seen_links.add(product_link_full) # Добавляем ссылку в множество
                        logger.info(f"Найден потенциально релевантный товар: '{product_title}' (Цена: {price}, Ссылка: {product_link_full})")
        
        # Сортируем найденные товары по оценке релевантности
        found_products.sort(key=lambda x: x[0])
        
        results = []
        for _, title, link, price in found_products[:3]: # Берем до 3х самых релевантных
            results.append({
                'title': title,
                'link': link,
                'price': price
            })
        
        if not results:
            logger.warning(f"Товары по запросам '{original_title}' и '{search_query}' не найдены на Hausdorf.ru.")
            
        return results


# Пример использования
async def main():
    # Тестируем сложный запрос
    results = await parse_hausdorf(
        original_title="Miele Комплект мешков-пылесборников GN XL HyClean Pure", # Более полное название
        search_query="Miele GN HyClean Pure" # Сокращенный или альтернативный запрос
    )
    
    if results:
        print("\nНайденные товары на Hausdorf:")
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