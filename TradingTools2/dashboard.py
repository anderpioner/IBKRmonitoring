import streamlit as st
import pandas as pd
import asyncio

# Fix for "RuntimeError: There is no current event loop in thread"
# We must ensure an event loop exists before importing ib_insync (which depends on eventkit)
try:
    asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

from ib_insync import *
from datetime import datetime
import time

# Setup ib_insync for Streamlit/Asyncio compatibility
util.patchAsyncio()

# --- Page Config ---
st.set_page_config(page_title="IBKR Portfolio Momentum Tracker", layout="wide", page_icon="📈")

# --- Custom Styling ---
st.markdown("""
    <style>
    .metric-card {
        background-color: #1e1e1e;
        padding: 20px;
        border-radius: 10px;
        border: 1px solid #333;
        margin-bottom: 10px;
    }
    .risk-monitor-card {
        background: linear-gradient(135deg, #1a2a4a 0%, #0f172a 100%);
        border: 1px solid rgba(59, 130, 246, 0.3);
        color: white;
        padding: 24px;
        border-radius: 16px;
        margin: 20px 0;
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.3), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
        position: relative;
        overflow: hidden;
    }
    .risk-monitor-card::before {
        content: "";
        position: absolute;
        top: 0; left: 0; right: 0; height: 2px;
        background: linear-gradient(90deg, transparent, #3b82f6, transparent);
    }
    .level-container {
        margin-top: 25px;
        background: rgba(15, 23, 42, 0.8);
        border-radius: 999px;
        height: 10px;
        position: relative;
        border: 1px solid #334155;
    }
    .level-fill {
        height: 100%;
        border-radius: 999px;
        transition: width 0.8s cubic-bezier(0.4, 0, 0.2, 1);
        box-shadow: 0 0 10px var(--glow-color);
    }
    .marker-label {
        position: absolute;
        top: 15px;
        font-size: 10px;
        color: #64748b;
        transform: translateX(-50%);
        white-space: nowrap;
    }
    .marker-tick {
        position: absolute;
        top: -4px;
        width: 1px;
        height: 18px;
        background: #334155;
    }
    .risk-label {
        font-size: 0.8rem;
        color: #94a3b8;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 4px;
    }
    .metric-grid {
        display: grid;
        grid-template-columns: 1fr 1fr 1fr;
        gap: 15px;
        margin-bottom: 10px;
    }
    .metric-value-large {
        font-size: 1.6rem;
        font-weight: 800;
        font-family: 'Inter', sans-serif;
    }
    .status-pill {
        font-size: 0.75rem;
        font-weight: 700;
        padding: 4px 12px;
        border-radius: 999px;
        text-transform: uppercase;
        letter-spacing: 0.02em;
        display: flex;
        align-items: center;
        gap: 6px;
    }
    .metric-label {
        color: #888;
        font-size: 14px;
    }
    /* Normalize sidebar button heights */
    [data-testid="stSidebar"] .stButton button {
        height: 3rem;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    </style>
""", unsafe_allow_html=True)

# --- Session State Initialization ---
if 'ib_connected' not in st.session_state:
    st.session_state.ib_connected = False
if 'last_fetch' not in st.session_state:
    st.session_state.last_fetch = datetime.now()

# --- Sidebar Configuration ---
st.sidebar.header("Configuration")
principal_baseline = st.sidebar.number_input("Principal Baseline ($)", value=83000, step=500)
account_id = st.sidebar.text_input("Account ID", value="U2753907")
stop_strategy = st.sidebar.selectbox("Stop Strategy", ["TWS Orders", "Manual 5% (Fallback)"])

with st.sidebar.expander("Refresh Settings", expanded=True):
    auto_refresh = st.toggle("Auto-Refresh", value=True)
    refresh_interval = st.slider("Interval (seconds)", 5, 60, 60)

with st.sidebar.expander("Connection Settings", expanded=not st.session_state.ib_connected):
    tws_host = st.text_input("TWS Host", value="127.0.0.1")
    tws_port = st.number_input("TWS Port", value=7496, step=1)
    client_id = st.number_input("Client ID", value=10, step=1)

