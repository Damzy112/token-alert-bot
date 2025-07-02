import os
import sys
import time
import requests
from dotenv import load_dotenv
from collections import defaultdict
from datetime import datetime

# Load and validate environment variables
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_IDS = os.getenv("TELEGRAM_CHAT_IDS")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")
SOLSCAN_API_KEY = os.getenv("SOLSCAN_API_KEY")

if TELEGRAM_CHAT_IDS:
    TELEGRAM_CHAT_IDS = [chat_id.strip() for chat_id in TELEGRAM_CHAT_IDS.split(",")]

required_vars = {
    "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
    "TELEGRAM_CHAT_IDS": TELEGRAM_CHAT_IDS,
    "HELIUS_API_KEY": HELIUS_API_KEY,
    "SOLSCAN_API_KEY": SOLSCAN_API_KEY,
}

missing = [key for key, value in required_vars.items() if not value]
if missing:
    raise EnvironmentError(f"Missing required environment variables: {', '.join(missing)}")

HELIUS_ENDPOINT_TEMPLATE = "https://api.helius.xyz/v0/addresses/{wallet}/transactions?limit=20&api-key={api_key}"

WALLETS = [
    "CBaM2xaPdDdhaopd8dD93LJAvextJoPngdKFz8QFP7JD",
    "DfMxre4cKmvogbLrPigxmibVTTQDuzjdXojWzjCXXhzj",
    "8yJFWmVTQq69p6VJxGwpzW7ii7c5J9GRAtHCNMMQPydj",
    "D6zdELhLudUPtEjzsvDjbUB1vZsErPWgvRnvD8rWc8Lg",
    # Add more if needed
]

seen_transactions = set()
token_to_wallets = defaultdict(set)
IGNORED_TOKENS = {
    "FZN7QZ8ZUUAxMPfxYEYkH3cXUASzH8EqA6B4tyCL8f1j",
    "So11111111111111111111111111111111111111112",
    "AN2oFJT42rE2XSkFG6HrZ2UmRH6CifzsYWM9Jf1LvX6u"
}

# Caches with expiry
metadata_cache = {}  # {token_address: (name, symbol, timestamp)}
price_cache = {}     # {token_address: (price, timestamp)}
CACHE_TTL = 300  # 5 minutes

def log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")

def fetch_transactions(wallet):
    url = HELIUS_ENDPOINT_TEMPLATE.format(wallet=wallet, api_key=HELIUS_API_KEY)
    response = requests.get(url)
    if response.status_code != 200:
        log(f"[!] Error fetching tx for {wallet}: {response.status_code} - {response.text}")
        return []
    return response.json()

def extract_token_mints(tx):
    try:
        token_transfers = tx.get("tokenTransfers", [])
        if not token_transfers:
            log(f"❌ No tokenTransfers found in tx: {tx.get('signature')}")
        mints = [t.get("mint") for t in token_transfers if t.get("tokenStandard") == "Fungible"]
        for t in token_transfers:
            log(f"🔄 Transfer: {t}")
        return mints
    except Exception as e:
        log(f"⚠️ Error parsing tx: {e}")
        return []

def get_token_price(token_address):
    now = time.time()
    if token_address in price_cache:
        price, timestamp = price_cache[token_address]
        if now - timestamp < CACHE_TTL:
            return price

    try:
        url = f"https://pro-api.solscan.io/v2.0/token/price?address={token_address}"
        headers = {
            "accept": "application/json",
            "token": SOLSCAN_API_KEY
        }
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            raw_data = response.json()
            data_list = raw_data.get("data", [])
            if isinstance(data_list, list) and len(data_list) > 0:
                latest_price_entry = data_list[-1]
                price = latest_price_entry.get("price")
                result = round(float(price), 6) if price else "N/A"
                price_cache[token_address] = (result, now)
                return result
            return "N/A"
        else:
            log(f"[!] Solscan price fetch failed for {token_address}: {response.status_code} - {response.text}")
            return "N/A"
    except Exception as e:
        log(f"⚠️ Error fetching price from Solscan for {token_address}: {e}")
        return "N/A"

def get_token_metadata(token_address):
    now = time.time()
    if token_address in metadata_cache:
        name, symbol, timestamp = metadata_cache[token_address]
        if now - timestamp < CACHE_TTL:
            return name, symbol

    try:
        url = f"https://pro-api.solscan.io/v2.0/token/meta?address={token_address}"
        headers = {
            "accept": "application/json",
            "token": SOLSCAN_API_KEY
        }
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            token_info = data.get("data", {})
            name = token_info.get("name", "Unknown")
            symbol = token_info.get("symbol", "")
            metadata_cache[token_address] = (name, symbol, now)
            return name, symbol
        else:
            log(f"[!] Metadata fetch failed for {token_address}: {response.status_code} - {response.text}")
            return "Unknown", ""
    except Exception as e:
        log(f"⚠️ Error fetching metadata from Solscan for {token_address}: {e}")
        return "Unknown", ""

def send_telegram_alert(message):
    for chat_id in TELEGRAM_CHAT_IDS:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False
        }
        response = requests.post(url, data=data)
        if response.status_code != 200:
            log(f"[!] Telegram send error for {chat_id}: {response.status_code} - {response.text}")
        else:
            log(f"✅ Telegram alert sent to {chat_id}")

def main():
    log("Starting wallet monitoring...")
    while True:
        for wallet in WALLETS:
            transactions = fetch_transactions(wallet)
            for tx in transactions:
                sig = tx.get("signature")
                if sig in seen_transactions:
                    continue
                seen_transactions.add(sig)
                mints = extract_token_mints(tx)
                for mint in mints:
                    if mint in IGNORED_TOKENS:
                        continue
                    token_to_wallets[mint].add(wallet)
                    if len(token_to_wallets[mint]) >= 2:
                        dex_url = f"https://dexscreener.com/solana/{mint}"
                        price = get_token_price(mint)
                        name, symbol = get_token_metadata(mint)
                        msg = (
                            f"\U0001F6A8 *Token Alert!*\n"
                            f"A watched wallet group just bought:\n\n"
                            f"🔹 Token: *{name}* (`{symbol}`)\n"
                            f"💲 Price: `${price}`\n"
                            f"🪙 Address: `{mint}`\n\n"
                            f"[🔎 View on Dexscreener]({dex_url})\n"
                            f"[🛒 Buy with BonkBot](https://t.me/furiosa_bonkbot?start=ref_mqbn6_ca_{mint}) | "
                            f"[🛒 Trojan Bot](https://t.me/solana_trojanbot?start=buy_{mint})"
                        )
                        send_telegram_alert(msg)
        time.sleep(15)

if __name__ == "__main__":
    main()
