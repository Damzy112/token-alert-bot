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
    "suqh5sHtr8HyJ7q8scBimULPkPpA557prMG47xCHQfK",
    "6ghHk323zz5hBFdvXJtdhRS1em5rzTDkEdh7Ch9SGovU",
    "BtDaZUqHr2mKH5EYQCztuerHBuBEfQNYdquTDtEZp2Ym",
    "65MtrVc5TQP3JcxKHjbkwYmk9QC6wiskEBZvhpe1d3rN",
    "CBaM2xaPdDdhaopd8dD93LJAvextJoPngdKFz8QFP7JD",
    "DfMxre4cKmvogbLrPigxmibVTTQDuzjdXojWzjCXXhzj",
    "8yJFWmVTQq69p6VJxGwpzW7ii7c5J9GRAtHCNMMQPydj",
    "D6zdELhLudUPtEjzsvDjbUB1vZsErPWgvRnvD8rWc8Lg"
    
]

WALLET_ALIASES = {
    "suqh5sHtr8HyJ7q8scBimULPkPpA557prMG47xCHQfK": "Alaba",
    "6ghHk323zz5hBFdvXJtdhRS1em5rzTDkEdh7Ch9SGovU": "Benjamin",
    "BtDaZUqHr2mKH5EYQCztuerHBuBEfQNYdquTDtEZp2Ym": "Caro",
    "65MtrVc5TQP3JcxKHjbkwYmk9QC6wiskEBZvhpe1d3rN": "Dolapo",
    "CBaM2xaPdDdhaopd8dD93LJAvextJoPngdKFz8QFP7JD": "Ezekiel",
    "DfMxre4cKmvogbLrPigxmibVTTQDuzjdXojWzjCXXhzj": "Folake",
    "8yJFWmVTQq69p6VJxGwpzW7ii7c5J9GRAtHCNMMQPydj": "Gbolahan"
    "D6zdELhLudUPtEjzsvDjbUB1vZsErPWgvRnvD8rWc8Lg": "Henry"
}

seen_transactions = set()
token_to_wallets = defaultdict(set)
wallet_buy_times = {}  # (token_address, wallet): timestamp string
initial_market_caps = {}  # token_address: (initial_market_cap, timestamp)

IGNORED_TOKENS = {
    "FZN7QZ8ZUUAxMPfxYEYkH3cXUASzH8EqA6B4tyCL8f1j",  # Meteora LP
    "So11111111111111111111111111111111111111111",  # Native SOL
    "So11111111111111111111111111111111111111112",  # Wrapped SOL
    "AN2oFJT42rE2XSkFG6HrZ2UmRH6CifzsYWM9Jf1LvX6u"
}

metadata_cache = {}  # token_address: (name, symbol, price, market_cap, timestamp)
CACHE_TTL = 60  # 1 minute

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

                    # Track buy time per wallet-token pair
                    key = (mint, wallet)
                    if key not in wallet_buy_times:
                        wallet_buy_times[key] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    if len(token_to_wallets[mint]) >= 2:
                        name, symbol, price, market_cap = get_token_metadata(mint)
                        dex_url = f"https://dexscreener.com/solana/{mint}"
                        twitter_url = f"https://twitter.com/search?q={mint}&src=typed_query"

                        # Market cap float conversion for return calculation
                        try:
                            current_mc = float(market_cap)
                        except (ValueError, TypeError):
                            current_mc = None

                        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                        return_text = ""
                        if current_mc is not None:
                            if mint not in initial_market_caps:
                                initial_market_caps[mint] = (current_mc, now_str)
                            else:
                                initial_mc, first_time = initial_market_caps[mint]
                                if initial_mc > 0:
                                    pct_return = ((current_mc - initial_mc) / initial_mc) * 100
                                    if pct_return > 0:
                                        return_text = (
                                            f"\n🟩 *Return Since First Alert:* +*{pct_return:.2f}%*"
                                            f"\n📅 First Alert: {first_time}"
                                            f"\n📅 Now: {now_str}"
                                        )
                                    elif pct_return < 0:
                                        return_text = (
                                            f"\n🟥 *Return Since First Alert:* -*{abs(pct_return):.2f}%*"
                                            f"\n📅 First Alert: {first_time}"
                                            f"\n📅 Now: {now_str}"
                                        )
                                    else:
                                        return_text = (
                                            f"\n🟨 *Return Since First Alert:* *0.00%*"
                                            f"\n📅 First Alert: {first_time}"
                                            f"\n📅 Now: {now_str}"
                                        )

                        # Sort wallets by buy time for this token
                        wallets_sorted = sorted(
                            token_to_wallets[mint],
                            key=lambda w: wallet_buy_times.get((mint, w), "")
                        )
                        wallet_list = "\n".join([
                            f"• {WALLET_ALIASES.get(w, w)}" for w in wallets_sorted
                        ])

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
    main()
