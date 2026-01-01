#!/usr/bin/env python3
"""
OPTION E: Google News HTML Scraping
====================================
Versucht Original-URLs direkt aus dem Google News HTML zu extrahieren.
"""

import requests
from bs4 import BeautifulSoup
import json
import re

print("="*80)
print("TESTE: HTML SCRAPING VON GOOGLE NEWS")
print("="*80)

# ============================================================================
# METHODE 1: Google News Webseite scrapen
# ============================================================================
print("\n[METHODE 1] Google News Webseite scrapen...")

url = "https://news.google.com/search?q=china&hl=en-US&gl=US&ceid=US:en"

try:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    }
    
    response = requests.get(url, headers=headers, timeout=10)
    print(f"Status: {response.status_code}")
    
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Speichere HTML für Analyse
    with open('google_news_debug.html', 'w', encoding='utf-8') as f:
        f.write(response.text)
    print("✅ HTML gespeichert in: google_news_debug.html")
    
    # Suche nach verschiedenen Mustern
    print("\nSuche nach URL-Mustern...")
    
    # 1. data-* Attribute
    data_urls = soup.find_all(attrs={'data-url': True})
    if data_urls:
        print(f"✅ Gefunden: {len(data_urls)} data-url Attribute")
        for i, elem in enumerate(data_urls[:3], 1):
            print(f"  {i}. {elem.get('data-url')[:100]}")
    
    # 2. Direkte <a> Links (nicht news.google.com)
    all_links = soup.find_all('a', href=True)
    external_links = [a['href'] for a in all_links if 'http' in a['href'] and 'google.com' not in a['href']]
    if external_links:
        print(f"✅ Gefunden: {len(external_links)} externe Links")
        for i, link in enumerate(external_links[:3], 1):
            print(f"  {i}. {link[:100]}")
    
    # 3. JSON-LD oder JavaScript Daten
    scripts = soup.find_all('script')
    print(f"\nAnalysiere {len(scripts)} Script-Tags...")
    
    for script in scripts:
        if script.string:
            # Suche nach URL-ähnlichen Strings
            urls = re.findall(r'https?://[^\s"\'<>]+', script.string)
            if urls:
                # Filter nur nicht-Google URLs
                non_google = [u for u in urls if 'google.com' not in u and len(u) > 30]
                if non_google:
                    print(f"✅ Gefunden in Script: {len(non_google)} URLs")
                    for i, u in enumerate(non_google[:3], 1):
                        print(f"  {i}. {u[:100]}")
                    break
    
    # 4. Spezielle Klassen/IDs die Google verwendet
    article_elements = soup.find_all(['article', 'div'], class_=re.compile(r'article|story|item', re.I))
    print(f"\nGefunden: {len(article_elements)} Artikel-Elemente")
    
    if article_elements:
        print("Analysiere erstes Artikel-Element:")
        first = article_elements[0]
        print(f"  Tag: {first.name}")
        print(f"  Classes: {first.get('class')}")
        print(f"  Attributes: {list(first.attrs.keys())}")
        
        # Suche nach Links im Artikel
        article_links = first.find_all('a', href=True)
        if article_links:
            print(f"  Links im Artikel: {len(article_links)}")
            for i, link in enumerate(article_links[:3], 1):
                href = link['href']
                text = link.get_text(strip=True)[:50]
                print(f"    {i}. {text}")
                print(f"       → {href[:100]}")

except Exception as e:
    print(f"❌ Fehler: {str(e)}")

# ============================================================================
# METHODE 2: RSS Feed Item einzeln abrufen und HTML parsen
# ============================================================================
print("\n" + "="*80)
print("[METHODE 2] RSS-Link als Webseite laden und HTML parsen...")
print("="*80)

