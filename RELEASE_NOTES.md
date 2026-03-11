# Release Notes - v0.0.7

**Release Date:** March 11, 2026

We are excited to announce the latest release of the **IBKR Risk Monitor** (v0.0.7)! 
This lightweight, local web application allows you to monitor your Interactive Brokers (IBKR) portfolio risk, moving average thresholds, and dynamic gains in real-time.

## 🚀 Key Features & Highlights
* **Privacy Mode:** Added a new privacy toggle to hide sensitive monetary values from the dashboard securely.
* **Principal State (PS) Risk Calculation:** Added a dedicated "PS Risk" column to monitor risk strictly tied to your allocated principal. It dynamically drops to zero when your Stop Price or Moving Average exit exceeds or protects your Average Cost, indicating your initial capital is completely safe.
* **Total PS Risk Interface:** A new dashboard statistics card has been added to display the aggregated risk of your initial principal across all open positions.
* **Capital Allocation Visualization:** You can now toggle the display of the principal state to show as a percentage.

---

### Previous updates (v0.0.6)
* **Public GitHub Release:** The project is now available on GitHub! The `README.md` has been overhauled with better instructions for cloning the repo or downloading the latest Zip, with clear split instructions for Windows CMD/PowerShell vs Mac Terminals.
* **Application Icon Fixes:** The correct custom application icon is now perfectly bundled and rendered inside the title bar and taskbars on Windows when executing it.
* **Intelligent Stop Prices:** Refined Logic for auto-suggesting Stop Prices. If manually deleted, the field won't stubbornly refill, allowing power users more granular control. Only re-engages automatically when Entry Price or ATR limits are toggled.
* **Cleaned Caches:** Temporary debugging files and metric caches have been unlinked from version control to prevent conflicts.

---

### Previous updates (v0.0.4)
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
