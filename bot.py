import requests
import asyncio
from datetime import datetime, timezone
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TELEGRAM_TOKEN = "8807718291:AAFZ9e9HNYU5msFlju1FchS6J4D1rNQOgh4"
TELEGRAM_CHAT_ID = "-1003734394227"
HELIUS_API_KEY = "d42a709c-e572-4344-bd5b-20874533d8eb"

WALLETS = {
    "Stigman": "8fsKLLtvKNanL4ginCaiRS6UfeemY11rSf8U8fN1dJw4",
    "Cupseyy": "2fg5QD1eD7rzNNCsvnhmXFm5hqNgwTTG8p7kQ6f3rx6f",
    "Yp12": "7cQjAvzJsmdePPMk8TiW8hYHHhCfdNtEaaNK3o46YP12"
}

STABLE_TOKENS = [
    "So11111111111111111111111111111111111111112",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
]

MIN_USD = 50
MAX_DELAY_SECONDS = 300
bot_aktif = True
tx_history = {wallet: set() for wallet in WALLETS.values()}
sol_price_cache = {"price": 150, "last_update": 0}
recap_sent = False

daily_stats = {
    name: {"buy": 0, "sell": 0, "spent": 0, "pnl": 0}
    for name in WALLETS.keys()
}

def get_sol_price():
    try:
        now = datetime.now(timezone.utc).timestamp()
        if now - sol_price_cache["last_update"] < 300:
            return sol_price_cache["price"]
        url = "https://api.dexscreener.com/tokens/v1/solana/So11111111111111111111111111111111111111112"
        r = requests.get(url, timeout=10)
        data = r.json()
        if isinstance(data, list) and len(data) > 0:
            price = float(data[0].get("priceUsd", 150))
            sol_price_cache["price"] = price
            sol_price_cache["last_update"] = now
            return price
    except:
        pass
    return sol_price_cache["price"]

def get_token_info(mint):
    try:
        url = f"https://api.dexscreener.com/tokens/v1/solana/{mint}"
        r = requests.get(url, timeout=10)
        data = r.json()
        if isinstance(data, list) and len(data) > 0:
            pair = data[0]
            name = pair.get("baseToken", {}).get("symbol", "UNKNOWN")
            price = float(pair.get("priceUsd", 0))
            mcap = pair.get("marketCap", 0)
            return name, price, mcap
    except:
        pass
    return "UNKNOWN", 0, 0

def format_mcap(mcap):
    try:
        mcap = float(mcap)
        if mcap >= 1_000_000_000:
            return f"${mcap/1_000_000_000:.2f}B"
        elif mcap >= 1_000_000:
            return f"${mcap/1_000_000:.2f}M"
        elif mcap >= 1_000:
            return f"${mcap/1_000:.2f}K"
        return f"${mcap:.2f}"
    except:
        return "?"

def get_transactions(wallet):
    url = f"https://api.helius.xyz/v0/addresses/{wallet}/transactions?api-key={HELIUS_API_KEY}&limit=10"
    try:
        r = requests.get(url, timeout=10)
        return r.json()
    except:
        return []

def parse_tx(tx):
    try:
        sig = tx.get("signature", "")
        tx_type = tx.get("type", "")
        if tx_type != "SWAP":
            return None

        tx_time = tx.get("timestamp", 0)
        now = datetime.now(timezone.utc).timestamp()
        if now - tx_time > MAX_DELAY_SECONDS:
            return None

        token_transfers = tx.get("tokenTransfers", [])
        native_transfers = tx.get("nativeTransfers", [])
        fee_payer = tx.get("feePayer", "")

        token_in = None
        token_out = None
        amount_in = 0
        amount_out = 0

        for t in token_transfers:
            mint = t.get("mint", "")
            amount = t.get("tokenAmount", 0)
            if t.get("toUserAccount") == fee_payer:
                token_in = mint
                amount_in = amount
            elif t.get("fromUserAccount") == fee_payer:
                token_out = mint
                amount_out = amount

        sol_in = sum(t.get("amount", 0) for t in native_transfers if t.get("toUserAccount") == fee_payer) / 1e9
        sol_out = sum(t.get("amount", 0) for t in native_transfers if t.get("fromUserAccount") == fee_payer) / 1e9

        sol_price = get_sol_price()
        min_sol = MIN_USD / sol_price

        if sol_out > min_sol and token_in and token_in not in STABLE_TOKENS:
            return {"sig": sig, "action": "BUY", "mint": token_in, "sol": round(sol_out, 4), "amount": amount_in, "usd": round(sol_out * sol_price, 2), "time": tx_time}
        elif token_out and token_out not in STABLE_TOKENS and (sol_in > min_sol or (token_in and token_in in STABLE_TOKENS)):
            return {"sig": sig, "action": "SELL", "mint": token_out, "sol": round(sol_in, 4), "amount": amount_out, "usd": round(sol_in * sol_price, 2), "time": tx_time}

        return None
    except:
        return None