# --- IB Connection Management ---
@st.cache_resource
def get_ib_connection(host, port, base_client_id):
    """
    Handles TWS connection logic with automatic retry for Client ID conflicts.
    """
    # Try up to 3 different client IDs if they are locked
    for attempt in range(3):
        current_client_id = base_client_id + attempt
        ib = IB()
        try:
            # 1. Attempt connection
            ib.connect(host, port, clientId=current_client_id, timeout=10)
            
            # 2. Initialize subscriptions
            ib.reqAccountSummary()
            ib.reqPositions()
            ib.reqAllOpenOrders()
            
            if attempt > 0:
                st.sidebar.info(f"ℹ️ Connected using Client ID Fallback: {current_client_id}")
            
            return ib
        except Exception as e:
            error_msg = str(e)
            if any(x in error_msg for x in ["326", "already in use", "clientId already in use"]):
                if attempt < 2: # Keep trying if we have attempts left
                    if ib.isConnected():
                        ib.disconnect()
                    continue
                else:
                    st.error(f"🔌 Connection Error: Client ID {current_client_id} is already in use. Exhausted retries.")
                    st.warning("⚠️ Try using a completely different Client ID in Connection Settings.")
            else:
                st.error(f"🔌 Connection Error: {error_msg}")
                if "10061" in error_msg:
                    st.info("💡 TWS is likely closed or the API port is wrong.")
            
            if ib.isConnected():
                ib.disconnect()
            return None
    return None

def get_safe_ib(host, port, client_id):
    """
    Returns the cached connection if connected. 
    If not connected, or if it raises a loop error, it resets the cache.
    """
    ib = get_ib_connection(host, port, client_id)
    if ib and not ib.isConnected():
        st.cache_resource.clear()
        return get_ib_connection(host, port, client_id)
    return ib

# Sidebar Connection Controls
st.sidebar.divider()
if not st.session_state.ib_connected:
    if st.sidebar.button("🔌 Connect to TWS", use_container_width=True):
        # Explicitly clear resource to force a fresh connection attempt
        st.cache_resource.clear()
        ib = get_safe_ib(tws_host, tws_port, client_id)
        if ib and ib.isConnected():
            st.session_state.ib_connected = True
            st.rerun()
        else:
            st.sidebar.error("Could not connect. Check TWS/Gateway.")
else:
    col_ref, col_disc = st.sidebar.columns(2)
    if col_ref.button("🔄 Refresh", use_container_width=True):
        st.cache_data.clear() # Clear MA20 cache
        st.rerun()
    if col_disc.button("🚫 Disconnect", use_container_width=True):
        # 1. Explicitly disconnect the cached resource
        try:
            ib = get_safe_ib(tws_host, tws_port, client_id)
            if ib:
                ib.disconnect()
                # Give a small pause for TWS to register the disconnect
                time.sleep(0.5)
        except:
            pass
        
        # 2. Clear all Streamlit caches to free the Client ID
        st.cache_resource.clear()
        st.cache_data.clear()
        
        # 3. Reset state
        st.session_state.ib_connected = False
        st.rerun()

# Debug Info (Optional, but helpful for user)
if st.sidebar.checkbox("Show Connection Debug"):
    if st.session_state.ib_connected:
        st.sidebar.write("✅ State: Connected")
        ib = get_safe_ib(tws_host, tws_port, client_id)
        if ib:
            st.sidebar.write(f"Socket: {ib.isConnected()}")
            st.sidebar.write(f"Client ID: {client_id}")
    else:
        st.sidebar.write("❌ State: Disconnected")

if st.sidebar.button("🆘 Emergency App Reset", use_container_width=True, help="Clears all caches and forces a full reconnection. Use if the app hangs."):
    # Attempt a clean disconnect first if possible
    try:
        ib = get_safe_ib(tws_host, tws_port, client_id)
        if ib:
            ib.disconnect()
    except:
        pass
    
    st.cache_resource.clear()
    st.cache_data.clear()
    if 'last_fetch_time' in st.session_state:
        del st.session_state.last_fetch_time
    st.session_state.ib_connected = False
    st.rerun()

