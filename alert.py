import os
import time
import requests
import json
import threading
import re
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

# Blacklist file
BLACKLIST_FILE = "blacklist.json"

def load_blacklist():
    try:
        with open(BLACKLIST_FILE, "r") as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

def save_blacklist(blacklist):
    with open(BLACKLIST_FILE, "w") as f:
        json.dump(list(blacklist), f)

blacklisted_tokens = load_blacklist()

# Wallets to track
WALLETS = [
    "suqh5sHtr8HyJ7q8scBimULPkPpA557prMG47xCHQfK",
    "6ghHk323zz5hBFdvXJtdhRS1em5rzTDkEdh7Ch9SGovU",
    "BtDaZUqHr2mKH5EYQCztuerHBuBEfQNYdquTDtEZp2Ym",
    "j1oxqtEHFn7rUkdABJLmtVtz5fFmHFs4tCG3fWJnkHX",
    "CBaM2xaPdDdhaopd8dD93LJAvextJoPngdKFz8QFP7JD",
    "DfMxre4cKmvogbLrPigxmibVTTQDuzjdXojWzjCXXhzj",
    "8yJFWmVTQq69p6VJxGwpzW7ii7c5J9GRAtHCNMMQPydj",
    "5YkZmuaLhrPjFv4vtYE2mcR6J4JEXG1EARGh8YYFo8s4",
    "Aqw3ke5j7K9BNAAsKKUGDZxjgfsqqFH5q1voRq6Fbg3t",
    "86AEJExyjeNNgcp7GrAvCXTDicf5aGWgoERbXFiG1EdD"
]

WALLET_ALIASES = {
    "suqh5sHtr8HyJ7q8scBimULPkPpA557prMG47xCHQfK": "Alaba",
    "6ghHk323zz5hBFdvXJtdhRS1em5rzTDkEdh7Ch9SGovU": "Benjamin",
    "BtDaZUqHr2mKH5EYQCztuerHBuBEfQNYdquTDtEZp2Ym": "Caro",
    "j1oxqtEHFn7rUkdABJLmtVtz5fFmHFs4tCG3fWJnkHX": "Dolapo",
    "CBaM2xaPdDdhaopd8dD93LJAvextJoPngdKFz8QFP7JD": "Ezekiel",
    "DfMxre4cKmvogbLrPigxmibVTTQDuzjdXojWzjCXXhzj": "Folake",
    "8yJFWmVTQq69p6VJxGwpzW7ii7c5J9GRAtHCNMMQPydj": "Gbolahan",
    "5YkZmuaLhrPjFv4vtYE2mcR6J4JEXG1EARGh8YYFo8s4": "Henry",
    "Aqw3ke5j7K9BNAAsKKUGDZxjgfsqqFH5q1voRq6Fbg3t": "Isaac",
    "86AEJExyjeNNgcp7GrAvCXTDicf5aGWgoERbXFiG1EdD": "Junior"
}

seen_transactions = set()
token_to_wallets = defaultdict(set)
wallet_buy_times = {}
initial_market_caps = {}

IGNORED_TOKENS = {
    "FZN7QZ8ZUUAxMPfxYEYkH3cXUASzH8EqA6B4tyCL8f1j",
    "So11111111111111111111111111111111111111111",
    "So11111111111111111111111111111111111111112",
    "AN2oFJT42rE2XSkFG6HrZ2UmRH6CifzsYWM9Jf1LvX6u"
}

metadata_cache = {}
CACHE_TTL = 30

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
    headers = {"accept": "application/json", "token": SOLSCAN_API_KEY}
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
            flow = tx.get("flow")
            if not sig or not mint or flow != "in":
                continue
            parsed_txs.append({
                "signature": sig,
                "tokenTransfers": [{"mint": mint, "tokenStandard": "Fungible"}]
            })
        return parsed_txs
    except Exception as e:
        log(f"⚠️ Solscan SPL transfer fetch error: {e}")
        return []

def extract_token_mints(tx):
    try:
        token_transfers = tx.get("tokenTransfers", [])
        for t in token_transfers:
            log(f"🔄 Transfer: {t}")
        return [t.get("mint") for t in token_transfers if t.get("tokenStandard") == "Fungible"]
    except Exception as e:
        log(f"⚠️ Error parsing tx: {e}")
        return []

