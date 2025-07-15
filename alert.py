import os
import time
import requests
from dotenv import load_dotenv
from collections import defaultdict
from datetime import datetime

# Load environment variables
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_IDS = os.getenv("TELEGRAM_CHAT_IDS")
SOLSCAN_API_KEY = os.getenv("SOLSCAN_API_KEY")

if TELEGRAM_CHAT_IDS:
    TELEGRAM_CHAT_IDS = [chat_id.strip() for chat_id in TELEGRAM_CHAT_IDS.split(",")]

required_vars = {
    "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
    "TELEGRAM_CHAT_IDS": TELEGRAM_CHAT_IDS,
    "SOLSCAN_API_KEY": SOLSCAN_API_KEY,
}

missing = [key for key, value in required_vars.items() if not value]
if missing:
    raise EnvironmentError(f"Missing required environment variables: {', '.join(missing)}")

WALLETS = [
    "CBaM2xaPdDdhaopd8dD93LJAvextJoPngdKFz8QFP7JD",
    "DfMxre4cKmvogbLrPigxmibVTTQDuzjdXojWzjCXXhzj",
    "8yJFWmVTQq69p6VJxGwpzW7ii7c5J9GRAtHCNMMQPydj",
    "D6zdELhLudUPtEjzsvDjbUB1vZsErPWgvRnvD8rWc8Lg",
]

seen_transactions = set()
token_to_wallets = defaultdict(set)

IGNORED_TOKENS = {
    "FZN7QZ8ZUUAxMPfxYEYkH3cXUASzH8EqA6B4tyCL8f1j",  # Meteora LP
    "So11111111111111111111111111111111111111111",  # Native SOL
    "So11111111111111111111111111111111111111112", # Wrapped SOL
    "AN2oFJT42rE2XSkFG6HrZ2UmRH6CifzsYWM9Jf1LvX6u"
}

metadata_cache = {}  # token_address: (name, symbol, price, market_cap, timestamp)
CACHE_TTL = 300  # 5 minutes

def log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")

def fetch_transactions(wallet):
    url = (
        f"https://pro-api.solscan.io/v2.0/account/transfer?"
        f"address={wallet}&"
        f"activity_type[]=ACTIVITY_SPL_TRANSFER&"
        f"sort_by=block_time&sort_order=desc&"
        f"page=1&page_size=20"
    )
    headers = {
        "accept": "application/json",
        "token": SOLSCAN_API_KEY
    }

    try:
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            log(f"[!] Error fetching transfers for {wallet}: {response.status_code} - {response.text}")
            return []

        data = response.json()
        transfers = data.get("data", [])
        parsed_txs = []

        for tx in transfers:
            sig = tx.get("trans_id")
            mint = tx.get("token_address")
            flow = tx.get("flow")  # should be 'in' or 'out'

            if not sig or not mint or flow != "in":
                continue

            parsed_txs.append({
                "signature": sig,
                "tokenTransfers": [{
                    "mint": mint,
                    "tokenStandard": "Fungible"
                }]
            })

        return parsed_txs

    except Exception as e:
        log(f"⚠️ Solscan SPL transfer fetch error: {e}")
        return []

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

def get_token_metadata(token_address):
    now = time.time()
    if token_address in metadata_cache:
        name, symbol, price, market_cap, timestamp = metadata_cache[token_address]
        if now - timestamp < CACHE_TTL:
            return name, symbol, price, market_cap

    headers = {
        "accept": "application/json",
        "token": SOLSCAN_API_KEY
    }

    # Fetch meta
    name = symbol = "Unknown"
    market_cap = "N/A"
    try:
        url_meta = f"https://pro-api.solscan.io/v2.0/token/meta?address={token_address}"
        response_meta = requests.get(url_meta, headers=headers)
        if response_meta.status_code == 200:
            data = response_meta.json().get("data", {})
            name = data.get("name", "Unknown")
            symbol = data.get("symbol", "")
            market_cap = data.get("market_cap", "N/A")
        else:
            log(f"[!] Metadata fetch failed for {token_address}: {response_meta.status_code}")
    except Exception as e:
        log(f"⚠️ Error fetching metadata: {e}")

    # Fetch price
    price = "N/A"
    try:
        url_price = f"https://pro-api.solscan.io/v2.0/token/price?address={token_address}"
        response_price = requests.get(url_price, headers=headers)
        if response_price.status_code == 200:
            data_list = response_price.json().get("data", [])
            if isinstance(data_list, list) and data_list:
                price_entry = data_list[-1]
                price = round(float(price_entry.get("price", 0)), 8)
        else:
            log(f"[!] Price fetch failed for {token_address}: {response_price.status_code}")
    except Exception as e:
        log(f"⚠️ Error fetching price: {e}")

    metadata_cache[token_address] = (name, symbol, price, market_cap, now)
    return name, symbol, price, market_cap

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
    log("🔁 Starting wallet monitoring...")
    while True:
        for wallet in WALLETS:
            log(f"🔍 Checking wallet: {wallet}")
            transactions = fetch_transactions(wallet)
            log(f"   ↪ Found {len(transactions)} transactions")

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
                        name, symbol, price, market_cap = get_token_metadata(mint)
                        dex_url = f"https://dexscreener.com/solana/{mint}"
                        msg = (
                            f"\U0001F6A8 *Token Alert!*\n"
                            f"A watched wallet group just bought:\n\n"
                            f"🔹 Token: *{name}* (`{symbol}`)\n"
                            f"💲 Price: `${price}`\n"
                            f"📊 Market Cap: `${market_cap}`\n"
                            f"🪙 Address: `{mint}`\n\n"
                            f"[🔎 View on Dexscreener]({dex_url})\n"
                            f"[🛒 Buy with BonkBot](https://t.me/furiosa_bonkbot?start=ref_mqbn6_ca_{mint}) | "
                            f"[🛒 Trojan Bot](https://t.me/solana_trojanbot?start=buy_{mint})"
                        )
                        send_telegram_alert(msg)
        time.sleep(15)

if __name__ == "__main__":
    main()
