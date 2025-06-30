import websocket
import json
import numpy as np
import pandas as pd
from binance.client import Client
from binance.enums import *
import time
import os
import threading

# --- YAPILANDIRMA (Lütfen bu bölümü düzenleyin) ---

# 1. Adım: Binance Testnet API anahtarlarınızı buraya yapıştırın.
API_KEY = "ShPET9aiEKcGFWKjr1BYgBDOE5EDeO1sANbYQ9UiQ2IpWorNuQd95iQvyjNbad5E" 
API_SECRET = "jcR1IPpkGMrp5kR08KNXm4GMib8ooJET8HgdJgB7Jqhh50kLN6VeFLaub4flf3mN"

# 2. Adım: İşlem yapılacak parite ve strateji parametreleri
SYMBOL = 'DOGEUSDT'
LEVERAGE = 10
RSI_PERIOD = 14
RSI_OVERSOLD = 30
TAKE_PROFIT_PCT = 0.10  # %10 kar
STOP_LOSS_PCT = 0.03    # %3 zarar
TRADE_USDT_AMOUNT = 15000  # Her işlemde kullanılacak sanal USDT miktarı
INTERVAL = Client.KLINE_INTERVAL_1MINUTE # 1 dakikalık mumlar

# --- BOT KODU (Bu bölümü değiştirmenize gerek yok) ---

# Binance Testnet bağlantı URL'leri
BASE_URL_FUTURES = "https://fapi.binance.com"
TESTNET_URL_FUTURES = "https://testnet.binancefuture.com"
SOCKET_URL_FUTURES = f"wss://fstream.binance.com/ws/{SYMBOL.lower()}@kline_{INTERVAL}"
TESTNET_SOCKET_URL_FUTURES = f"wss://stream.binancefuture.com/ws/{SYMBOL.lower()}@kline_{INTERVAL}"

# Global Değişkenler
closes = []
in_position = False
client = None

def check_open_positions():
    """Mevcut açık pozisyon olup olmadığını kontrol eder."""
    global in_position
    try:
        positions = client.futures_position_information(symbol=SYMBOL)
        # Birden fazla pozisyon bilgisi dönebilir, doğru olanı bulmalıyız.
        for position in positions:
            if position['symbol'] == SYMBOL and float(position['positionAmt']) > 0:
                print(f"Mevcut açık pozisyon bulundu: {position['positionAmt']} {SYMBOL}")
                in_position = True
                return
        in_position = False
        print("Açık pozisyon yok. Sinyal bekleniyor...")
    except Exception as e:
        print(f"Pozisyon kontrolü sırasında hata: {e}")
        in_position = False

def calculate_rsi(data, period=14):
    """RSI değerini hesaplar."""
    if len(data) < period:
        return None
    
    df = pd.DataFrame(data, columns=['close'])
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    
    if loss.iloc[-1] == 0: # Sıfıra bölme hatasını önle
        return 100
        
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]

def place_order_with_tp_sl():
    """Alım emri ve ilişkili TP/SL emirlerini yerleştirir."""
    global in_position
    try:
        # Fiyat ve miktar hesaplama
        ticker = client.futures_ticker(symbol=SYMBOL)
        last_price = float(ticker['lastPrice'])
        quantity = round(TRADE_USDT_AMOUNT / last_price * LEVERAGE, 3) # Miktarı DOGE cinsinden hesapla
        
        print(f"\n--- YENİ İŞLEM BAŞLATILIYOR ---")
        print(f"Fiyat: {last_price}, Miktar: {quantity} {SYMBOL}")

        # 1. LONG (ALIŞ) PİYASA EMRİ
        order = client.futures_create_order(
            symbol=SYMBOL,
            side=SIDE_BUY,
            type=ORDER_TYPE_MARKET,
            quantity=quantity
        )
        print("Piyasa Alış Emri Başarıyla Verildi.")
        
        # Giriş fiyatını doğru almak için biraz bekle
        time.sleep(1) 
        entry_price = 0
        positions = client.futures_position_information(symbol=SYMBOL)
        for p in positions:
             if p['symbol'] == SYMBOL:
                entry_price = float(p['entryPrice'])
                break
        
        if entry_price == 0:
            print("Hata: Pozisyon giriş fiyatı alınamadı.")
            return

        print(f"Pozisyona Giriş Fiyatı: {entry_price}")
        in_position = True

        # 2. TAKE PROFIT (KAR AL) EMRİ
        tp_price = round(entry_price * (1 + TAKE_PROFIT_PCT / LEVERAGE), 4)
        client.futures_create_order(
            symbol=SYMBOL,
            side=SIDE_SELL,
            type='TAKE_PROFIT_MARKET',
            stopPrice=tp_price,
            closePosition=True
        )
        print(f"Kar Al (Take Profit) Emri {tp_price} seviyesine kuruldu.")

        # 3. STOP LOSS (ZARAR DURDUR) EMRİ
        sl_price = round(entry_price * (1 - STOP_LOSS_PCT / LEVERAGE), 4)
        client.futures_create_order(
            symbol=SYMBOL,
            side=SIDE_SELL,
            type='STOP_MARKET', # API'de STOP_LOSS_MARKET yerine STOP_MARKET kullanılabilir
            stopPrice=sl_price,
            closePosition=True
        )
        print(f"Zarar Durdur (Stop Loss) Emri {sl_price} seviyesine kuruldu.")
        print("--- İŞLEM AKTİF, SONUÇ BEKLENİYOR ---\n")

    except Exception as e:
        print(f"Emir verme sırasında bir hata oluştu: {e}")
        in_position = False

