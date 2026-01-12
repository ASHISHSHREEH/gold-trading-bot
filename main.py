import matplotlib.pyplot as plt
from data.fetcher import GoldDataFetcher
from indicators.rsi import RSICalculator

def main():
    print("--- Hybrid Gold Bot (MetalPriceAPI + yfinance) ---")

    # 1. Initialize
    fetcher = GoldDataFetcher()
    rsi_tool = RSICalculator(period=14)

    # 2. Validate
    if not fetcher.validate_connection():
        print("Error: Could not connect to data sources.")
        return

    # 3. Fetch Historical Data (for RSI)
    # Yahoo provides the history we need for indicators
    print("Fetching historical data from yfinance...")
    df = fetcher.get_historical_data(period='1mo', interval='1h')

    if df.empty:
        print("No historical data found.")
        return

    # 4. Calculate RSI
    df['rsi'] = rsi_tool.calculate_rsi(df)
    
    # 5. Get Real-Time Spot Price (for accuracy)
    # MetalPriceAPI is better for the *current* price than Yahoo
    print("Checking live spot price from MetalPriceAPI...")
    live_price = fetcher.get_current_price()
    
    # 6. Analysis
    latest_analysis = rsi_tool.analyze_latest(df)
    
    print("\n" + "="*30)
    print(" ANALYSIS REPORT")
    print("="*30)
    print(f"Time (History): {df.index[-1]}")
    print(f"Yahoo Close:    {df['close'].iloc[-1]:.2f} (Used for RSI)")
    
    if live_price:
        print(f"Live Spot Price: {live_price:.2f} (MetalPriceAPI)")
    else:
        print("Live Spot Price: Unavailable")
        
    print(f"RSI (14):       {latest_analysis['rsi']}")
    print(f"Signal:         {latest_analysis['signal']}")
    print("="*30)

    # 7. Plotting
    print("\nDisplaying chart...")
    plt.style.use('bmh')
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

    ax1.plot(df.index, df['close'], label='Price (Yahoo)')
    ax1.set_title('Gold Price (Source: yfinance)')
    ax1.legend()

    ax2.plot(df.index, df['rsi'], label='RSI', color='purple')
    ax2.axhline(70, color='red', linestyle='--', alpha=0.5)
    ax2.axhline(30, color='green', linestyle='--', alpha=0.5)
    ax2.set_title('RSI Indicator')
    
    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    main()