import urllib.parse
import requests
from requests.exceptions import RequestException
from bs4 import BeautifulSoup

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
            # Suche nach dem Weiterleitungslink (oft ein <a> Tag mit der Original-URL)
            redirect_link = soup.find('a', href=True)
            if redirect_link:
                original_url = redirect_link['href']
                print(f"Weiterleitungs-URL gefunden: {original_url}")
                return original_url
            else:
                print("Kein Weiterleitungslink gefunden in der Seite")
        else:
            print(f"Seite konnte nicht geladen werden, Status-Code: {response.status_code}")
        print(f"Fallback: Verwende response.url: {response.url}")
        return response.url
    except RequestException as e:
        print(f"Fehler beim Abrufen der Original-URL für {google_url}: {e}")
        return google_url

# Liste von Test-URLs (inkl. URLs aus deinem Briefing)
test_urls = [
    "https://news.google.com/rss/articles/CBMingFBVV95cUxQeC1wcG5ZXzNCVlgwY1N2U2ZMWHFpZDJDUXdBaEc3TUdBdjdiQkx3aXpoTkhHcFNpRndKVk5RNDlzOG4yRnFrNUdpVWlwMWh6dXJsYk1xOWRKOXUxdEtNT25GR2M5QUNqRzQzS0N3U2c4Nkc4aU0tbUVabTZPTlFFVW91aGFOMkpQbzI0VmJnNnBTczVISnA0N3l0Sk9jUQ?oc=5&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/articles/CBMi5wFBVV95cUxOWEEyempoOFZMaVNOeWFxdDViSnFjM0hxUU5telRHR3hCV3JyTUNtY2FGTHVZczVNR3BmU3BRRkVsMld5T1ZEZUNCVFRhcktGZmp5Q25zZm8zQzhqeG5EV20zMFpHUGdLUno1SW53ZWowVnZCVWJlakFGbXZiLXNHVzNZSnZ1NEs1Y1UtWFVEV2o5U2o3djFJQ1M2QVZPek1pNERVVjNJbmZkZlRsYk5Zd0hCdmQ0ZlJ2clVJWGEtZFB0dHhxN1c4WXNKV0w1WFNDX3pqeXMteW1wRWdqTlYyTkV2dk45akk?oc=5",
    "https://news.google.com/rss/articles/CBMizwFBVV95cUxPaUduUVBqZ1hsa0s3Y2FRTjZzR3Zua2JHTG5CZjNRQkxLc2hzWHBYbWJHLWt0b0ZUM1Z3Qk90R0VwZU9tdFZXWjdTNjMtM3BJdU1ad0d2eERvM29RejFiUWw4Tzk0enpMVTUwQlo0UnZXR29EVTljSlR1LU1UUmF1QUdZai1DX1BBZ2NOMlc0ZGJfMHR4dnE4Yk5pRnFncU9RVzFYTEo2Wlh5WmJHa3dhUEJzR05pNGFNQWxEeWJmWXhNX3JXTWhSaklUYkVZNDQ?oc=5",
    "https://news.google.com/rss/articles/CBMixAFBVV95cUxOTDNhdXZFUkJTY2Y0YkFDVWp6ZVhkVEFVNmhkb2cxWDZQRERSbEFXVDduYkhudldPbjdrX1I4d2EtdWRUMDBOakI1eW1aYUdpbDNzcjh5Nm8xenhBODZkNTc0TFZxUjlDUnpDWjlveDJTN19CdnhldlNJSXZxZkMtQW00a2NRQVBNMmh1VnZuRTdYT3JIZ1hWcDFuS0tqUkFMbGI3NlIxU1pJa282LXVyUGZVMmZKWXQydG1aREh0VHRweFVP?oc=5"
]

# Teste jede URL
for url in test_urls:
    result = fetch_original_url(url)
    print(f"Original-URL: {result}")