def on_message(ws, message):
    """Websocket'ten gelen her mesajda tetiklenir."""
    global closes, in_position
    json_message = json.loads(message)
    
    if 'e' in json_message and json_message['e'] == 'kline':
        kline = json_message['k']
        is_kline_closed = kline['x']
        close_price = float(kline['c'])
        
        if is_kline_closed:
            print(f"Mum kapandı: {close_price}", end=' | ')
            closes.append(close_price)
            if len(closes) > 100: # Hafızayı yönetmek için eski verileri sil
                closes.pop(0)

            # Pozisyon yoksa RSI ve sinyal kontrolü yap
            if not in_position:
                rsi = calculate_rsi(closes, RSI_PERIOD)
                if rsi is not None:
                    print(f"RSI: {rsi:.2f}")
                    if rsi < RSI_OVERSOLD:
                        print(f"\n>>> ALIM SİNYALİ! RSI ({rsi:.2f}) < {RSI_OVERSOLD} <<<\n")
                        place_order_with_tp_sl()
                else:
                    print("RSI hesaplamak için yeterli veri toplanıyor...")
            else:
                print("Pozisyon açık, yeni sinyal aranmıyor. TP/SL bekleniyor.")

def check_position_periodic():
    """Açık pozisyonun kapanıp kapanmadığını periyodik olarak kontrol eder."""
    # DÜZELTME: Bu fonksiyonun global değişkeni değiştireceğini belirtiyoruz.
    global in_position
    
    while True:
        try:
            if in_position: # Sadece bir pozisyon açıksa kontrol et
                 positions = client.futures_position_information(symbol=SYMBOL)
                 position_found = False
                 for p in positions:
                     if p['symbol'] == SYMBOL and float(p['positionAmt']) > 0:
                         position_found = True
                         break
                 
                 if not position_found:
                     print("\n--- POZİSYON KAPANDI ---")
                     in_position = False
                     # Durumu tekrar kontrol et ve "Sinyal bekleniyor" yazdır
                     check_open_positions()
            
            time.sleep(5) # Her 5 saniyede bir kontrol et

        except Exception as e:
            print(f"Periyodik pozisyon kontrol hatası: {e}")
            time.sleep(5)


def on_open(ws):
    print("Binance Testnet ile bağlantı kuruldu.")
    check_open_positions() # Bota başlarken açık pozisyon var mı diye kontrol et
    
    # Periyodik pozisyon kontrolünü ayrı bir thread'de başlat
    position_checker_thread = threading.Thread(target=check_position_periodic, daemon=True)
    position_checker_thread.start()


def on_close(ws, close_status_code, close_msg):
    print("Bağlantı kesildi. 5 saniye içinde yeniden bağlanmaya çalışılacak...")
    time.sleep(5)
    main() # Yeniden başlat

def main():
    """Botun ana çalışma fonksiyonu."""
    global client
    print("Bot başlatılıyor...")

    if "SENİN_TESTNET_API_ANAHTARIN" in API_KEY or "SENİN_TESTNET_GİZLİ_ANAHTARIN" in API_SECRET:
        print("\n!!! UYARI: Lütfen kodun içindeki API_KEY ve API_SECRET alanlarını kendi Testnet anahtarlarınızla güncelleyin.\n")
        return

    client = Client(API_KEY, API_SECRET)
    client.API_URL = TESTNET_URL_FUTURES # Testnet'e bağlan

    # Başlangıçta kaldıraç ve marjin türü ayarlarını yap
    try:
        client.futures_change_leverage(symbol=SYMBOL, leverage=LEVERAGE)
        print(f"{SYMBOL} için kaldıraç {LEVERAGE}x olarak ayarlandı.")
        client.futures_change_margin_type(symbol=SYMBOL, marginType='ISOLATED')
        print(f"{SYMBOL} için marjin türü ISOLATED olarak ayarlandı.")
    except Exception as e:
        print(f"Başlangıç ayarları sırasında hata (zaten ayarlı olabilir): {e}")

    # RSI'ı "ısıtmak" için geçmiş verileri çek
    try:
        print("RSI hesaplaması için geçmiş veriler çekiliyor...")
        klines = client.futures_klines(symbol=SYMBOL, interval=INTERVAL, limit=100)
        for k in klines:
            closes.append(float(k[4]))
        print("Geçmiş veriler başarıyla çekildi.")
    except Exception as e:
        print(f"Geçmiş veri çekilirken hata: {e}")
        return

    ws = websocket.WebSocketApp(TESTNET_SOCKET_URL_FUTURES,
                              on_open=on_open,
                              on_message=on_message,
                              on_close=on_close)
    ws.run_forever()


if __name__ == "__main__":
    main()
