import matplotlib.pyplot as plt
from data.fetcher import GoldDataFetcher
from indicators.rsi import RSICalculator
from indicators.macd import MACDCalculator

def main():
    print("--- Advanced Gold Bot (RSI + MACD) ---")

    # 1. Initialize
    fetcher = GoldDataFetcher()
    rsi_tool = RSICalculator(period=14)
    macd_tool = MACDCalculator(fast_period=12, slow_period=26, signal_period=9)

    # 2. Fetch Data
    print("Fetching historical data...")
    df = fetcher.get_historical_data(period='1mo', interval='1h')
    
    if df.empty:
        print("Error: No data found.")
        return

    # 3. Calculate Indicators
    # RSI
    df['rsi'] = rsi_tool.calculate_rsi(df)
    
    # MACD (Returns a new DataFrame, so we concat or just inspect it)
    macd_results = macd_tool.calculate_macd(df)
    df = df.join(macd_results) # Joins 'macd', 'signal', 'histogram' to main df

    # 4. Analyze Latest Candle
    latest_rsi = rsi_tool.analyze_latest(df)
    latest_macd = macd_tool.analyze_latest(macd_results)

    # 5. Combined Strategy Logic (Confluence)
    final_action = "WAIT"
    
    # Example Strategy: BUY if RSI < 30 AND MACD is Bullish
    if latest_rsi['signal'] == 'BUY' and latest_macd['signal'] == 'BUY':
        final_action = "STRONG BUY 🚀"
    elif latest_rsi['signal'] == 'SELL' and latest_macd['signal'] == 'SELL':
        final_action = "STRONG SELL 🔻"
    else:
        final_action = "NEUTRAL / CONFLICTING SIGNALS"

    # 6. Report
    print("\n" + "="*40)
    print(f" ANALYSIS REPORT ({df.index[-1]})")
    print("="*40)
    print(f"Price:      {df['close'].iloc[-1]:.2f}")
    print("-" * 20)
    print(f"RSI (14):   {latest_rsi['rsi']:.2f} -> {latest_rsi['signal']}")
    print(f"MACD:       {latest_macd['message']}")
    print("-" * 20)
    print(f"FINAL DECISION: {final_action}")
    print("="*40)

    # 7. Plotting
    print("\nDisplaying chart...")
    plt.style.use('bmh')
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 10), sharex=True)

    # Price
    ax1.plot(df.index, df['close'], label='Price')
    ax1.set_title('Gold Price')
    
    # RSI
    ax2.plot(df.index, df['rsi'], color='purple', label='RSI')
    ax2.axhline(70, color='red', linestyle='--')
    ax2.axhline(30, color='green', linestyle='--')
    ax2.set_title('RSI')

    # MACD
    ax3.plot(df.index, df['macd'], label='MACD Line', color='blue')
    ax3.plot(df.index, df['signal'], label='Signal Line', color='orange')
    # Bar chart for Histogram
    colors = ['green' if v >= 0 else 'red' for v in df['histogram']]
    ax3.bar(df.index, df['histogram'], color=colors, alpha=0.3)
    ax3.set_title('MACD')
    ax3.legend()

    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    main()