# IBKR Risk Monitor

A lightweight, local web application to monitor your Interactive Brokers (IBKR) portfolio risk, moving average thresholds, and dynamic gains in real-time.

## Prerequisites

- **Python 3.8+** installed on your machine.
  - **Windows users:** Python 3.10+ is recommended.
  - **macOS users:** Python 3.9+ is recommended.
- **Interactive Brokers TWS or IB Gateway** installed and running locally.
- In TWS/Gateway settings, go to **Edit > Global Configuration > API > Settings**:
  - Enable **"Enable ActiveX and Socket Clients"**.
  - Uncheck **"Read-Only API"**.
    > **Why is this required?** Even though this app never places or modifies orders, it calls `reqAllOpenOrders` on every data refresh to read your existing stop-loss orders and display their stop prices correctly. TWS blocks this call when Read-Only API is enabled — because retrieving open orders also "binds" them to the client session, which TWS considers an order-management operation. Without unchecking this option, stop prices will not appear in the dashboard.
  - **Trusted IPs**: In the **Trusted IP Addresses** list, add `127.0.0.1` (this is the loopback address, meaning the app running on the same machine). Click **+** to add it, then **OK**. If you ever see a TWS pop-up asking *"Allow connection from..."*, click **Yes** and it will be remembered.
  - Note the **Socket port** (default is **7496** for Live accounts, **7497** for Paper Trading).

## Installation

### Option 1: Download ZIP (Recommended for beginners)
1. Extract the provided `IBKRmonitoring-v0.0.8.zip` file to a folder on your computer.
2. Open a terminal (Command Prompt/PowerShell on Windows, Terminal on macOS) and navigate into the extracted folder:
   ```bash
   cd path/to/extracted/IBKRmonitoring
   ```

### Option 2: Clone via Git
Open a terminal and run:
```bash
git clone https://github.com/anderpioner/IBKRmonitoring.git
cd IBKRmonitoring
```

## Setup & Running

1. **Create a virtual environment (Recommended):**
   ```bash
   # On Windows:
   python -m venv venv
   venv\Scripts\activate
   
   # On macOS/Linux:
   python3 -m venv venv
   source venv/bin/activate
   ```

2. **Install the required dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Ensure TWS or IB Gateway is open and logged in.**

4. **Run the application:**
   ```bash
   # On Windows:
   python start_app.py

   # On macOS/Linux:
   python3 start_app.py
   ```

5. Open your web browser and navigate to the Dashboard URL shown in the console (usually `http://localhost:8000/ui/index.html`).

## Usage

* **Connection Setup**: In the left sidebar of the web UI, ensure your IBKR Port matches your TWS/Gateway settings (7496 or 7497) and click **Connect**.
* **Account Auto-Detection**: The app will automatically detect your account ID once connected.
* **Auto-Refresh**: You can enable auto-refresh in the sidebar to keep your dashboard updated with real-time risk metrics.
* **MA Periods**: Toggle between 10-day and 20-day Moving Average calculations to adjust your threshold settings.

## Disclaimer

This is a local monitoring tool and does not execute trades. Use at your own risk. Always verify metrics within standard TWS interfaces.
