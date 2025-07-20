import re
import logging
import aiohttp
from typing import Dict, List
from bs4 import BeautifulSoup
import urllib.parse

# Предполагаем, что utils.py с fetch, normalize_text, remove_miele существует
from utils import extract_price_from_text, fetch, normalize_text, remove_miele

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def parse_tehnikapremium(search_query: str) -> List[Dict]:
    """
    Парсинг tehnikapremium.ru с использованием поисковой строки,
    возвращает наиболее релевантные уникальные позиции, основываясь только на search_query.
    """
    
    # search_query используется напрямую для URL
    encoded_query = urllib.parse.quote_plus(search_query) 
    url = f"https://tehnikapremium.ru/catalog/?q={encoded_query}&s=Найти"

    async with aiohttp.ClientSession() as session:
        html = await fetch(session, url)
        if not html:
            logger.error(f"Не удалось получить HTML-контент с {url}")
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        products = soup.select('div.catalog_item:not(.hidden)') 
        
        if not products:
            logger.warning(f"Товары не найдены на {url}")
            return []
            
        # Теперь только один нормализованный запрос
        clean_search_query = remove_miele(normalize_text(search_query))
        
        search_terms = []
        if clean_search_query:
            search_terms.append(re.escape(clean_search_query))
        
        if not search_terms:
            logger.warning("Поисковый запрос пуст для tehnikapremium.ru после нормализации.")
            return []
        
        regex_pattern = re.compile(
            r'\b(' + '|'.join(search_terms) + r')\b', 
            re.IGNORECASE
        )
        
        logger.info(f"Используемое регулярное выражение для TehnikaPremium: {regex_pattern.pattern}")

        found_products = [] 
        seen_links = set() 
        
        for product in products:
            title_elem = product.select_one('div.item-title')
            link_elem = product.select_one('a.dark_link') 
            
            if not title_elem or not link_elem:
                continue

            title = title_elem.get_text(strip=True)
            link_relative = link_elem.get('href')
            if not link_relative:
                continue
            full_link = urllib.parse.urljoin("https://tehnikapremium.ru/", link_relative)
            
            if full_link in seen_links:
                logger.debug(f"Пропускаем дубликат ссылки на TehnikaPremium: {full_link}")
                continue

            art_elem = product.select_one('div.article_block')
            article = art_elem.get_text(strip=True).replace('Артикул:', '').strip() if art_elem else ""
            
            price_elem = product.select_one('span.price_value')
            if not price_elem:
                continue
                
            price = extract_price_from_text(price_elem.get_text(strip=True))
            if price is None:
                continue
            
            normalized_title = remove_miele(normalize_text(title))
            normalized_article = normalize_text(article)

            relevance_score = float('inf') 
            
            # Приоритет совпадения артикула с search_query
            if clean_search_query == normalized_article:
                relevance_score = min(relevance_score, 0)
            
            # Приоритет точного совпадения названия с search_query
            elif clean_search_query == normalized_title:
                relevance_score = min(relevance_score, 1)
            
            # Приоритет вхождения запроса в название
            elif clean_search_query in normalized_title:
                relevance_score = min(relevance_score, 2)

            # Приоритет совпадения всех слов запроса в названии
            else: # если предыдущие не сработали
                search_query_words = clean_search_query.split()
                if all(word in normalized_title for word in search_query_words):
                    relevance_score = min(relevance_score, 3)
            
            if relevance_score != float('inf'):
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

        found_products.sort(key=lambda x: x['score'])
        
        return found_products[:3]