# Nutze einen der Links aus deinem Test
test_rss_url = "https://news.google.com/rss/articles/CBMirgFBVV95cUxPTWZsUzJMWTRCVkdRNWVtQ0lpdEhheHNmdFRoX0JqMXQ4akFiTmVzbGhvS0ZRd3pCbm1fM2F4azljcGlDc0pJUU1CMTNlQkNlNjlEV0xPdTlVTlk0bUFXdG5SdnRPeDNkb2VLRkhlcURRSG4wQmdWVGdPZHpfcVVYTGcycEkybnlDOW9YbGhDQ05YaDl6azk5T0lsQzA2WF9SN3NZeE5NMQ?oc=5"

try:
    response = requests.get(test_rss_url, headers=headers, timeout=10, allow_redirects=False)
    print(f"Status (ohne Redirects): {response.status_code}")
    
    if response.status_code in [301, 302, 303, 307, 308]:
        location = response.headers.get('Location')
        print(f"✅ Redirect Location Header: {location}")
    
    # Versuche mit Redirects
    response = requests.get(test_rss_url, headers=headers, timeout=10, allow_redirects=True)
    print(f"Status (mit Redirects): {response.status_code}")
    print(f"Final URL: {response.url}")
    
    if "news.google.com" not in response.url:
        print(f"✅ ERFOLG! Aufgelöst zu: {response.url}")
    else:
        # Parse HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Suche nach Canonical URL
        canonical = soup.find('link', rel='canonical')
        if canonical:
            print(f"✅ Canonical URL: {canonical.get('href')}")
        
        # Suche nach Meta Refresh
        meta_refresh = soup.find('meta', attrs={'http-equiv': 'refresh'})
        if meta_refresh:
            content = meta_refresh.get('content', '')
            url_match = re.search(r'url=(.+)', content, re.I)
            if url_match:
                print(f"✅ Meta Refresh URL: {url_match.group(1)}")
        
        # Suche nach JavaScript Redirect
        js_redirect = re.search(r'window\.location\s*=\s*["\']([^"\']+)["\']', response.text)
        if js_redirect:
            print(f"✅ JS Redirect: {js_redirect.group(1)}")
        
        # Suche nach data-n-a-sg Attribut (Google News spezifisch)
        data_links = soup.find_all(attrs={'data-n-a-sg': True})
        if data_links:
            print(f"✅ Gefunden: data-n-a-sg Attribute")
            for elem in data_links[:3]:
                print(f"  → {elem.get('data-n-a-sg')[:100]}")

except Exception as e:
    print(f"❌ Fehler: {str(e)}")

# ============================================================================
# METHODE 3: Google News RSS als JSON API
# ============================================================================
print("\n" + "="*80)
print("[METHODE 3] Prüfe ob Google News eine versteckte JSON API hat...")
print("="*80)

# Manchmal haben Webseiten JSON Endpoints
json_urls = [
    "https://news.google.com/rss/search?q=china&hl=en&gl=US&ceid=US:en&output=json",
    "https://news.google.com/api/search?q=china",
]

for test_url in json_urls:
    try:
        response = requests.get(test_url, headers=headers, timeout=5)
        if response.status_code == 200:
            try:
                data = response.json()
                print(f"✅ JSON Response von: {test_url}")
                print(f"   Keys: {list(data.keys())}")
            except:
                print(f"❌ Keine JSON-Antwort von: {test_url}")
    except:
        pass

# ============================================================================
# FAZIT
# ============================================================================
print("\n" + "="*80)
print("FAZIT")
print("="*80)
print("""
Prüfe die Ausgaben oben:

Wenn ✅ irgendwo auftaucht:
→ Wir haben einen Weg gefunden Original-URLs zu extrahieren!
→ Das kann ins Hauptscript integriert werden

Wenn nur ❌:
→ Google News blockiert ALLE programmatischen Zugriffe
→ Wir brauchen Plan F (siehe unten)

PLAN F (falls alles fehlschlägt):
1. Paid Service nutzen (z.B. ScraperAPI, Bright Data)
2. Eigenen Headless Browser hosten (Selenium/Playwright in Docker)
3. Newsletter komplett umbauen auf andere Quellen
""")

print("\n📁 Prüfe auch: google_news_debug.html (gespeichert)")
print("   Dort siehst du das rohe HTML von Google News")