# --- Logic & Metric Calculations ---
async def fetch_portfolio_data(ib, account_id, stop_strategy, status_placeholder=None):
    # Resilient lock with short auto-expiration for fast refreshes
    now = time.time()
    if 'last_fetch_time' in st.session_state:
        if now - st.session_state.last_fetch_time < 5: # Faster lock for fast updates
            return {"status": "InProgress", "message": "Fetch already in progress."}
    
    st.session_state.last_fetch_time = now
    try:
        if not ib or not ib.isConnected():
            return {"status": "Disconnected", "message": "IB is not connected."}

        # 1. Sync local cache with background data thread
        # This yields to the event loop and processes pending IB messages
        await asyncio.sleep(0.05)
        ib.waitOnUpdate(0.05) 

        target_acc = str(account_id).strip().upper()
        
        # Process pending events
        await asyncio.sleep(0.1)
        
        # 1. Get Account Summary Data
        # These are synchronous lookups on the current state
        summary = ib.accountSummary()
        acc_summary = [item for item in summary if item.account.upper() == target_acc]
        
        if not acc_summary:
            acc_summary = [v for v in ib.accountValues() if v.account.upper() == target_acc]

        if not acc_summary:
            all_accounts = list(set(item.account for item in summary))
            if not all_accounts:
                all_accounts = list(set(v.account for v in ib.accountValues()))
            
            return {
                "status": "NoData",
                "message": f"No data found for account '{target_acc}'.",
                "available": all_accounts
            }

        net_liquidation = 0.0
        cash = 0.0
        
        for item in acc_summary:
            if item.tag == 'NetLiquidation':
                try: net_liquidation = float(item.value)
                except: pass
            if item.tag in ['TotalCashValue', 'CashBalance', 'SettledCash', 'TotalCashBalance']:
                try: cash = float(item.value)
                except: pass

        # 2. Positions & Subscriptions
        # Only do heavy work (qualification/subscription) for NEW positions
        all_positions = ib.positions()
        positions = [p for p in all_positions if p.account.upper() == target_acc]
        
        # Sync subscriptions with the current connection's ticker list
        active_tickers = {t.contract.conId for t in ib.tickers()}
        new_contracts = [p.contract for p in positions if p.contract.conId not in active_tickers]
        
        if new_contracts:
            if status_placeholder:
                status_placeholder.caption(f"🆕 Initializing {len(new_contracts)} new positions...")
            
            ib.reqMarketDataType(3)
            await ib.qualifyContractsAsync(*new_contracts)
            for contract in new_contracts:
                # Start persistent background stream
                ib.reqMktData(contract, '', False, False)
            
            # Allow a tiny bit of time for first-time data to arrive
            await asyncio.sleep(0.3)

        # 3. Open Risk & Historical Metrics Calculation
        total_open_risk = 0.0
        threshold_gains = 0.0
        total_unrealized_pnl = 0.0
        total_market_value = 0.0
        position_data = []
        
        # Optimized MA20 with Session State Caching & Throttling
        if 'ma20_cache' not in st.session_state:
            st.session_state.ma20_cache = {}

        # Semaphore to avoid IBKR pacing violations and hanging
        # Historical data is strictly limited to 3 concurrent requests
        hist_semaphore = asyncio.Semaphore(3)

        async def fetch_ma20_step(contract):
            cid = contract.conId
            # Only fetch if not cached or cache is older than 1 hour
            if cid in st.session_state.ma20_cache:
                val, ts = st.session_state.ma20_cache[cid]
                if (datetime.now() - ts).total_seconds() < 3600:
                    return val

            async with hist_semaphore:
                try:
                    if status_placeholder:
                        status_placeholder.caption(f"📊 Updating MA20 for {contract.symbol}...")
                    # Strict timeout for each individual historical data request
                    bars = await asyncio.wait_for(
                        ib.reqHistoricalDataAsync(
                            contract, endDateTime='', durationStr='1 M',
                            barSizeSetting='1 day', whatToShow='ADJUSTED_LAST', useRTH=True),
                        timeout=8.0 # Give it enough time but don't hang forever
                    )
                    if bars and len(bars) >= 20:
                        closes = [b.close for b in bars[-20:]]
                        ma = sum(closes) / 20
                        st.session_state.ma20_cache[cid] = (ma, datetime.now())
                        return ma
                    return None
                except:
                    return None

        # Fetch missing MA20s in parallel with throttling
        ma20_tasks = [fetch_ma20_step(pos.contract) for pos in positions]
        ma20_results = await asyncio.gather(*ma20_tasks)
        ma20_map = {positions[i].contract.conId: ma20_results[i] for i in range(len(positions))}

        # Use openTrades() for active orders only. 
        active_trades = [t for t in ib.openTrades() if t.order.account.upper() == target_acc]

        for pos in positions:
            contract = pos.contract
            # Reading from local background-updated ticker cache (Zero Latency)
            ticker = ib.ticker(contract)
            ma20 = ma20_map.get(contract.conId)
            
            market_price = 0.0
            if ticker:
                # Aggressive price discovery logic
                mp = ticker.marketPrice()
                if not pd.isna(mp) and mp > 0:
                    market_price = mp
                elif not pd.isna(ticker.last) and ticker.last > 0:
                    market_price = ticker.last
                elif not pd.isna(ticker.close) and ticker.close > 0:
                    market_price = ticker.close
                elif not pd.isna(ticker.bid) and ticker.bid > 0:
                    market_price = ticker.bid
                elif not pd.isna(ticker.ask) and ticker.ask > 0:
                    market_price = ticker.ask

            # Forced snapshot fallback if price is still 0
            if market_price == 0.0:
                try:
                    # One-time direct request to wake up the data stream for this contract
                    snap = await asyncio.wait_for(ib.reqTickersAsync(contract), timeout=2.0)
                    if snap:
                        t = snap[0]
                        mp = t.marketPrice()
                        if not pd.isna(mp) and mp > 0: market_price = mp
                        elif not pd.isna(t.last) and t.last > 0: market_price = t.last
                except:
                    pass
                
            market_value = pos.position * market_price
            total_market_value += market_value
            unrealized_pnl = market_value - (pos.avgCost * pos.position)
            total_unrealized_pnl += unrealized_pnl

            # Find Stop Price
            stop_price = None
            for trade in active_trades:
                if trade.contract.conId == contract.conId:
                    if trade.order.orderType in ['STP', 'STP LMT', 'TRAIL', 'TRAIL LIMIT']:
                        stop_price = trade.order.auxPrice or getattr(trade.orderStatus, 'stopPrice', None)
                        if stop_price:
                            break
            
            # Determine the "Effective Exit" for Threshold Gains
            # Primary: Stop Order | Fallback: MA20
            # Logic: If both exist, pick the one closest to current market price (more conservative)
            effective_exit = None
            if stop_price and ma20:
                # Pick the one closest to market_price
                if abs(market_price - stop_price) < abs(market_price - ma20):
                    effective_exit = stop_price
                else:
                    effective_exit = ma20
            elif stop_price:
                effective_exit = stop_price
            elif ma20:
                effective_exit = ma20
            
            # Risk calculation: Stop Order > MA20 > Fallback Strategy
            if stop_price:
                risk = abs(market_price - stop_price) * abs(pos.position)
            elif ma20:
                risk = abs(market_price - ma20) * abs(pos.position)
            else:
                risk = abs(market_value) * 0.05 if stop_strategy == "Manual 5% (Fallback)" else abs(market_value)
            
            total_open_risk += risk
            
            # Threshold Gain is based on the "Effective Exit" (Stop or MA20)
            # Only count if the exit price is better than the entry cost
            if effective_exit and ((pos.position > 0 and effective_exit > pos.avgCost) or (pos.position < 0 and effective_exit < pos.avgCost)):
                t_gain = abs(effective_exit - pos.avgCost) * abs(pos.position)
            else:
                t_gain = 0.0
            
            threshold_gains += t_gain
            
            # Yellow ! icon if price is zero
            display_symbol = contract.symbol
            if market_price == 0:
                display_symbol = f"⚠️ {contract.symbol}"

            position_data.append({
                "Symbol": display_symbol,
                "Pos": pos.position,
                "Avg Cost": pos.avgCost,
                "Price": market_price,
                "Unrealized PnL": unrealized_pnl,
                "Stop": stop_price,
                "MA20": ma20,
                "Risk": risk,
                "T-Gain": t_gain
            })

        principal_state = (cash + total_market_value) - total_open_risk
        growth_state = total_unrealized_pnl
        dynamic_gains = total_unrealized_pnl - threshold_gains
        
        return {
            "status": "Success",
            "Total Money": net_liquidation,
            "Open Risk": total_open_risk,
            "Principal State": principal_state,
            "Growth State": growth_state,
            "Threshold Gains": threshold_gains,
            "Dynamic Gains": dynamic_gains,
            "Position Data": position_data
        }
    except Exception as e:
        return {"status": "Error", "message": str(e)}
    finally:
        if 'last_fetch_time' in st.session_state:
            del st.session_state.last_fetch_time

