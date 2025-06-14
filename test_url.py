import urllib.parse
import requests
from requests.exceptions import RequestException
from bs4 import BeautifulSoup
import re
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import time

def fetch_original_url(google_url):
    """Extrahiert die Original-URL aus einer Google News Weiterleitungs-URL."""
    print(f"\nVerarbeite URL: {google_url}")
    try:
        # Schritt 1: Prüfe URL-Parameter
        parsed = urllib.parse.urlparse(google_url)
        print(f"Parsed URL: {parsed}")
        query_params = urllib.parse.parse_qs(parsed.query)
        print(f"Query-Parameter: {query_params}")
        if 'url' in query_params:
            original_url = query_params['url'][0]
            print(f"URL-Parameter gefunden: {original_url}")
            return original_url

        # Schritt 2: Selenium für JavaScript-Weiterleitungen
        print("Kein 'url'-Parameter gefunden, starte Selenium für JavaScript-Weiterleitungen...")
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
        driver = webdriver.Chrome(options=chrome_options)
        try:
            driver.get(google_url)
            time.sleep(2)  # Kürzere Wartezeit für GitHub Actions
            final_url = driver.current_url
            print(f"Selenium finale URL: {final_url}")
            if final_url != google_url and not final_url.startswith('https://news.google.com'):
                print(f"Original-URL gefunden: {final_url}")
                return final_url
            else:
                print(f"Selenium hat keine Original-URL gefunden, URL ist: {final_url}")
        finally:
            driver.quit()

        # Schritt 3: Fallback mit requests
        print("Keine Weiterleitung via Selenium, lade Seite mit GET und parse mit BeautifulSoup...")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://news.google.com/"
        }
        session = requests.Session()
        response = session.get(google_url, headers=headers, allow_redirects=False, timeout=10)
        print(f"Status-Code (ohne Redirects): {response.status_code}")
        if response.status_code in (301, 302, 303):
            redirect_url = response.headers.get('Location')
            if redirect_url and not redirect_url.startswith('https://news.google.com'):
                print(f"Redirect-URL gefunden: {redirect_url}")
                return redirect_url
            else:
                print(f"Redirect-URL ist Google News: {redirect_url}")
        response = session.get(google_url, headers=headers, allow_redirects=True, timeout=10)
        print(f"Status-Code (mit Redirects): {response.status_code}")
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            meta_refresh = soup.find('meta', attrs={'http-equiv': re.compile('refresh', re.I)})
            if meta_refresh and 'content' in meta_refresh.attrs:
                content = meta_refresh['content']
                match = re.search(r'url=(https?://[^\s"]+)', content)
                if match:
                    original_url = match.group(1)
                    print(f"Meta-Refresh-URL gefunden: {original_url}")
                    return original_url
                else:
                    print(f"Meta-Refresh gefunden, aber keine URL: {content}")
            else:
                print("Kein Meta-Refresh-Tag gefunden")
            redirect_link = soup.find('a', class_='VDXfz')
            if redirect_link:
                original_url = redirect_link['href']
                print(f"Weiterleitungs-URL (VDXfz) gefunden: {original_url}")
                return original_url
            all_links = soup.find_all('a', href=True)
            if all_links:
                print(f"Gefundene <a>-Links: {[link['href'] for link in all_links]}")
                for link in all_links:
                    href = link['href']
                    if not href.startswith(('https://news.google.com', 'https://www.google.com', '/')):
                        print(f"Weiterleitungs-URL (Heuristik) gefunden: {href}")
                        return href
            else:
                print("Keine <a>-Links gefunden")
            scripts = soup.find_all('script')
            for script in scripts:
                if script.string:
                    match = re.search(r'(?:window\.location\.href|window\.location)\s*=\s*[\'"](https?://[^\s\'"]+)[\'"]', script.string)
                    if match:
                        original_url = match.group(1)
                        print(f"JavaScript-Weiterleitungs-URL gefunden: {original_url}")
                        return original_url
            print("Keine JavaScript-Weiterleitung gefunden")
            print("Erste 2000 Zeichen des HTML:")
            print(str(soup)[:2000])
        else:
            print(f"Seite konnte nicht geladen werden, Status-Code: {response.status_code}")
        print(f"Fallback: Verwende response.url: {response.url}")
        return response.url
    except Exception as e:
        print(f"Fehler beim Abrufen der Original-URL für {google_url}: {e}")
        return google_url

# Liste von Test-URLs
test_urls = [
    "https://news.google.com/rss/articles/CBMingFBVV95cUxQeC1wcG5ZXzNCVlgwY1N2U2ZMWHFpZDJDUXdBaEc3TUdBdjdiQkx3aXpoTkhHcFNpRndKVk5RNDlzOG4yRnFrNUdpVWlwMWh6dXJsYk1xOWRKOXUxdEtNT25GR2M5QUNqRzQzS0N3U2c4Nkc4aU0tbUVabTZPTlFFVW91aGFOMkpQbzI0VmJnNnBTczVISnA0N3l0Sk9jUQ?oc=5&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/articles/CBMi5wFBVV95cUxOWEEyempoOFZMaVNOeWFxdDViSnFjM0hxUU5telRHR3hCV3JyTUNtY2FGTHVZczVNR3BmU3BRRkVsMld5T1ZEZUNCVFRhcktGZmp5Q25zZm8zQzhqeG5EV20zMFpHUGdLUno1SW53ZWowVnZCVWJlakFGbXZiLXNHVzNZSnZ1NEs1Y1UtWFVEV2o5U2o3djFJQ1M2QVZPek1pNERVVjNJbmZkZlRsYk5Zd0hCdmQ0ZlJ2clVJWGEtZFB0dHhxN1c4WXNKV0w1WFNDX3pqeXMteW1wRWdqTlYyTkV2dk45akk?oc=5",
    "https://news.google.com/rss/articles/CBMizwFBVV95cUxPaUduUVBqZ1hsa0s3Y2FRTjZzR3Zua2JHTG5CZjNRQkxLc2hzWHBYbWJHLWt0b0ZUM1Z3Qk90R0VwZU9tdFZXWjdTNjMtM3BJdU1ad0d2eERvM29RejFiUWw4Tzk0enpMVTUwQlo0UnZXR29EVTljSlR1LU1UUmF1QUdZai1DX1BBZ2NOMlc0ZGJfMHR4dnE4Yk5pRnFncU9RVzFYTEo2Wlh5WmJHa3dhUEBzR05pNGFNQWxEeWJmWXhNX3JXTWhSaklUYkVZNDQ?oc=5",
    "https://news.google.com/rss/articles/CBMi1AFBVV95cUxNWFZfRWJoN0ptaHc5bkN4dnlBbEM0WWdMdTVhQklhTmtQOGY5WkRua1YydFNxMkR5RnVjTkRYNk0yaU9LdXg3WVpVbUtfdWRSWVZEUDA0eGtaS0xvVE9NX19LUVNSQXpjVFRfUDEwam5HaGdGOFJPWXYtSHo0enBWZUhEU2FRTVlMV3FfajlzaTRFQTRwclAyamYyLUFsdmtZWmxlZzg2ZDRENlFXbXFiVDdOZXo3cDE1OGRUMG54eWpqeW05THNQaHduN0JtYzVda0tqSw?oc=5"
]

# Teste jede URL
for url in test_urls:
    result = fetch_original_url(url)
    print(f"Original-URL: {result}")