def get_token_metadata(token_address):
    now = time.time()
    if token_address in metadata_cache:
        name, symbol, price, market_cap, timestamp = metadata_cache[token_address]
        if now - timestamp < CACHE_TTL:
            return name, symbol, price, market_cap

    headers = {"accept": "application/json", "token": SOLSCAN_API_KEY}
    name = symbol = "Unknown"
    market_cap = "N/A"
    try:
        meta_url = f"https://pro-api.solscan.io/v2.0/token/meta?address={token_address}"
        response_meta = requests.get(meta_url, headers=headers)
        if response_meta.status_code == 200:
            data = response_meta.json().get("data", {})
            name = data.get("name", "Unknown")
            symbol = data.get("symbol", "")
            market_cap = data.get("market_cap", "N/A")
    except Exception as e:
        log(f"⚠️ Error fetching metadata: {e}")

    price = "N/A"
    try:
        price_url = f"https://pro-api.solscan.io/v2.0/token/price?address={token_address}"
        response_price = requests.get(price_url, headers=headers)
        if response_price.status_code == 200:
            data_list = response_price.json().get("data", [])
            if isinstance(data_list, list) and data_list:
                price_entry = data_list[-1]
                price = round(float(price_entry.get("price", 0)), 8)
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
        requests.post(url, data=data)

def listen_for_blacklist_commands():
    log("📨 Listening for Telegram messages to update blacklist...")
    offset = None
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
            params = {"timeout": 30}
            if offset:
                params["offset"] = offset
            response = requests.get(url, params=params)
            data = response.json()
            for update in data.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                text = msg.get("text", "").strip()
                chat_id = str(msg.get("chat", {}).get("id", ""))

                if chat_id not in TELEGRAM_CHAT_IDS:
                    continue

                if re.fullmatch(r"[A-Za-z0-9]{32,44}", text):
                    log(f"📥 Received blacklist request for: {text}")
                    if text in blacklisted_tokens:
                        send_telegram_alert(f"⚠️ Token already blacklisted:\n`{text}`")
                    else:
                        blacklisted_tokens.add(text)
                        save_blacklist(blacklisted_tokens)
                        send_telegram_alert(f"✅ Token blacklisted:\n`{text}`")
        except Exception as e:
            log(f"⚠️ Error in Telegram listener: {e}")
        time.sleep(3)

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
                    if mint in IGNORED_TOKENS or mint in blacklisted_tokens:
                        continue
                    token_to_wallets[mint].add(wallet)
                    key = (mint, wallet)
                    if key not in wallet_buy_times:
                        wallet_buy_times[key] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    if len(token_to_wallets[mint]) >= 2:
                        name, symbol, price, market_cap = get_token_metadata(mint)
                        dex_url = f"https://dexscreener.com/solana/{mint}"
                        twitter_url = f"https://twitter.com/search?q={mint}&src=typed_query"
                        try:
                            current_mc = float(market_cap)
                        except:
                            current_mc = None

                        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                        return_text = ""
                        if current_mc is not None:
                            if mint not in initial_market_caps:
                                initial_market_caps[mint] = (current_mc, now_str)
                            else:
                                initial_mc, first_time = initial_market_caps[mint]
                                pct_return = ((current_mc - initial_mc) / initial_mc) * 100
                                if pct_return > 0:
                                    return_text = f"\n🟩 *Return Since First Alert:* +*{pct_return:.2f}%*\n📅 First Alert: {first_time}\n📅 Now: {now_str}"
                                elif pct_return < 0:
                                    return_text = f"\n🟥 *Return Since First Alert:* -*{abs(pct_return):.2f}%*\n📅 First Alert: {first_time}\n📅 Now: {now_str}"
                                else:
                                    return_text = f"\n🟨 *Return Since First Alert:* *0.00%*\n📅 First Alert: {first_time}\n📅 Now: {now_str}"

                        wallets_sorted = sorted(
                            token_to_wallets[mint],
                            key=lambda w: wallet_buy_times.get((mint, w), "")
                        )
                        wallet_list = "\n".join([f"• {WALLET_ALIASES.get(w, w)}" for w in wallets_sorted])
                        msg = (
                            f"\U0001F6A8 *Token Alert!*\n"
                            f"*{len(token_to_wallets[mint])} watched wallets* have bought this token:\n\n"
                            f"🔹 Token: *{name}* (`{symbol}`)\n"
                            f"💲 Price: `${price}`\n"
                            f"📊 Market Cap: `${market_cap}`{return_text}\n"
                            f"🪙 Address: `{mint}`\n\n"
                            f"👛 Wallets (by time bought):\n{wallet_list}\n\n"
                            f"[🔎 View on Dexscreener]({dex_url}) | [🐦 Search on Twitter]({twitter_url})\n"
                            f"[🛒 Buy with BonkBot](https://t.me/furiosa_bonkbot?start=ref_mqbn6_ca_{mint}) | "
                            f"[🛒 Trojan Bot](https://t.me/solana_trojanbot?start=buy_{mint})"
                        )
                        send_telegram_alert(msg)
        time.sleep(15)

if __name__ == "__main__":
    threading.Thread(target=listen_for_blacklist_commands, daemon=True).start()
    main()