# --- Fragmented Dashboard Rendering ---
@st.fragment(run_every=refresh_interval if (st.session_state.ib_connected and auto_refresh) else None)
def render_dashboard_fragment():
    if st.session_state.ib_connected:
        ib = get_safe_ib(tws_host, tws_port, client_id)
        if ib and ib.isConnected():
            target_acc = account_id.strip().upper()
            status_container = st.empty()
            with status_container:
                st.caption(f"🔄 Updating data for {target_acc}...")
                
            try:
                # Use util.run which is the "gold standard" for ib_insync in sync environments
                data = util.run(fetch_portfolio_data(ib, target_acc, stop_strategy, status_container))
                status_container.empty()
            except Exception as e:
                # Specific check for loop mismatch to help the user identify it
                if "different loop" in str(e):
                    st.cache_resource.clear()
                    st.rerun()
                status_container.error(f"Fetch Error: {e}")
                data = {"status": "Error", "message": str(e)}

            if data.get("status") == "InProgress":
                return # Silent return for background overlap

            if data.get("status") == "Success":
                # --- New Risk Monitor Component ---
                open_risk = data["Open Risk"]
                threshold = data["Threshold Gains"]
                
                # Calculate coverage and level color
                coverage = (open_risk / threshold * 100) if threshold > 0 else (100 if open_risk > 0 else 0)
                coverage_capped = min(100, coverage)
                buffer = threshold - open_risk
                
                if coverage < 50:
                    level_color = "#3b82f6" # Safe Blue
                    status_text = "SAFE"
                    status_icon = "🛡️"
                    glow = "rgba(59, 130, 246, 0.5)"
                elif coverage < 90:
                    level_color = "#f59e0b" # Caution Amber
                    status_text = "CAUTION"
                    status_icon = "⚠️"
                    glow = "rgba(245, 158, 11, 0.5)"
                else:
                    level_color = "#ef4444" # Breach Red
                    status_text = "DEFENSE ALERT"
                    status_icon = "🚨"
                    glow = "rgba(239, 68, 68, 0.5)"

                risk_html = (
                    f'<div class="risk-monitor-card">'
                    f'    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">'
                    f'        <span style="font-weight: 700; font-size: 0.9rem; color: #94a3b8;">SYSTEM RISK MONITOR</span>'
                    f'        <div class="status-pill" style="background: {level_color}22; color: {level_color}; border: 1px solid {level_color}44;">'
                    f'            <span>{status_icon}</span> {status_text}'
                    f'        </div>'
                    f'    </div>'
                    f'    <div class="metric-grid">'
                    f'        <div>'
                    f'            <div class="risk-label">Open Risk</div>'
                    f'            <div class="metric-value-large" style="color: {level_color if coverage > 90 else "white"}">${open_risk:,.2f}</div>'
                    f'        </div>'
                    f'        <div>'
                    f'            <div class="risk-label">Threshold Gains</div>'
                    f'            <div class="metric-value-large" style="color: white;">${threshold:,.2f}</div>'
                    f'        </div>'
                    f'        <div>'
                    f'            <div class="risk-label">Safety Buffer</div>'
                    f'            <div class="metric-value-large" style="color: {"#10b981" if buffer > 0 else "#ef4444"}">${buffer:,.2f}</div>'
                    f'        </div>'
                    f'    </div>'
                    f'    <div class="level-container">'
                    f'        <div class="marker-tick" style="left: 0%;"></div>'
                    f'        <div class="marker-label" style="left: 0%;">0%</div>'
                    f'        <div class="marker-tick" style="left: 50%; opacity: 0.5;"></div>'
                    f'        <div class="marker-label" style="left: 50%;">50% (CAUTION)</div>'
                    f'        <div class="marker-tick" style="left: 100%;"></div>'
                    f'        <div class="marker-label" style="left: 100%;">100% (DEFENSE)</div>'
                    f'        <div class="level-fill" style="width: {coverage_capped}%; background-color: {level_color}; --glow-color: {glow};"></div>'
                    f'    </div>'
                    f'    <div style="margin-top: 40px; font-size: 0.75rem; color: #64748b; display: flex; justify-content: space-between;">'
                    f'        <span>Risk Coverage Ratio</span>'
                    f'        <span style="color: {level_color}; font-weight: 700;">{coverage:,.1f}%</span>'
                    f'    </div>'
                    f'</div>'
                )
                st.markdown(risk_html, unsafe_allow_html=True)

                m1, m2, m3 = st.columns(3)
                m1.metric("Total Money (Equity)", f"${data['Total Money']:,.2f}", f"{(data['Total Money'] - principal_baseline) / principal_baseline:.2%}" if principal_baseline > 0 else "0%", help="The current total value of your account, representing the sum of your Principal State and your Growth State.")
                m2.metric("Principal State", f"${data['Principal State']:,.2f}", help="The \"real\" value of your account—the money you truly own after subtracting open risk from your cash and allocated capital.")
                m3.metric("Growth State", f"${data['Growth State']:,.2f}", help="Unrealized PnL")

                m4, m5, m6 = st.columns(3)
                m4.metric("Open Risk", f"${data['Open Risk']:,.2f}", delta_color="inverse", help="The total dollar amount at risk across all positions where stops are not yet at breakeven, plus any fresh risk from new entries.")
                m5.metric("Threshold Gains", f"${data['Threshold Gains']:,.2f}", help="The portion of your unrealized profits that are \"stable\" because they are protected by your current stop-loss levels.")
                m6.metric("Dynamic Gains", f"${data['Dynamic Gains']:,.2f}", help="The fluid portion of your profits that fluctuates with market volatility and has not yet been \"locked in\" by a protective stop.")

                # Display Portfolio Table
                st.subheader("Active Positions")
                df = pd.DataFrame(data["Position Data"])
                if not df.empty:
                    st.dataframe(df.style.format({
                        "Pos": "{:.0f}",
                        "Avg Cost": "{:.2f}",
                        "Price": "{:.2f}",
                        "Unrealized PnL": "{:.2f}",
                        "Stop": "{:.2f}",
                        "MA20": "{:.2f}",
                        "Risk": "{:.2f}",
                        "T-Gain": "{:.2f}"
                    }, na_rep="-"), use_container_width=True)
                else:
                    st.info("No active positions found in TWS.")

                st.caption(f"Last updated: {datetime.now().strftime('%H:%M:%S')}")
            elif data.get("status") == "NoData":
                st.warning(data["message"])
                if data.get("available"): st.info(f"Available Accounts: {', '.join(data['available'])}")
            else:
                st.error(f"API Error: {data.get('message')}")
        else:
            # Connection lost - clean up
            st.cache_resource.clear()
            st.session_state.ib_connected = False
            st.error("Lost connection to TWS. Please reconnect.")
            st.rerun()
    else:
        st.info("👋 Welcome! Please configure your settings in the sidebar and click **Connect to TWS** to start monitoring.")

# Render the fragment
render_dashboard_fragment()
