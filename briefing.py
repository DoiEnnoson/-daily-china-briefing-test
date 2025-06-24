import requests
import json
import os
import smtplib
from email.mime.text import MIMEText
from datetime import date, datetime, timedelta

def load_scfi_cache():
    cache_file = "scfi_cache.json"
    print(f"DEBUG - load_scfi_cache: Attempting to load cache from {cache_file}")
    try:
        with open(cache_file, "r") as f:
            cache = json.load(f)
            # Konvertiere alte Einträge (Float) in neues Format
            for key, value in cache.items():
                if isinstance(value, (int, float)):
                    cache[key] = {"value": float(value), "api_date": key}
            print(f"DEBUG - load_scfi_cache: Successfully loaded cache: {cache}")
            return cache
    except FileNotFoundError:
        print("DEBUG - load_scfi_cache: Cache file not found, returning empty cache")
        return {}
    except Exception as e:
        print(f"❌ ERROR - load_scfi_cache: Failed to load cache: {str(e)}")
        return {}

def save_scfi_cache(cache):
    cache_file = "scfi_cache.json"
    print(f"DEBUG - save_scfi_cache: Attempting to save cache to {cache_file}")
    print(f"DEBUG - save_scfi_cache: Cache content: {cache}")
    try:
        with open(cache_file, "w") as f:
            json.dump(cache, f, indent=2)
        print(f"DEBUG - save_scfi_cache: Successfully written cache to {cache_file}")
        with open(cache_file, "r") as f:
            print(f"DEBUG - save_scfi_cache: Verified cache content: {json.load(f)}")
    except Exception as e:
        print(f"❌ ERROR - save_scfi_cache: Failed to save cache: {str(e)}")
        raise

def fetch_scfi():
    print("DEBUG - fetch_scfi: Starting to fetch SCFI data")
    url