async def send_recap(app):
    tanggal = datetime.now(timezone.utc).strftime("%d %B %Y")
    pesan = f"📊 *Daily Recap - {tanggal}*\n"
    pesan += "━━━━━━━━━━━━━━━\n"

    for name, stats in daily_stats.items():
        pnl = stats["pnl"]
        pnl_emoji = "📈" if pnl >= 0 else "📉"
        pnl_text = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
        pesan += f"\n🐋 *{name}*\n"
        pesan += f"• BUY: {stats['buy']}x | SELL: {stats['sell']}x\n"
        pesan += f"• Total Spent: ${stats['spent']:.2f}\n"
        pesan += f"• Total PnL: {pnl_emoji} {pnl_text}\n"

    pesan += "\n━━━━━━━━━━━━━━━"
    await app.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=pesan, parse_mode="Markdown")

    for name in daily_stats:
        daily_stats[name] = {"buy": 0, "sell": 0, "spent": 0, "pnl": 0}

async def monitor_wallets(app):
    global recap_sent
    while True:
        try:
            if not bot_aktif:
                await asyncio.sleep(10)
                continue

            utc_now = datetime.now(timezone.utc)
            wib_hour = (utc_now.hour + 7) % 24
            wib_minute = utc_now.minute

            if wib_hour == 20 and wib_minute == 0 and not recap_sent:
                await send_recap(app)
                recap_sent = True
            elif wib_hour != 20:
                recap_sent = False

            for name, wallet in WALLETS.items():
                txs = get_transactions(wallet)
                if not txs or not isinstance(txs, list):
                    continue

                for tx in txs[:5]:
                    sig = tx.get("signature", "")
                    if sig and sig not in tx_history[wallet]:
                        parsed = parse_tx(tx)
                        if parsed:
                            token_name, price, mcap = get_token_info(parsed["mint"])

                            tx_time = datetime.fromtimestamp(parsed["time"], tz=timezone.utc)
                            wib_h = (tx_time.hour + 7) % 24
                            waktu = f"{tx_time.strftime('%H:%M:%S')} UTC ({wib_h:02d}:{tx_time.strftime('%M')} WIB)"

                            if parsed["action"] == "BUY":
                                emoji = "🟢"
                                action_text = "BUY 🚀"
                                sol_text = f"Spent: {parsed['sol']} SOL (≈${parsed['usd']})"
                                daily_stats[name]["buy"] += 1
                                daily_stats[name]["spent"] += parsed["usd"]
                                daily_stats[name]["pnl"] -= parsed["usd"]
                            else:
                                emoji = "🔴"
                                action_text = "SELL 💰"
                                sol_text = f"Received: {parsed['sol']} SOL (≈${parsed['usd']})"
                                daily_stats[name]["sell"] += 1
                                daily_stats[name]["pnl"] += parsed["usd"]

                            amount_fmt = f"{float(parsed['amount']):,.0f}" if parsed['amount'] else "?"
                            price_fmt = f"${price:.8f}" if price > 0 else "?"
                            mcap_fmt = format_mcap(mcap)

                            pesan = f"""{emoji} *Wallet Alert!*
━━━━━━━━━━━━━━━
👤 *Wallet:* {name}
📊 *Action:* {action_text}
🪙 *Token:* {token_name}
📦 *Amount:* {amount_fmt} {token_name}
💵 *{sol_text}*
💲 *Price:* {price_fmt}
📈 *MCap:* {mcap_fmt}
🕐 *Time:* {waktu}
━━━━━━━━━━━━━━━
🔗 [Solscan](https://solscan.io/tx/{parsed['sig']}) | 📊 [DexScreener](https://dexscreener.com/solana/{parsed['mint']})"""

                            await app.bot.send_message(
                                chat_id=TELEGRAM_CHAT_ID,
                                text=pesan,
                                parse_mode="Markdown"
                            )
                        tx_history[wallet].add(sig)

            await asyncio.sleep(15)
        except Exception as e:
            print(f"Error: {e}")
            await asyncio.sleep(10)

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sol_price = get_sol_price()
    status = "✅ Aktif" if bot_aktif else "⛔ Berhenti"
    pesan = f"👁️ *Wallet Tracker*: {status}\n\n"
    pesan += f"💲 *SOL Price:* ${sol_price:.2f}\n"
    pesan += f"🎯 *Min Trade:* ${MIN_USD}\n\n"
    pesan += "🐋 *Monitoring:*\n"
    for name in WALLETS.keys():
        pesan += f"• {name}\n"
    await update.message.reply_text(pesan, parse_mode="Markdown")

async def cmd_recap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_recap(update.effective_message._bot._application)

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_aktif
    bot_aktif = True
    await update.message.reply_text("✅ Bot aktif!")

async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_aktif
    bot_aktif = False
    await update.message.reply_text("⛔ Bot berhenti!")

async def main():
    print("Wallet Tracker Bot v2")
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("recap", cmd_recap))
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stop", cmd_stop))
    async with app:
        await app.start()
        await app.updater.start_polling()
        sol_price = get_sol_price()
        await app.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=f"👁️ *Wallet Tracker V2 AKTIF!*\n\n🐋 Monitoring:\n• Stigman\n• Cupseyy\n• Yp12\n\n💲 SOL: ${sol_price:.2f}\n🎯 Min trade: ${MIN_USD}\n📊 Recap: 20:00 WIB\n\n/status /recap /start /stop",
            parse_mode="Markdown"
        )
        await monitor_wallets(app)
        await app.updater.stop()
        await app.stop()

asyncio.run(main())
