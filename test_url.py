import urllib.parse
import requests
from requests.exceptions import RequestException

def fetch_original_url(google_url):
    """Extrahiert die Original-URL aus einer Google News Weiterleitungs-URL."""
    try:
        parsed = urllib.parse.urlparse(google_url)
        query_params = urllib.parse.parse_qs(parsed.query)
        if 'url' in query_params:
            return query_params['url'][0]
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.head(google_url, headers=headers, allow_redirects=True, timeout=5)
        return response.url
    except RequestException as e:
        print(f"Fehler beim Abrufen der Original-URL für {google_url}: {e}")
        return google_url

# Test-URL
test_url = "https://news.google.com/rss/articles/CBMingFBVV95cUxQeC1wcG5ZXzNCVlgwY1N2U2ZMWHFpZDJDUXdBaEc3TUdBdjdiQkx3aXpoTkhHcFNpRndKVk5RNDlzOG4yRnFrNUdpVWlwMWh6dXJsYk1xOWRKOXUxdEtNT25GR2M5QUNqRzQzS0N3U2c4Nkc4aU0tbUVabTZPTlFFVW91aGFOMkpQbzI0VmJnNnBTczVISnA0N3l0Sk9jUQ?oc=5&hl=en-US&gl=US&ceid=US:en"
result = fetch_original_url(test_url)
print(f"Original-URL: {result}")
