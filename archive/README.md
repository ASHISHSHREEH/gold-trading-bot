# archive/

Old code from before the MT5 rewrite. **Do not import from these files.**

| File | Why archived |
|------|-------------|
| `main.py` | v1 bot — used yfinance + paper trading, no MT5 |
| `main_integrated.py` | v1.1 integrated paper trading bot |
| `main_integrated_backup.py` | Backup of the above |
| `test_bot.py` | Test runner for old main.py |
| `data/fetcher.py` | yfinance data fetcher — replaced by `data/mt5_fetcher.py` |
| `trading/position_manager.py` | Paper position manager — replaced by `trading/mt5_position_manager.py` |
| `trading/risk_manager.py` | Paper risk manager — logic moved into `trading/mt5_executor.py` |
| `trading/trade_executor.py` | Paper trade executor — replaced by `trading/mt5_executor.py` |
| `trading/trade_logger.py` | CSV trade logger — replaced by `database/trade_logger.py` |
| `database/schema.py` | Old SQLite schema — replaced by `database/trade_logger.py` |
| `indicators/import pandas as pd.py` | Misnamed file, broken |

## What replaced them

| Old | New (active) |
|-----|-------------|
| `data/fetcher.py` (yfinance) | `data/mt5_fetcher.py` (FxPro MT5 live feed) |
| `trading/trade_executor.py` | `trading/mt5_executor.py` |
| `trading/position_manager.py` | `trading/mt5_position_manager.py` |
| `database/schema.py` | `database/trade_logger.py` |
| `main.py` / `main_integrated.py` | `main_mt5.py` |
