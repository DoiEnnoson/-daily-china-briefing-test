#!/usr/bin/env python3
"""
TEST FÜR GITHUB ACTIONS - Google News URL Auflösung
====================================================
Dieses Script testet die URL-Auflösung in DEINER GitHub Actions Umgebung.
"""

import requests
import feedparser
from concurrent.futures import ThreadPoolExecutor, as_completed

print("="*80)
print("TESTE GOOGLE NEWS URL-AUFLÖSUNG IN GITHUB ACTIONS")
print("="*80)

# ============================================================================
# SCHRITT 1: Teste ob Google News erreichbar ist
# ============================================================================
print("\n[1] Teste Verbindung zu news.google.com...")
try:
    response = requests.get("https://news.google.com", timeout=5)
    print(f"✅ Verbindung erfolgreich! Status: {response.status_code}")
except Exception as e:
    print(f"❌ Verbindung fehlgeschlagen: {str(e)}")
    print("⚠️ Ohne Netzwerkzugriff kann URL-Auflösung nicht funktionieren!")
    exit(1)

# ============================================================================
# SCHRITT 2: Hole echte Google News Links aus deinem Feed
# ============================================================================
print("\n[2] Hole Google News Feed...")
feed_url = "https://news.google.com/rss/search?q=china+when:1d&hl=de&gl=DE&ceid=DE:de"

try:
    feed = feedparser.parse(feed_url)
    print(f"✅ Feed erfolgreich geladen: {len(feed.entries)} Einträge")
    
    # Nimm die ersten 3 Links
    test_links = []
    for entry in feed.entries[:3]:
        link = entry.get("link", "")
        title = entry.get("title", "")
        if "news.google.com" in link:
            test_links.append((title, link))
            print(f"  → {title[:60]}...")
            print(f"    Link: {link[:80]}...")
    
    if not test_links:
        print("❌ Keine Google News Links gefunden!")
        exit(1)
        
except Exception as e:
    print(f"❌ Fehler beim Laden des Feeds: {str(e)}")
    exit(1)

# ============================================================================
# SCHRITT 3: Teste URL-Auflösung mit verschiedenen Methoden
# ============================================================================

def method1_head_request(url, timeout=5):
    """Methode 1: HEAD Request"""
    try:
        response = requests.head(
            url,
            allow_redirects=True,
            timeout=timeout,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        if "news.google.com" not in response.url:
            return response.url
    except:
        pass
    return None

def method2_get_request(url, timeout=5):
    """Methode 2: GET Request"""
    try:
        response = requests.get(
            url,
            allow_redirects=True,
            timeout=timeout,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        if "news.google.com" not in response.url:
            return response.url
    except:
        pass
    return None

def method3_session(url, timeout=5):
    """Methode 3: Session mit Cookies"""
    try:
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0'})
        response = session.get(url, allow_redirects=True, timeout=timeout)
        if "news.google.com" not in response.url:
            return response.url
    except:
        pass
    return None

print("\n[3] Teste URL-Auflösung mit verschiedenen Methoden...")

methods = [
    ("HEAD Request", method1_head_request),
    ("GET Request", method2_get_request),
    ("Session", method3_session)
]

results = {}

for title, link in test_links[:1]:  # Teste nur den ersten Link
    print(f"\n{'='*80}")
    print(f"Teste: {title[:60]}...")
    print(f"Original: {link[:80]}...")
    print(f"{'='*80}")
    
    for method_name, method_func in methods:
        print(f"\n  Teste {method_name}...", end=" ")
        resolved = method_func(link)
        
        if resolved:
            print(f"✅ ERFOLG!")
            print(f"  Aufgelöst zu: {resolved[:100]}...")
            results[method_name] = resolved
        else:
            print(f"❌ Fehlgeschlagen")

# ============================================================================
# SCHRITT 4: Teste parallele Verarbeitung (wie im Hauptscript)
# ============================================================================
print(f"\n{'='*80}")
print("[4] Teste parallele Verarbeitung (wie im echten Script)...")
print(f"{'='*80}")

def resolve_url_parallel(url, timeout=3):
    """Die Funktion die im Hauptscript verwendet wird"""
    if "news.google.com" not in url:
        return url
    
    try:
        response = requests.get(
            url,
            allow_redirects=True,
            timeout=timeout,
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        if "news.google.com" not in response.url:
            return response.url
    except:
        pass
    return url

# Teste mit allen 3 Links parallel
all_links = [link for title, link in test_links]

print(f"\nAuflösen von {len(all_links)} Links parallel...")

with ThreadPoolExecutor(max_workers=10) as executor:
    future_to_url = {executor.submit(resolve_url_parallel, url): url for url in all_links}
    
    resolved_results = {}
    for future in as_completed(future_to_url):
        original = future_to_url[future]
        try:
            resolved = future.result()
            resolved_results[original] = resolved
        except Exception as e:
            resolved_results[original] = original

successful = 0
for i, ((title, original), resolved) in enumerate(zip(test_links, [resolved_results[link] for title, link in test_links]), 1):
    if original != resolved and "news.google.com" not in resolved:
        successful += 1
        status = "✅"
    else:
        status = "❌"
    
    print(f"\n{status} Link {i}:")
    print(f"  Titel: {title[:80]}")
    print(f"  Original: {original[:80]}...")
    print(f"  Resolved: {resolved[:80]}...")

# ============================================================================
# FAZIT
# ============================================================================
print(f"\n{'='*80}")
print("FAZIT")
print(f"{'='*80}")

if successful > 0:
    print(f"✅ ERFOLG! {successful}/{len(test_links)} URLs wurden aufgelöst!")
    print("\nDie URL-Auflösung FUNKTIONIERT in deiner GitHub Actions Umgebung!")
    print("→ Du kannst jetzt dein briefing.py Script anpassen")
    print("→ Verwende die GET-Request Methode aus diesem Test")
else:
    print("❌ FEHLGESCHLAGEN! Keine URLs konnten aufgelöst werden")
    print("\nMögliche Gründe:")
    print("1. Google blockiert programmatischen Zugriff")
    print("2. Netzwerk-Einschränkungen in GitHub Actions")
    print("3. Google News URLs funktionieren anders als erwartet")
    print("\n→ Wir brauchen eine alternative Lösung!")

print(f"\n{'='*80}")
