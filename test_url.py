import urllib.parse
import requests
from requests.exceptions import RequestException
from bs4 import BeautifulSoup
import re

def fetch_original_url(google_url):
    """Extrahiert die Original-URL aus einer Google News Weiterleitungs-URL."""
    print(f"\nVerarbeite URL: {google_url}")
    try:
        parsed = urllib.parse.urlparse(google_url)
        print(f"Parsed URL: {parsed}")
        query_params = urllib.parse.parse_qs(parsed.query)
        print(f"Query-Parameter: {query_params}")
        if 'url' in query_params:
            original_url = query_params['url'][0]
            print(f"URL-Parameter gefunden: {original_url}")
            return original_url
        print("Kein 'url'-Parameter gefunden, lade Seite mit GET und parse mit BeautifulSoup...")
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
        response = requests.get(google_url, headers=headers, allow_redirects=True, timeout=10)
        print(f"Status-Code: {response.status_code}")
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            # Suche nach <meta http-equiv="refresh">
            meta_refresh = soup.find('meta', attrs={'http-equiv': re.compile('refresh', re.I)})
            if meta_refresh and 'content' in meta_refresh.attrs:
                content = meta_refresh['content']
                # Extrahiere URL aus content="0;url=https://..."
                match = re.search(r'url=(https?://[^\s"]+)', content)
                if match:
                    original_url = match.group(1)
                    print(f"Meta-Refresh-URL gefunden: {original_url}")
                    return original_url
                else:
                    print(f"Meta-Refresh gefunden, aber keine URL: {content}")
            else:
                print("Kein Meta-Refresh-Tag gefunden")
            # Suche nach <a class="VDXfz">
            redirect_link = soup.find('a', class_='VDXfz')
            if redirect_link:
                original_url = redirect_link['href']
                print(f"Weiterleitungs-URL (VDXfz) gefunden: {original_url}")
                return original_url
            # Suche nach allen <a>-Tags
            all_links = soup.find_all('a', href=True)
            if all_links:
                print(f"Gefundene <a>-Links: {[link['href'] for link in all_links]}")
                # Heuristik: Wähle den ersten Link, der nicht zu Google führt
                for link in all_links:
                    href = link['href']
                    if not href.startswith(('https://news.google.com', 'https://www.google.com', '/')):
                        print(f"Weiterleitungs-URL (Heuristik) gefunden: {href}")
                        return href
            else:
                print("Keine <a>-Links gefunden")
            # Debugging: Gib die ersten 1000 Zeichen des HTML aus
            print("Erste 1000 Zeichen des HTML:")
            print(str(soup)[:1000])
        else:
            print(f"Seite konnte nicht geladen werden, Status-Code: {response.status_code}")
        print(f"Fallback: Verwende response.url: {response.url}")
        return response.url
    except RequestException as e:
        print(f"Fehler beim Abrufen der Original-URL für {google_url}: {e}")
