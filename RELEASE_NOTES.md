# Release Notes - v0.0.4

**Release Date:** March 10, 2026

We are excited to announce the latest release of the **IBKR Risk Monitor** (v0.0.4)! 
This lightweight, local web application allows you to monitor your Interactive Brokers (IBKR) portfolio risk, moving average thresholds, and dynamic gains in real-time.

## 🚀 Key Features & Highlights
* **Simplified Installation:** The `README.md` now explicitly includes instructions for users relying on the `.zip` file rather than using `git clone`.
* **OS Python Recommendations:** Explicit recommendations have been added to the instructions to help users pick the most stable Python versions out-of-the-box (Python 3.10+ for Windows, Python 3.9+ for macOS).
* **Position Size Display:** A new "Size" column has been added to the Open Positions table (showing absolute dollar value of the position size based on Avg Cost * Position).
* **Enhanced Order Syncing:** Improved the synchronization of open orders internally (`ib_manager.py`) to fetch a more reliable stream of data.

---

### Previous updates (v0.0.3)
* **Updated Baseline:** The default principal baseline was increased to $100,000 for improved default metric tracking.
* **Account Auto-Detection:** The application automatically retrieves and detects your available managed accounts upon successfully connecting.
* **Auto-Refresh Support:** Toggle the auto-refresh feature in the dashboard sidebar to keep your metrics updated automatically without manual intervention.
* **Refined Dashboard UI:** Beautiful, polished dashboard featuring a uniform blue color scheme for core metric widgets.

## 🛠️ Getting Started
Please refer to the `README.md` for complete prerequisites and installation steps. In brief:
1. Ensure your IBKR TWS/Gateway settings have **"Enable ActiveX and Socket Clients"** checked and **"Read-Only API"** unchecked.
2. Extract the `.zip` file on your computer and navigate to it via terminal.
3. Install dependencies: `pip install -r requirements.txt`
4. Launch the app: `python start_app.py` 

Enjoy tracking your portfolio risk!
