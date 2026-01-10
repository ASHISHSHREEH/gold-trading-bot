# Gold Trading Bot

AI-powered gold (XAU/JPY) trading bot using technical indicators, trend following strategies, and OANDA API.

## Project Status
🚧 **In Development** - Phase 1: Data Pipeline Setup

## Features (Planned)
- ✅ OANDA API integration for real-time gold price data
- 🔄 Technical indicators (RSI, MACD, Moving Averages, Bollinger Bands)
- 🔄 Trend following strategies
- 🔄 Paper trading mode for testing
- 🔄 Risk management system
- 🔄 PostgreSQL database for historical data
- 🔄 AI-powered analysis using Google Gemini

## Setup Instructions

### 1. Prerequisites
- Python 3.10 or higher
- PostgreSQL (already set up on D: drive)
- Git
- OANDA practice account (free)

### 2. Installation

```bash
# Navigate to project directory
cd /d/My\ projects/gold-trading-bot

# Install dependencies
pip install -r requirements.txt
```

### 3. OANDA Account Setup

1. Create a free practice account at https://www.oanda.com/
2. Log in and go to "Manage API Access"
3. Generate a Personal Access Token
4. Copy your Account ID (format: xxx-xxx-xxxxxxxx-xxx)

### 4. Environment Configuration

```bash
# Copy the example .env file
cp .env.example .env

# Edit .env with your credentials
notepad .env
```

Add your credentials:
```
OANDA_API_KEY=your_actual_api_token_here
OANDA_ACCOUNT_ID=your_actual_account_id_here
OANDA_ENVIRONMENT=practice

DATABASE_URL=postgresql://username:password@localhost:5432/trading_db
```

### 5. Test the Data Fetcher

```bash
# Test OANDA connection
cd data
python fetcher.py
```

Expected output:
```
INFO - OANDA Client initialized in practice mode.
INFO - API connection validated successfully.
Successfully connected to OANDA!
INFO - Fetching 5 H1 candles for XAU_JPY...
```

## Project Structure

```
gold-trading-bot/
├── data/
│   └── fetcher.py          # OANDA API data fetcher ✅
├── indicators/             # Technical indicators (TODO)
├── strategies/             # Trading strategies (TODO)
├── trading/                # Paper/live trading logic (TODO)
├── backtesting/            # Strategy backtesting (TODO)
├── monitoring/             # Performance monitoring (TODO)
├── ai_integration/         # Gemini AI integration (TODO)
├── .env                    # Your secrets (NOT in Git)
├── .env.example           # Template (safe to commit)
├── requirements.txt        # Python dependencies
└── README.md              # This file
```

## Development Workflow

### Daily Development
```bash
# Start of session
cd /d/My\ projects/gold-trading-bot
git pull

# ... make changes ...

# End of session
git add .
git commit -m "Descriptive message"
git push
```

### Using Multiple AIs
1. **Claude (me)**: Architecture, design, code review
2. **Gemini**: Code generation, implementation
3. **Workflow**: Claude designs → Gemini implements → Claude reviews

## Next Steps

### Phase 1: Data Foundation ✅
- [x] Set up project structure
- [x] Create OANDA data fetcher
- [ ] Test with real API credentials
- [ ] Set up PostgreSQL database schema
- [ ] Create data storage module

### Phase 2: Technical Indicators (Week 1-2)
- [ ] Implement RSI calculator
- [ ] Implement MACD calculator
- [ ] Implement Moving Averages
- [ ] Implement Bollinger Bands
- [ ] Add unit tests

### Phase 3: Basic Strategy (Week 2)
- [ ] Design simple rule-based strategy
- [ ] Implement signal generation
- [ ] Add backtesting framework

### Phase 4: Paper Trading (Week 3)
- [ ] Create virtual account system
- [ ] Implement order simulator
- [ ] Add performance tracking
- [ ] Create monitoring dashboard

### Phase 5: Risk Management (Week 3-4)
- [ ] Stop loss automation
- [ ] Position sizing rules
- [ ] Maximum drawdown protection
- [ ] Daily loss limits

## Important Notes

⚠️ **Security**
- Never commit `.env` file to Git
- Keep API keys secret
- Use practice account for testing

⚠️ **Risk Warning**
- This is for educational purposes
- Always test strategies thoroughly before live trading
- Past performance doesn't guarantee future results
- Only trade with money you can afford to lose

## Resources

- [OANDA API Documentation](https://developer.oanda.com/rest-live-v20/introduction/)
- [oandapyV20 Library](https://oanda-api-v20.readthedocs.io/)
- [Technical Analysis Library](https://technical-analysis-library-in-python.readthedocs.io/)

## Contact

- GitHub: [@ASHISHSHREEH](https://github.com/ASHISHSHREEH)
- Project: [gold-trading-bot](https://github.com/ASHISHSHREEH/gold-trading-bot)

## License

This project is for educational purposes only.