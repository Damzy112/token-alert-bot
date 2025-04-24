import os
import sys
import time
import requests
from dotenv import load_dotenv
from collections import defaultdict

# Load and validate environment variables
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")

required_vars = {
    "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
    "TELEGRAM_CHAT_ID": TELEGRAM_CHAT_ID,
    "HELIUS_API_KEY": HELIUS_API_KEY,
}

missing = [key for key, value in required_vars.items() if not value]
if missing:
    print(f"Missing required environment variables: {', '.join(missing)}")
    sys.exit(1)

# Constants
HELIUS_ENDPOINT_TEMPLATE = "https://api.helius.xyz/v0/addresses/{wallet}/transactions?api-key={api_key}"
DEXSCREENER_API_TEMPLATE = "https://api.dexscreener.com/latest/dex/pairs/solana/{}"

# Wallets to monitor
WALLETS = [
    "AjBVnBJzDnsjHjeLTLziHUonvBohDHpjrdPUuW6MVmS2",
    "dATMod1UTXYzvaXji4mBsvXTeAUAC73TNJQAejKS54X",
    "86AEJExyjeNNgcp7GrAvCXTDicf5aGWgoERbXFiG1EdD",
]

# Blacklisted tokens
BLACKLISTED_MINTS = {"So11111111111111111111111111111111111111112"}

seen_transactions = set()
token_to_wallets = defaultdict(set)

def fetch_transactions(wallet):
    url = HELIUS_ENDPOINT_TEMPLATE.format(wallet=wallet, api_key=HELIUS_API_KEY)
    response = requests.get(url)
    if response.status_code != 200:
        print(f"[!] Error fetching tx for {wallet}: {response.status_code} - {response.text}")
        return []
    return response.json()

def extract_token_mints(tx):
    try:
        token_transfers = tx.get("tokenTransfers", [])
        mints = [t.get("mint") for t in token_transfers if t.get("tokenStandard") == "Fungible"]
        return mints
    except Exception as e:
        print(f"⚠️ Error parsing tx: {e}")
        return []

def fetch_dexscreener_data(mint):
    try:
        url = DEXSCREENER_API_TEMPLATE.format(mint)
        response = requests.get(url)
        if response.status_code != 200:
            return None, None, None, None

        data = response.json()
        if not data.get("pairs"):
            return None, None, None, None

        pair_data = data["pairs"][0]
        market_cap = pair_data.get("fdv")
        price = float(pair_data["priceUsd"]) if pair_data.get("priceUsd") else None
        volume = pair_data.get("volume", {}).get("h24")

        return market_cap, price, volume, pair_data.get("url")
    except Exception as e:
        print(f"Error fetching Dexscreener data: {e}")
        return None, None, None, None

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    response = requests.post(url, data=data)
    if response.status_code != 200:
        print(f"[!] Telegram send error: {response.status_code} - {response.text}")

def main():
    print("👀 Starting wallet monitoring...")
    processed = 0
    startup_limit = 5

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
                    if mint in BLACKLISTED_MINTS:
                        continue

                    token_to_wallets[mint].add(wallet)
                    if len(token_to_wallets[mint]) >= 2:
                        market_cap, price, volume_24h, dexscreener_url = fetch_dexscreener_data(mint)

                        market_cap_text = f"💰 Market Cap: ${market_cap:,.0f}" if market_cap else "💰 Market Cap: N/A"
                        price_text = f"📈 Price: ${price:,.6f}" if price else "📈 Price: N/A"
                        volume_text = f"📊 24h Volume: ${volume_24h:,.0f}" if volume_24h else "📊 24h Volume: N/A"

                        msg = (
                            f"\U0001F6A8 *Token Alert!*\n"
                            f"A watched wallet group just bought:\n\n"
                            f"🔹 Token: `{mint}`\n"
                            f"{market_cap_text}\n"
                            f"{price_text}\n"
                            f"{volume_text}\n\n"
                            f"[🔎 View on Dexscreener]({dexscreener_url})\n"
                            f"[🛒 Buy with BonkBot](https://t.me/furiosa_bot?start=ref_mqbn6_ca_{mint}) | "
                            f"[🛒 Trojan Bot](https://t.me/TrojanBot?start=buy_{mint})"
                        )

                        if processed < startup_limit:
                            processed += 1
                            send_telegram_alert(msg)
                        elif processed == startup_limit:
                            print("Startup alert limit reached. New alerts will be sent live.")
                            processed += 1
                        elif processed > startup_limit:
                            send_telegram_alert(msg)

        time.sleep(15)

if __name__ == "__main__":
    main()
