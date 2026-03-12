# Release Notes - v0.0.11

**Release Date:** March 12, 2026

## 📊 New Portfolio Visualization
* **Position Exposure & Risk Chart:** Added a high-end visual dashboard below the positions table.
    * **Stacked Bar Design:** Displays total position value (exposure) vs. Market's Money (active risk) at a glance.
    * **Proportional Scaling:** Automatically scales heights based on your largest position for clear portfolio weighting.
    * **ADR Labels:** Each bar is labeled with its corresponding ADR (Average Daily Range) for quick volatility reference.
    * **Interactive Tooltips:** Deep dive into specific values, risk, and percentages by hovering over bars.
* **Unified Legend & Axes:** Added clear color-coded legends and descriptive axis labels (Exposure $ vs Positions) to the chart.
* **Privacy Mode Integration:** Visual scale maximums and sensitive data are now masked when Privacy Mode is active.

## ⚡ Smart Organization
* **Automated Descending Sort:** Positions are now automatically sorted by **Market Value** (descending) across the entire app.
    * The table now presents your крупнейший (largest) exposure first.
    * The chart follows the same order from left to right, providing a clear visual hierarchy of your capital allocation.

## 🎨 UI Polish
* **Refined Spacing:** Optimized axis label positions and container dimensions for a more compact and balanced layout.
* **Themed Styling:** Styled "ADR" references throughout the chart to match the main table's purple color palette.

---

# Release Notes - v0.0.10

**Release Date:** March 12, 2026

## ✨ UI & Dashboard Improvements
* **Hero Section Overhaul:** Redesigned the top stats bar with a more logical grouping. Financial metrics (Net Liquidation, Total Market's Money) are grouped on the left, while "System Risk Monitor" (Open Risk, Safety Buffer, and Risk Coverage Ratio) is unified on the right.
* **Consistent Typography:** Normalized sizing (text-5xl/6xl) across all core metrics and matched label colors with the StatCard theme for a professional, integrated look.
* **Collapsible Navigator:** The sidebar is now collapsible, allowing for a cleaner dashboard view while retaining access to core settings.
* **Refined Layout Logic:** Improved spacing and grouping to visually communicate the relationship between risk metrics and safety buffers.

## 📱 Responsiveness & Stability
* **Responsive Tables:** Added horizontal scrolling to the Open Positions table, ensuring it remains fully functional on smaller laptop screens (e.g., 16" notebooks).
* **Viewport Overflow Fix:** Resolved a layout bug where the sidebar would conflict with the main content's centering, causing unwanted scrollbars and overlapping.
* **Icon Consistency:** Fixed various sidebar and title bar icons that were previously showing as circle fallbacks.

---

### Previous updates (v0.0.9)

**Release Date:** March 11, 2026

## 📖 Documentation Improvements

* **Read-Only API Explained:** The `README.md` now includes a clear explanation of *why* the "Read-Only API" checkbox must be unchecked in TWS — even though the app never trades. The app calls `reqAllOpenOrders` on every data refresh to read existing stop-loss orders and display correct stop prices. TWS blocks this under read-only mode because it treats order retrieval as the first step of order management.
* **Trusted IPs Setup:** Added step-by-step instructions for configuring the Trusted IP Addresses list in TWS (`127.0.0.1`), including a note about the connection approval pop-up.
* **Corrected Navigation Path:** The TWS settings path is now precisely documented as **Edit > Global Configuration > API > Settings**.

**Release Date:** March 11, 2026

We are excited to announce the latest release of the **IBKR Risk Monitor** (v0.0.8)! 
This lightweight, local web application allows you to monitor your Interactive Brokers (IBKR) portfolio risk, moving average thresholds, and dynamic gains in real-time.

## 🚀 Key Features & Highlights
* **Enhanced UI Table:** All columns in the Open Positions table are now center-aligned for better visual clarity.
* **Risk Prioritization:** Reordered the risk columns so "PS Risk" (Principal Protection) appears alongside core PnL metrics, emphasizing principal safety first.
* **"Market's Money" Info:** Added a clear tooltip explaining that "Market Risk" represents the portion of your portfolio value currently exposed to market volatility.
* **Favicon & Icons:** Added a custom favicon to the web interface and bundled `app_icon.ico` for the executable.
* **Accurate Size Percentage:** The "Size %" column now calculates your position weight relative to your **Principal State**, providing a more realistic view of allocation against your "real" own capital.
* **Stability Fixes:** Improved internal data alignments for more consistent metric tracking.

---

### Previous updates (v0.0.7)
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
