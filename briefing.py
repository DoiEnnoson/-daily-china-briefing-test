#!/usr/bin/env python3
"""
QUICK TEST SCRIPT - Google News URL Resolution
===============================================
Teste ob die URL-Auflösung funktioniert BEVOR du dein Hauptscript änderst.
"""

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

def resolve_google_news_url(google_url, timeout=3, max_retries=2):
    """Löst eine Google News URL zur Original-URL auf."""
    if "news.google.com" not in google_url:
        return google_url
    
    for attempt in range(max_retries):
        try:
            response = requests.head(
                google_url,
                allow_redirects=True,
                timeout=timeout,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            )
            
            final_url = response.url
            
            if "news.google.com" not in final_url:
                print(f"✅ SUCCESS: Resolved to {final_url[:100]}...")
                return final_url
            
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"❌ FAILED after {max_retries} attempts: {str(e)[:50]}")
            continue
    
    return google_url


def resolve_multiple_urls(url_list, max_workers=10, timeout=3):
    """Löst mehrere URLs parallel auf."""
    results = {}
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_url = {
            executor.submit(resolve_google_news_url, url, timeout): url 
            for url in url_list
        }
        
        for future in as_completed(future_to_url):
            original_url = future_to_url[future]
            try:
                resolved_url = future.result()
                results[original_url] = resolved_url
            except Exception as e:
                print(f"ERROR: {str(e)}")
                results[original_url] = original_url
    
    return results


# === TESTS ===
if __name__ == "__main__":
    print("=" * 80)
    print("TEST 1: Einzelne URL auflösen")
    print("=" * 80)
    
    # Test-URL (dein Beispiel aus der Anfrage)
    test_url = "https://news.google.com/rss/articles/CBMilwFBVV95cUxOTlh2UU83TVNGWG8wd2VGc2FmS0wtX0ZDWFJKS25GM0R6NS00cFVxV0xwYUNrT2R1OENGY09sZmxmSURpOUZKaDQ1R0hxWVdpdEpQR2g1d0hUc21BNlFIbDd1VlRQR3pCZFpDY0lPUUhpM0kyRktIZzZvcmx6a09QWmdhdnZEbG4wYUFid0IxVy1rR2lEYWR30gGcAUFVX3lxTE5qaUFQV1ljVWdrek9SaW5rUlFxZ0NfSmktWEpES25LY2dhUmtkVzJrTHRmblFNbkExOVdlT2ZVejdReW1PVjlud0h5SFBlblAtZ2gxUlQ0aFdURkxYWXpRQWtyOW5oZ1BYZmNEZ2hzLTJXYWQ4MUlIQkcxZjRrVXRQeG5nQTQ1NDl3RXVpa2FRTXJ0MUpNMG0yaEtiaQ?oc=5"
    
    print(f"\nOriginal URL:\n{test_url}\n")
    
    resolved = resolve_google_news_url(test_url)
    
    print(f"\nResolved URL:\n{resolved}\n")
    
    if "news.google.com" not in resolved:
        print("✅ TEST PASSED: URL wurde erfolgreich aufgelöst!")
    else:
        print("❌ TEST FAILED: URL konnte nicht aufgelöst werden")
    
    print("\n" + "=" * 80)
    print("TEST 2: Mehrere URLs parallel auflösen (Performance-Test)")
    print("=" * 80)
    
    # Mehrere Test-URLs
    test_urls = [
        "https://news.google.com/rss/articles/CBMilwFBVV95cUxOTlh2UU83TVNGWG8wd2VGc2FmS0wtX0ZDWFJKS25GM0R6NS00cFVxV0xwYUNrT2R1OENGY09sZmxmSURpOUZKaDQ1R0hxWVdpdEpQR2g1d0hUc21BNlFIbDd1VlRQR3pCZFpDY0lPUUhpM0kyRktIZzZvcmx6a09QWmdhdnZEbG4wYUFid0IxVy1rR2lEYWR30gGcAUFVX3lxTE5qaUFQV1ljVWdrek9SaW5rUlFxZ0NfSmktWEpES25LY2dhUmtkVzJrTHRmblFNbkExOVdlT2ZVejdReW1PVjlud0h5SFBlblAtZ2gxUlQ0aFdURkxYWXpRQWtyOW5oZ1BYZmNEZ2hzLTJXYWQ4MUlIQkcxZjRrVXRQeG5nQTQ1NDl3RXVpa2FRTXJ0MUpNMG0yaEtiaQ?oc=5",
        "https://www.reuters.com/world/example",  # Nicht-Google-News URL (sollte unverändert bleiben)
    ]
    
    print(f"\nAuflösen von {len(test_urls)} URLs...\n")
    
    import time
    start_time = time.time()
    
    results = resolve_multiple_urls(test_urls, max_workers=10)
    
    elapsed_time = time.time() - start_time
    
    print(f"\n⏱️ Zeit: {elapsed_time:.2f} Sekunden")
    print(f"📊 Verarbeitete URLs: {len(results)}")
    
    successful = 0
    for orig, res in results.items():
        if orig != res and "news.google.com" not in res:
            successful += 1
        print(f"\n{'='*60}")
        print(f"Original:\n{orig[:80]}...")
        print(f"\nResolved:\n{res[:80]}...")
    
    print(f"\n{'='*80}")
    print(f"✅ Erfolgreich aufgelöst: {successful}/{len(test_urls)}")
    print(f"⏱️ Durchschnitt: {elapsed_time/len(test_urls):.2f} Sekunden pro URL")
    
    print("\n" + "=" * 80)
    print("TEST 3: Echte Google News Feed testen (optional)")
    print("=" * 80)
    print("\nWenn du feedparser installiert hast, kann ich einen echten Feed testen.")
    print("Führe dazu aus: pip install feedparser")
    
    try:
        import feedparser
        
        print("\n✅ feedparser gefunden! Teste echten Google News Feed...\n")
        
        feed_url = "https://news.google.com/rss/search?q=china+when:1d&hl=en&gl=US&ceid=US:en"
        feed = feedparser.parse(feed_url)
        
        print(f"Feed enthält {len(feed.entries)} Einträge\n")
        
        # Nimm die ersten 3 Links
        test_links = [entry.link for entry in feed.entries[:3]]
        
        print("Auflösen der ersten 3 Google News Links...\n")
        
        start_time = time.time()
        results = resolve_multiple_urls(test_links, max_workers=10)
        elapsed_time = time.time() - start_time
        
        successful = sum(1 for orig, res in results.items() if "news.google.com" not in res and orig != res)
        
        for i, (orig, res) in enumerate(results.items(), 1):
            status = "✅" if "news.google.com" not in res else "❌"
            print(f"\n{status} Link {i}:")
            print(f"  Original: {orig[:80]}...")
            print(f"  Resolved: {res[:80]}...")
        
        print(f"\n{'='*80}")
        print(f"✅ Erfolgreich: {successful}/{len(test_links)}")
        print(f"⏱️ Zeit: {elapsed_time:.2f} Sekunden")
        print(f"⏱️ Durchschnitt: {elapsed_time/len(test_links):.2f} Sekunden pro URL")
        
    except ImportError:
        print("\n⚠️ feedparser nicht installiert")
        print("Installation: pip install feedparser")
    
    print("\n" + "=" * 80)
    print("TESTS ABGESCHLOSSEN")
    print("=" * 80)
    print("\n✅ Wenn die Tests erfolgreich waren, kannst du die Funktionen")
    print("   jetzt in dein Hauptscript integrieren!")
    print("\n📖 Siehe INTEGRATION_GUIDE.py für die genaue Anleitung")
