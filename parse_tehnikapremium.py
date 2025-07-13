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

async def parse_tehnikapremium(original_title: str, search_query: str) -> List[Dict]:
    """
    Парсинг tehnikapremium.ru с улучшенным поиском по обоим запросам и возвратом
    наиболее релевантных уникальных позиций.
    """
    url = "https://tehnikapremium.ru/catalog/bytovaya_khimiya_miele/?SHOWALL_2=1"
    async with aiohttp.ClientSession() as session:
        html = await fetch(session, url)
        if not html:
            logger.error("Не удалось получить HTML-контент с tehnikapremium.ru")
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        products = soup.select('div.catalog_item:not(.hidden)')
        
        if not products:
            logger.warning("No products found on tehnikapremium.ru")
            return []
            
        clean_original_title = remove_miele(normalize_text(original_title))
        clean_search_query = remove_miele(normalize_text(search_query))
        
        search_terms = []
        if clean_original_title:
            search_terms.append(re.escape(clean_original_title))
        if clean_search_query and clean_search_query != clean_original_title:
            search_terms.append(re.escape(clean_search_query))
        
        if not search_terms:
            logger.warning("Оба поисковых запроса пусты для tehnikapremium.ru после нормализации.")
            return []
        
        regex_pattern = re.compile(
            r'\b(' + '|'.join(search_terms) + r')\b', 
            re.IGNORECASE
        )
        
        logger.info(f"Используемое регулярное выражение для TehnikaPremium: {regex_pattern.pattern}")

        found_products = [] 
        seen_links = set() # Множество для отслеживания уникальных ссылок
        
        for product in products:
            title_elem = product.select_one('div.item-title')
            link_elem = product.select_one('a.dark_link') # Предполагается, что ссылка находится здесь
            
            if not title_elem or not link_elem:
                continue

            title = title_elem.get_text(strip=True)
            link_relative = link_elem.get('href')
            if not link_relative:
                continue
            full_link = f"https://tehnikapremium.ru{link_relative}"
            
            # Проверяем уникальность ссылки
            if full_link in seen_links:
                logger.debug(f"Пропускаем дубликат ссылки на TehnikaPremium: {full_link}")
                continue

            # Парсинг артикула
            art_elem = product.select_one('div.article_block')
            article = art_elem.get_text(strip=True).replace('Артикул:', '').strip() if art_elem else ""
            
            # Парсинг цены (обновлено)
            price_elem = product.select_one('span.price_value')
            if not price_elem:
                continue
                
            price_text_raw = price_elem.get_text(strip=True)
            price_cleaned = re.sub(r'[^\d,\.]', '', price_text_raw) # Надежное извлечение числа
            
            price_match = re.search(r'(\d+[\.,]?\d*)', price_cleaned)
            if not price_match:
                continue
                
            try:
                price = float(price_match.group(1).replace(',', '.'))
            except ValueError:
                logger.error(f"Price conversion error on TehnikaPremium: {price_match.group(1)}")
                continue
            
            # Вычисление релевантности (аналогично другим парсерам)
            normalized_title = remove_miele(normalize_text(title))
            normalized_article = normalize_text(article)

            relevance_score = float('inf') # Начинаем с очень большого значения
            
            # Приоритет совпадению по артикулу
            if clean_search_query and clean_search_query == normalized_article:
                relevance_score = min(relevance_score, 0)
            elif clean_original_title and clean_original_title == normalized_article: # original_title тоже может быть артикулом
                relevance_score = min(relevance_score, 0.5)

            # Совпадение по названию (точное)
            if clean_original_title and clean_original_title == normalized_title:
                relevance_score = min(relevance_score, 1)
            elif clean_search_query and clean_search_query == normalized_title:
                relevance_score = min(relevance_score, 2)
            
            # Совпадение как подстроки
            if clean_original_title and clean_original_title in normalized_title:
                relevance_score = min(relevance_score, 3)
            elif clean_search_query and clean_search_query in normalized_title:
                relevance_score = min(relevance_score, 4)

            # Все слова из original_title присутствуют
            if clean_original_title:
                original_title_words = clean_original_title.split()
                if all(word in normalized_title for word in original_title_words):
                    relevance_score = min(relevance_score, 5)
            
            # Все слова из search_query присутствуют
            if clean_search_query:
                search_query_words = clean_search_query.split()
                if all(word in normalized_title for word in search_query_words):
                    relevance_score = min(relevance_score, 6)

            if relevance_score != float('inf'):
                # Добавляем длину названия как множитель для дополнительной сортировки
                relevance_score += len(normalized_title) * 0.01 
                
                found_products.append({
                    'score': relevance_score,
                    'title': title,
                    'link': full_link,
                    'price': price,
                    'article': article
                })
                seen_links.add(full_link)
                logger.info(f"Найден потенциально релевантный товар на TehnikaPremium: '{title}' ({article}) - {price} RUB (Score: {relevance_score})")

        # Сортируем найденные товары по оценке релевантности
        found_products.sort(key=lambda x: x['score'])
        
        # Возвращаем до 3х лучших
        return found_products[:3]

# Пример использования
async def main():
    results = await parse_tehnikapremium(
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