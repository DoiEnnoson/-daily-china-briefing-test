import urllib.parse
import requests
from requests.exceptions import RequestException

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
        print("Kein 'url'-Parameter gefunden, folge Weiterleitung mit GET...")
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
        response = requests.get(google_url, headers=headers, allow_redirects=True, timeout=10)
        print(f"Weitergeleitete URL: {response.url}")
        return response.url
    except RequestException as e:
        print(f"Fehler beim Abrufen der Original-URL für {google_url}: {e}")
        return google_url

# Liste von Test-URLs
test_urls = [
    "https://news.google.com/rss/articles/CBMingFBVV95cUxQeC1wcG5ZXzNCVlgwY1N2U2ZMWHFpZDJDUXdBaEc3TUdBdjdiQkx3aXpoTkhHcFNpRndKVk5RNDlzOG4yRnFrNUdpVWlwMWh6dXJsYk1xOWRKOXUxdEtNT25GR2M5QUNqRzQzS0N3U2c4Nkc4aU0tbUVabTZPTlFFVW91aGFOMkpQbzI0VmJnNnBTczVISnA0N3l0Sk9jUQ?oc=5&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/articles/CBMi1gFBVV95cUxPZk1Ya0N2a0tYZkR3c3hPMTFTNFFrUm5WcDVJSG5fV0d3c2lRS1R6R0h5eVRRZm9VN3J5ZFhNNVZuMTRoRkhFNDVvbW5fM1p1R0tIa0dJSjFVaG1UcG5qMk5qYTFsTDRpZTVyblZhY0c3c0YxT2FudVBOc2J2R3o4Y1p3b1lMQ2dLZm9nM2N2a0ZhV1h0NklNaXJ3aDJlQXAyZTB4b1JqN2pna3p1?oc=5",
    "https://news.google.com/rss/articles/CBMiswFBVV95cUxPZzVOTVRUcV9fU0V2N0ZVNk9hZF9uV2M2ZmF6Y0p4U05IQnJ3R3J2b0h1Q2M3eF9fZDJqWFJ0U2x4T1ZCYzJ3M0x1U3U0eV9Uc2x1a2k2b1F3T2x3eEd2RTRrWVRnNGZhWURqelVBRjM1bG1NcmxUc0d4NDRhUXpJNDM2a0t4RllPU0VJZ01uWk9zR1J0SkJaY1M2b3hWdE1yNjd3?oc=5"
    "https://news.google.com/rss/articles/CBMiqgFBVV95cUxONGFWT2lMU3ZFSWdZRWFnazlaRVRVVENuRmx1N0JrWmlTSVBLMzJvS3VzVTZNNUQ2cENhWnNERDA0UHFCQ2ZOdXRmSzZ2X0dPSTlCOGpIOWd0ZzVrLWNieDJlXy1hLW90Y2VJRWs4RXhSR0VHd2t1UzhPR2kyTmNDNnBkNldXQkt0aFlmODUxZDNrMzZLRW51bmp0UEVDY0J4TmRUazc1YkNTdw?oc=5"
"https://news.google.com/rss/articles/CBMi1wFBVV95cUxPLU1oQlkxLTEyRXJ3VjFETVZ4VkMxWEdTWnhaeWQySk1SRDctbGIwZW9RYTNkRUlXbHg3UG9QSVdZeE5zbVl1cnJ5bFl2R1F5T0RhVzk3dzBQdXBzeS1ONGg0WFVaclpCdUNZcWRUNlZXTGk4c0paRkQyNmdXUUp5MzFuM2RxcVdDR2RQcFNRRW12RjRBNmg1UEg1NzV6eEtHSkY3NnhPSC1vRmR0VW5ueXB5aHdZT0FEd01YWE9VNVFKZ25fM3ZsaFlpcmJQdlMxWWxBTndNVQ?oc=5"
"https://news.google.com/rss/articles/CBMi5wFBVV95cUxOWEEyempoOFZMaVNOeWFxdDViSnFjM0hxUU5telRHR3hCV3JyTUNtY2FGTHVZczVNR3BmU3BRRkVsMld5T1ZEZUNCVFRhcktGZmp5Q25zZm8zQzhqeG5EV20zMFpHUGdLUno1SW53ZWowVnZCVWJlakFGbXZiLXNHVzNZSnZ1NEs1Y1UtWFVEV2o5U2o3djFJQ1M2QVZPek1pNERVVjNJbmZkZlRsYk5Zd0hCdmQ0ZlJ2clVJWGEtZFB0dHhxN1c4WXNKV0w1WFNDX3pqeXMteW1wRWdqTlYyTkV2dk45akk?oc=5"
]

# Teste jede URL
for url in test_urls:
    result = fetch_original_url(url)
    print(f"Original-URL: {result}")import urllib.parse
import requests
from requests.exceptions import RequestException

def fetch_original_url(google_url):
    """Extrahiert die Original-URL aus einer Google News Weiterleitungs-URL."""
    print(f"Verarbeite URL: {google_url}")
    try:
        # Parse die Google URL
        parsed = urllib.parse.urlparse(google_url)
        print(f"Parsed URL: {parsed}")
        query_params = urllib.parse.parse_qs(parsed.query)
        print(f"Query-Parameter: {query_params}")
        if 'url' in query_params:
            original_url = query_params['url'][0]
            print(f"URL-Parameter gefunden: {original_url}")
            return original_url
        print("Kein 'url'-Parameter gefunden, folge Weiterleitung mit GET...")
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
        response = requests.get(google_url, headers=headers, allow_redirects=True, timeout=10)
        print(f"Weitergeleitete URL: {response.url}")
        return response.url
    except RequestException as e:
        print(f"Fehler beim Abrufen der Original-URL für {google_url}: {e}")
        return google_url

test_url = "https://news.google.com/rss/articles/CBMingFBVV95cUxQeC1wcG5ZXzNCVlgwY1N2U2ZMWHFpZDJDUXdBaEc3TUdBdjdiQkx3aXpoTkhHcFNpRndKVk5RNDlzOG4yRnFrNUdpVWlwMWh6dXJsYk1xOWRKOXUxdEtNT25GR2M5QUNqRzQzS0N3U2c4Nkc4aU0tbUVabTZPTlFFVW91aGFOMkpQbzI0VmJnNnBTczVISnA0N3l0Sk9jUQ?oc=5&hl=en-US&gl=US&ceid=US:en"
result = fetch_original_url(test_url)
print(f"Original-URL: {result}")
