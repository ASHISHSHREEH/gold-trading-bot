"""
Test Script for Gold Trading Bot.
Runs the main bot logic exactly ONCE to verify configuration and data fetching.
"""

import main

if __name__ == "__main__":
    print("🧪 STARTING BOT TEST MODE (Single Execution)...")
    
    # Force the configuration to Single Run Mode
    main.RUN_ONCE = True
    
    # Run the main function
    main.main()
    
    print("✅ Test execution finished.")