# Release Notes - v0.0.3

**Release Date:** March 7, 2026

We are excited to announce the latest release of the **IBKR Risk Monitor** (v0.0.3)! 
This lightweight, local web application allows you to monitor your Interactive Brokers (IBKR) portfolio risk, moving average thresholds, and dynamic gains in real-time.

## 🚀 Key Features & Highlights
* **Updated Baseline:** The default principal baseline has been increased to $100,000 for improved default metric tracking.
* **Real-time Monitoring Framework:** Connect directly to your local IBKR TWS or IB Gateway to monitor your portfolio seamlessly.
* **Account Auto-Detection:** The application automatically retrieves and detects your available managed accounts upon successfully connecting.
* **Editable Account ID:** While auto-detection is supported, you can manually review and edit your Account ID directly from the UI.
* **Auto-Refresh Support:** Toggle the auto-refresh feature in the dashboard sidebar to keep your metrics updated automatically without manual intervention.
* **Dynamic MA Thresholds:** Toggle between 10-day and 20-day Moving Average calculations to adjust your risk threshold settings on the fly.
* **Refined Dashboard UI:** Beautiful, polished dashboard featuring a uniform blue color scheme for core metric widgets (Net Liquidation, Market Value, Cash) for improved readability.
* **Cross-Platform Compatibility:** Simple startup script (`start_app.py`) for both Windows and macOS/Linux environments, combined with standard Python `venv` support.

## 🛠️ Getting Started
Please refer to the `README.md` for complete prerequisites and installation steps. In brief:
1. Ensure your IBKR TWS/Gateway settings have **"Enable ActiveX and Socket Clients"** checked and **"Read-Only API"** unchecked.
2. Install dependencies: `pip install -r requirements.txt`
3. Launch the app: `python start_app.py` 

Enjoy tracking your portfolio risk!
