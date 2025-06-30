import websocket
import json
import numpy as np
import pandas as pd
# DÜZELTME: Kütüphanenin yeni yapısına uygun importlar
from pybit.unified_trading import HTTP, WebSocket
import time
import os
import threading

# --- YAPILANDIRMA (Lütfen bu bölümü düzenleyin) ---

# 1. Adım: Bybit Testnet API anahtarlarınızı buraya yapıştırın.
API_KEY = "MZr3w7OFXXDGPdnjXt" 
API_SECRET = "iWpurP32egvhLPqnJIYCBJVjnjnWSGIGzT00"

# 2. Adım: İşlem yapılacak parite ve strateji parametreleri
SYMBOL = 'DOGEUSDT'
LEVERAGE = 10
RSI_PERIOD = 1
RSI_OVERSOLD = 30
TAKE_PROFIT_PCT = 0.10  # %10 kar
STOP_LOSS_PCT = 0.03    # %3 zarar
TRADE_USDT_AMOUNT = 1000  # Her işlemde kullanılacak sanal USDT miktarı
INTERVAL = "1" # 1 dakikalık mumlar için Bybit formatı

# --- BOT KODU (Bu bölümü değiştirmenize gerek yok) ---

# Global Değişkenler
closes = []
in_position = False
session = None

def check_open_positions():
    """Mevcut açık pozisyon olup olmadığını kontrol eder."""
    global in_position
    try:
        # DÜZELTME: Yeni API yapısına uygun pozisyon sorgusu
        positions = session.get_positions(category="linear", symbol=SYMBOL)
        if 'result' in positions and len(positions['result']['list']) > 0 and float(positions['result']['list'][0]['size']) > 0:
             if not in_position:
                 print(f"Mevcut açık pozisyon bulundu: {positions['result']['list'][0]['size']} {SYMBOL}")
             in_position = True
        else:
             if in_position:
                 print("Açık pozisyon yok. Sinyal bekleniyor...")
             in_position = False
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
    
    if loss.iloc[-1] == 0:
        return 100
        
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]

def place_order_with_tp_sl():
    """Alım emri ve ilişkili TP/SL emirlerini yerleştirir."""
    global in_position
    try:
        ticker = session.get_tickers(category="linear", symbol=SYMBOL)
        last_price = float(ticker['result']['list'][0]['lastPrice'])
        
        quantity = str(round(TRADE_USDT_AMOUNT / last_price * LEVERAGE, 3))
        
        tp_price = str(round(last_price * (1 + TAKE_PROFIT_PCT / LEVERAGE), 4))
        sl_price = str(round(last_price * (1 - STOP_LOSS_PCT / LEVERAGE), 4))

        print(f"\n--- YENİ İŞLEM BAŞLATILIYOR ---")
        print(f"Fiyat: {last_price}, Miktar: {quantity} {SYMBOL}")
        print(f"Hedefler: Kâr Al (TP) @ {tp_price}, Zarar Durdur (SL) @ {sl_price}")

        # DÜZELTME: Yeni API yapısına uygun emir verme
        response = session.place_order(
            category="linear",
            symbol=SYMBOL,
            side="Buy",
            orderType="Market",
            qty=quantity,
            takeProfit=tp_price,
            stopLoss=sl_price
        )
        
        if response.get('retMsg') == 'OK' or response.get('retMsg') == '':
            print("Piyasa Alış Emri ve TP/SL hedefleri başarıyla verildi.")
            in_position = True
            print("--- İŞLEM AKTİF, SONUÇ BEKLENİYOR ---\n")
        else:
            print(f"Emir verme sırasında hata: {response.get('retMsg')}")
            in_position = False

    except Exception as e:
        print(f"Emir verme sırasında bir hata oluştu: {e}")
        in_position = False

def handle_message(msg):
    """Websocket'ten gelen her mesajda tetiklenir."""
    global closes
    
    if 'topic' in msg and msg['topic'] == f'kline.{INTERVAL}.{SYMBOL}':
        kline = msg['data'][0]
        is_kline_closed = kline['confirm']
        close_price = float(kline['close'])
        
        if is_kline_closed:
            print(f"Mum kapandı: {close_price}", end=' | ')
            closes.append(close_price)
            if len(closes) > 100:
                closes.pop(0)

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

def main():
    """Botun ana çalışma fonksiyonu."""
    global session
    print("Bybit Testnet Botu başlatılıyor (Güncel Sürüm)...")

    if "SENİN_BYBIT_TESTNET_API_ANAHTARIN" in API_KEY or "SENİN_BYBIT_TESTNET_GİZLİ_ANAHTARIN" in API_SECRET:
        print("\n!!! UYARI: Lütfen kodun içindeki API_KEY ve API_SECRET alanlarını kendi Bybit Testnet anahtarlarınızla güncelleyin.\n")
        return

    # DÜZELTME: Yeni API yapısına uygun oturum başlatma
    session = HTTP(testnet=True, api_key=API_KEY, api_secret=API_SECRET)
    ws = WebSocket(testnet=True, channel_type="linear", api_key=API_KEY, api_secret=API_SECRET)
    
    # Başlangıçta kaldıraç ayarını yap
    try:
        session.set_leverage(category="linear", symbol=SYMBOL, buyLeverage=str(LEVERAGE), sellLeverage=str(LEVERAGE))
        print(f"{SYMBOL} için kaldıraç {LEVERAGE}x olarak ayarlandı.")
    except Exception as e:
        print(f"Kaldıraç ayarlanırken hata (zaten ayarlı olabilir): {e}")

    # RSI'ı "ısıtmak" için geçmiş verileri çek
    try:
        print("RSI hesaplaması için geçmiş veriler çekiliyor...")
        klines = session.get_kline(category="linear", symbol=SYMBOL, interval=INTERVAL, limit=100)['result']['list']
        # Bybit verileri ters sırada verir, düzeltelim
        klines.reverse()
        for k in klines:
            closes.append(float(k[4])) # Kapanış fiyatı 4. index'te
        print("Geçmiş veriler başarıyla çekildi.")
    except Exception as e:
        print(f"Geçmiş veri çekilirken hata: {e}")
        return

    # Periyodik pozisyon kontrolü için thread başlat
    def position_check_loop():
        while True:
            check_open_positions()
            time.sleep(10)

    checker_thread = threading.Thread(target=position_check_loop, daemon=True)
    checker_thread.start()

    # Kline verilerini dinle
    ws.kline_stream(
        callback=handle_message,
        symbol=SYMBOL,
        interval=INTERVAL,
    )

    print("Bağlantı kuruldu. Sinyal bekleniyor...")
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
