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

# Wallets to monitor
WALLETS = [
    "AjBVnBJzDnsjHjeLTLziHUonvBohDHpjrdPUuW6MVmS2",
    "dATMod1UTXYzvaXji4mBsvXTeAUAC73TNJQAejKS54X",
    "86AEJExyjeNNgcp7GrAvCXTDicf5aGWgoERbXFiG1EdD",
    # Add more if needed
]

seen_transactions = set()
token_to_wallets = defaultdict(set)
IGNORED_TOKENS = {"So11111111111111111111111111111111111111112"}

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
        if not token_transfers:
            print(f"❌ No tokenTransfers found in tx: {tx.get('signature')}")
        mints = [t.get("mint") for t in token_transfers if t.get("tokenStandard") == "Fungible"]
        for t in token_transfers:
            print(f"🔄 Transfer: {t}")
        return mints
    except Exception as e:
        print(f"⚠️ Error parsing tx: {e}")
        return []

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }
    response = requests.post(url, data=data)
    if response.status_code != 200:
        print(f"[!] Telegram send error: {response.status_code} - {response.text}")

def main():
    print("👀 Starting wallet monitoring...")
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
                    if mint not in token_to_wallets:
                        token_to_wallets[mint] = set()
                    token_to_wallets[mint].add(wallet)
                    if len(token_to_wallets[mint]) >= 2:
                        dex_url = f"https://dexscreener.com/solana/{mint}"
                        msg = (
                            f"🚨 *Token Alert!*\n"
                            f"A watched wallet group just bought:\n\n"
                            f"🔹 Token: `{mint}`\n\n"
                            f"🔎 View on Dexscreener: {dex_url}\n"
                            f"🛒 [Buy with BonkBot](https://t.me/furiosa_bonkbot?start=ref_mqbn6_ca_{mint}) | "
                            f"[Buy with Trojan Bot](https://t.me/solana_trojanbot?start=buy_{mint})"
                        )
                        send_telegram_alert(msg)
        time.sleep(15)

if __name__ == "__main__":
    main()
