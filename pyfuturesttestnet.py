import websocket
import json
import numpy as np
import pandas as pd
from binance.client import Client
from binance.enums import *
import time
import os
import threading

# --- YAPILANDIRMA ---
# Ayarlar artık doğrudan kodda değil, sunucu ortam değişkenlerinden okunacak.

API_KEY = os.environ.get('API_KEY')
API_SECRET = os.environ.get('API_SECRET')

# Strateji Parametreleri
SYMBOL = 'DOGEUSDT'
LEVERAGE = 10
RSI_PERIOD = 14
RSI_OVERSOLD = 30
TAKE_PROFIT_PCT = 0.10
STOP_LOSS_PCT = 0.03
TRADE_USDT_AMOUNT = 10
INTERVAL = Client.KLINE_INTERVAL_1MINUTE

# --- BOT KODU ---

TESTNET_URL_FUTURES = "https://testnet.binancefuture.com"
TESTNET_SOCKET_URL_FUTURES = f"wss://stream.binancefuture.com/ws/{SYMBOL.lower()}@kline_{INTERVAL}"

closes = []
in_position = False
client = None

def check_open_positions():
    global in_position
    try:
        positions = client.futures_position_information(symbol=SYMBOL)
        position_found = any(p['symbol'] == SYMBOL and float(p['positionAmt']) > 0 for p in positions)
        if position_found:
            if not in_position: print(f"Mevcut açık pozisyon bulundu.")
            in_position = True
        else:
            if in_position: print("Açık pozisyon yok. Sinyal bekleniyor...")
            in_position = False
    except Exception as e:
        print(f"Pozisyon kontrolü sırasında hata: {e}")
        in_position = False

def calculate_rsi(data):
    if len(data) < RSI_PERIOD: return None
    df = pd.DataFrame(data, columns=['close'])
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=RSI_PERIOD).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=RSI_PERIOD).mean()
    if loss.iloc[-1] == 0: return 100
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]

def place_order_with_tp_sl():
    global in_position
    try:
        ticker = client.futures_ticker(symbol=SYMBOL)
        last_price = float(ticker['lastPrice'])
        quantity = round(TRADE_USDT_AMOUNT / last_price * LEVERAGE, 3)
        
        print(f"\n--- YENİ İŞLEM BAŞLATILIYOR ---")
        print(f"Fiyat: {last_price}, Miktar: {quantity} {SYMBOL}")

        client.futures_create_order(symbol=SYMBOL, side=SIDE_BUY, type=ORDER_TYPE_MARKET, quantity=quantity)
        print("Piyasa Alış Emri Başarıyla Verildi.")
        time.sleep(1)
        
        positions = client.futures_position_information(symbol=SYMBOL)
        entry_price = next((float(p['entryPrice']) for p in positions if p['symbol'] == SYMBOL), 0)
        if entry_price == 0: raise Exception("Giriş fiyatı alınamadı.")

        print(f"Pozisyona Giriş Fiyatı: {entry_price}")
        in_position = True

        tp_price = round(entry_price * (1 + TAKE_PROFIT_PCT / LEVERAGE), 4)
        client.futures_create_order(symbol=SYMBOL, side=SIDE_SELL, type='TAKE_PROFIT_MARKET', stopPrice=tp_price, closePosition=True)
        print(f"Kar Al (Take Profit) Emri {tp_price} seviyesine kuruldu.")

        sl_price = round(entry_price * (1 - STOP_LOSS_PCT / LEVERAGE), 4)
        client.futures_create_order(symbol=SYMBOL, side=SIDE_SELL, type='STOP_MARKET', stopPrice=sl_price, closePosition=True)
        print(f"Zarar Durdur (Stop Loss) Emri {sl_price} seviyesine kuruldu.")
        print("--- İŞLEM AKTİF, SONUÇ BEKLENİYOR ---\n")
    except Exception as e:
        print(f"Emir verme sırasında bir hata oluştu: {e}")
        in_position = False

def on_message(ws, message):
    global closes
    json_message = json.loads(message)
    if 'e' in json_message and json_message['e'] == 'kline':
        kline = json_message['k']
        if kline['x']: # Mum kapandı mı?
            close_price = float(kline['c'])
            print(f"Mum kapandı: {close_price}", end=' | ')
            closes.append(close_price)
            if len(closes) > 100: closes.pop(0)
            
            if not in_position:
                rsi = calculate_rsi(closes)
                if rsi is not None:
                    print(f"RSI: {rsi:.2f}")
                    if rsi < RSI_OVERSOLD:
                        print(f"\n>>> ALIM SİNYALİ! RSI ({rsi:.2f}) < {RSI_OVERSOLD} <<<\n")
                        place_order_with_tp_sl()
                else:
                    print("RSI için veri toplanıyor...")
            else:
                 print("Pozisyon açık, TP/SL bekleniyor.")

def position_check_loop():
    while True:
        if client: check_open_positions()
        time.sleep(10)

def on_open(ws):
    print("Binance FUTURES Testnet ile bağlantı kuruldu.")
    checker_thread = threading.Thread(target=position_check_loop, daemon=True)
    checker_thread.start()

def main():
    global client
    print("Bot başlatılıyor...")
    
    if not API_KEY or not API_SECRET:
        print("\n!!! HATA: API_KEY ve API_SECRET ortam değişkenleri bulunamadı.")
        print("Lütfen Render.com'daki 'Environment' ayarlarını kontrol edin.")
        return

    client = Client(API_KEY, API_SECRET)
    client.API_URL = TESTNET_URL_FUTURES
    
    try:
        print("Hesap bilgileri doğrulanıyor...")
        client.futures_account_balance()
        print("API Anahtarları geçerli.")
    except Exception as e:
        print(f"API Anahtarları ile doğrulama başarısız: {e}")
        return

    try:
        client.futures_change_leverage(symbol=SYMBOL, leverage=LEVERAGE)
        print(f"{SYMBOL} için kaldıraç {LEVERAGE}x olarak ayarlandı.")
    except Exception as e:
        print(f"Kaldıraç ayarlanırken hata: {e}")

    try:
        print("Geçmiş veriler çekiliyor...")
        klines = client.futures_klines(symbol=SYMBOL, interval=INTERVAL, limit=100)
        for k in klines: closes.append(float(k[4]))
        print("Geçmiş veriler başarıyla çekildi.")
    except Exception as e:
        print(f"Geçmiş veri çekilirken hata: {e}")
        return

    ws = websocket.WebSocketApp(TESTNET_SOCKET_URL_FUTURES, on_open=on_open, on_message=on_message)
    ws.run_forever()

if __name__ == "__main__":
    main()
