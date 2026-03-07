# IBKR Risk Monitor

A lightweight, local web application to monitor your Interactive Brokers (IBKR) portfolio risk, moving average thresholds, and dynamic gains in real-time.

## Prerequisites

- **Python 3.8+** installed on your machine (Windows or macOS).
- **Interactive Brokers TWS or IB Gateway** installed and running locally.
- In TWS/Gateway settings:
  - Go to **API > Settings**.
  - Enable **"Enable ActiveX and Socket Clients"**.
  - Uncheck **"Read-Only API"**.
  - Note the **Socket port** (default is usually 7496 for Live, 7497 for Paper).

## Installation

1. Clone this repository to your local machine:
   ```bash
   git clone https://github.com/anderpioner/IBKRmonitoring.git
   cd IBKRmonitoring
   ```

2. Create a virtual environment using Python's built-in `venv` module (recommended):
   ```bash
   python3 -m venv venv
   
   # On Windows:
   venv\Scripts\activate
   
   # On macOS/Linux:
   source venv/bin/activate
   ```

3. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Running the Application

1. Ensure TWS or IB Gateway is open and logged in.
2. Run the application:
   ```bash
   # On Windows:
   python start_app.py

   # On macOS/Linux:
   python3 start_app.py
   ```
3. Open your web browser and navigate to the Dashboard URL shown in the console (usually `http://localhost:8000/ui/index.html`).

## Usage

* **Connection Setup**: In the left sidebar of the web UI, ensure your IBKR Port matches your TWS/Gateway settings (7496 or 7497) and click **Connect**.
* **Account Auto-Detection**: The app will automatically detect your account ID once connected.
* **Auto-Refresh**: You can enable auto-refresh in the sidebar to keep your dashboard updated with real-time risk metrics.
* **MA Periods**: Toggle between 10-day and 20-day Moving Average calculations to adjust your threshold settings.

## Disclaimer

This is a local monitoring tool and does not execute trades. Use at your own risk. Always verify metrics within standard TWS interfaces.
