import asyncio
import threading
from ib_insync import IB
import pandas as pd
from datetime import datetime, timedelta
import time
import logging
import json
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class IBManager:
    """
    Runs ib_insync in a dedicated background thread with its own event loop.
    All ib_insync coroutines are submitted to that loop via run_coroutine_threadsafe,
    so they always execute in the correct loop context.
    """

    def __init__(self):
        self._ib_loop: asyncio.AbstractEventLoop = None
        self._ib_thread: threading.Thread = None
        self._ib: IB = None
        self._commission_map = {}  # execId -> commission
        self.ma_cache = {}  # key: (conId, period) → (value, timestamp)
        self.persistent_cache_file = "metrics_cache.json"
        self._load_persistent_cache()
        self._ready = threading.Event()
        self._alerts = [
            {"time": datetime.now().strftime('%H:%M:%S'), "type": "INFO", "message": "System Initialization Complete"},
            {"time": datetime.now().strftime('%H:%M:%S'), "type": "INFO", "message": "IBKR monitoring engine active."}
        ]
        self._triggered_alerts = {} # date_str -> set()
        self._active_critical_alerts = set() # key -> message
        self._earnings_cache = {}  # symbol -> {date, timestamp}
        self._start_ib_thread()

    def _load_persistent_cache(self):
        if os.path.exists(self.persistent_cache_file):
            try:
                with open(self.persistent_cache_file, "r") as f:
                    self.persistent_cache = json.load(f)
            except Exception as e:
                logger.error(f"Error loading persistent cache: {e}")
                self.persistent_cache = {}
        else:
            self.persistent_cache = {}

    def _save_persistent_cache(self):
        try:
            with open(self.persistent_cache_file, "w") as f:
                json.dump(self.persistent_cache, f)
        except Exception as e:
            logger.error(f"Error saving persistent cache: {e}")

    # ── Thread / Loop management ────────────────────────────────────────

    def _start_ib_thread(self):
        self._ib_thread = threading.Thread(target=self._run_loop, daemon=True, name="ib_loop")
        self._ib_thread.start()
        self._ready.wait(timeout=5)

    def _run_loop(self):
        """This thread owns the IB event loop forever."""
        self._ib_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._ib_loop)
        self._ib = IB()
        self._ib.commissionReportEvent += self._on_commission_report
        self.hist_semaphore = asyncio.Semaphore(5)  # Increased for faster background fetches
        self._ready.set()
        logger.info("IB background loop is running.")
        self._ib_loop.run_forever()

    def _submit(self, coro, timeout=30):
        """Submit a coroutine to the IB loop and block until complete."""
        future = asyncio.run_coroutine_threadsafe(coro, self._ib_loop)
        return future.result(timeout=timeout)

    # ── Coroutines that run INSIDE the IB loop ─────────────────────────

    async def _coro_connect(self, host, port, client_id):
        if self._ib.isConnected():
            self._ib.disconnect()

        for attempt in range(1, 4):
            cid = client_id + attempt - 1
            try:
                logger.info(f"Attempt {attempt}: {host}:{port} CID={cid}")
                await self._ib.connectAsync(host, port, clientId=cid, timeout=10)
                logger.info(f"Connected with CID={cid}")
                
                # Reset alerts and triggered history on new connection
                self._alerts = [
                    {"time": datetime.now().strftime('%H:%M:%S'), "type": "INFO", "message": "System Initialization Complete"},
                    {"time": datetime.now().strftime('%H:%M:%S'), "type": "INFO", "message": "IBKR monitoring engine active."}
                ]
                self._triggered_alerts = {}
                self._active_critical_alerts = set()
                
                self._add_alert("INFO", f"Connected to IBKR (Port: {port}, CID: {cid})")
                
                # Request all open orders so stop orders from prior sessions are loaded
                await self._ib.reqAllOpenOrdersAsync()
                logger.info(f"Open orders loaded: {len(self._ib.openTrades())} trades")
                
                # Stabilization Delay: Give the API a moment to be fully ready for queries
                await asyncio.sleep(1.5)
                
                # Fetch available managed accounts
                managed_accounts = self._ib.managedAccounts()
                
                return {
                    "status": "success", 
                    "client_id": cid,
                    "accounts": managed_accounts
                }
            except Exception as e:
                logger.error(f"Attempt {attempt} failed: {e}")
                self._add_alert("ALERT", f"Connection attempt {attempt} failed")


        return {"status": "error", "message": "Could not connect to TWS/Gateway. Check if TWS is open and API is enabled."}

    def _add_alert(self, alert_type, message, key=None):
        """Adds a new alert to the internal buffer."""
        self._alerts.append({
            "time": datetime.now().strftime('%H:%M:%S'),
            "type": alert_type.upper(),
            "message": message,
            "key": key
        })
        # Keep only the last 100 alerts
        if len(self._alerts) > 100:
            self._alerts = self._alerts[-100:]

    def clear_alerts(self):
        """Clears the internal alert buffer except for active critical issues."""
        self._alerts = [
            {"time": datetime.now().strftime('%H:%M:%S'), "type": "INFO", "message": "Log buffer cleared by user."}
        ]
        return {"status": "success"}


    async def _coro_fetch_data(self, account_id, ma_period=20):
        ib = self._ib
        if not ib.isConnected():
            return {"status": "error", "message": "IB is not connected."}

        try:
            target_acc = str(account_id).strip().upper()

            # Brief yield to allow any pending IB updates
            await asyncio.sleep(0.2)

            # Use cached account data - these are pure cache reads, no loop.run_until_complete
            # ib.accountValues() reads from ib.client.wrapper.accountValues (already populated on connect)
            # ib.portfolio() reads from ib.client.wrapper.portfolio (already populated on connect)
            acc_values = [v for v in ib.accountValues() if v.account.upper() == target_acc]

            if not acc_values:
                return {"status": "error", "message": f"No data for account '{target_acc}'. Try waiting a few seconds after connecting."}

            net_liquidation = cash = 0.0
            for item in acc_values:
                if item.tag == 'NetLiquidation' and item.currency == 'USD':
                    try: net_liquidation = float(item.value)
                    except: pass
                if item.tag in ['TotalCashValue', 'CashBalance'] and item.currency == 'USD':
                    try: cash = float(item.value)
                    except: pass

            # ib.portfolio() is a pure cache lookup - safe to call inside the IB loop
            portfolio_items = [p for p in ib.portfolio() if p.account.upper() == target_acc]

            # Request market data for ALL contracts to ensure tickers are fresh and updating
            ib.reqMarketDataType(3)  # Use delayed data as fallback
            active_tickers = {t.contract.conId for t in ib.tickers()}
            new_contracts = [p.contract for p in portfolio_items if p.contract.conId not in active_tickers]
            if new_contracts:
                try:
                    await ib.qualifyContractsAsync(*new_contracts)
                except Exception as qe:
                    logger.warning(f"qualifyContractsAsync warning: {qe}")
                for contract in new_contracts:
                    ib.reqMktData(contract, '', False, False)
                await asyncio.sleep(1.0)  # Give IB time to send the first tick

            # SERVE METRICS FROM CACHE IMMEDIATELY
            # These are pure cache lookups - instant
            metrics_results = []
            today_str = datetime.now().strftime('%Y-%m-%d')
            for item in portfolio_items:
                contract = item.contract
                cid = str(contract.conId)
                results = (None, None, None, None)
                
                # Check persistent cache (today's)
                if cid in self.persistent_cache:
                    cached = self.persistent_cache[cid]
                    if cached.get("date") == today_str:
                        results = (cached.get("ma10"), cached.get("ma20"), cached.get("adr"), cached.get("low"))
                
                # Check in-memory session cache
                key = (cid, 'metrics10_20')
                if key in self.ma_cache:
                    cached_val, ts = self.ma_cache[key]
                    if (datetime.now() - ts).total_seconds() < 3600:
                        results = cached_val
                
                metrics_results.append(results)
                
                # TRIGGER BACKGROUND FETCH IF STALE/MISSING
                # Also fetch if low is missing (new feature)
                if results[0] is None or results[3] is None:
                    asyncio.create_task(self._coro_historical_metrics(contract))

            # Request fresh open orders to get updated stop prices from TWS
            try:
                # Use the return value of reqAllOpenOrdersAsync which only contains truly open trades at this moment
                active_trades = await ib.reqAllOpenOrdersAsync()
            except Exception as e:
                logger.warning(f"reqAllOpenOrdersAsync error: {e}")
                # Fallback to cache
                active_trades = ib.openTrades()

            total_open_risk = threshold_gains = total_unrealized_pnl = total_market_value = total_ps_risk = 0.0
            position_data = []

            today_date_str = datetime.now().strftime('%Y-%m-%d')
            if today_date_str not in self._triggered_alerts:
                self._triggered_alerts = {today_date_str: set()}
            triggered_for_today = self._triggered_alerts[today_date_str]

            for i, item in enumerate(portfolio_items):

                contract = item.contract
                symbol = contract.symbol
                position = item.position
                avg_cost = item.averageCost

                # PRIMARY: use ib.ticker() — updated on every market tick (real-time)
                # FALLBACK: portfolio item's marketPrice (updates every few seconds from IB)
                market_price = 0.0
                ticker = ib.ticker(contract)
                if ticker:
                    for attr in ['marketPrice', 'last', 'close', 'bid']:
                        try:
                            if attr == 'marketPrice':
                                val = ticker.marketPrice()
                            else:
                                val = getattr(ticker, attr, None)
                            if val and not pd.isna(val) and val > 0:
                                market_price = val
                                break
                        except Exception:
                            pass

                # Final fallback: portfolio item price
                if market_price == 0.0 and item.marketPrice and item.marketPrice > 0:
                    market_price = item.marketPrice

                ma10, ma20, adr, daily_low = metrics_results[i] if i < len(metrics_results) else (None, None, None, None)

                # Use the chosen MA period for risk/threshold calculation
                ma_value = ma10 if ma_period == 10 else ma20

                market_value = position * market_price
                total_market_value += market_value
                unrealized_pnl = market_value - (avg_cost * position)
                total_unrealized_pnl += unrealized_pnl

                stop_price = None
                for trade in active_trades:
                    if trade.contract.conId == contract.conId:
                        ot = trade.order.orderType
                        if ot in ['STP', 'STP LMT', 'TRAIL', 'TRAIL LIMIT', 'TRAILLMT']:
                            # Try all possible fields where stop price could live
                            candidates = [
                                trade.order.auxPrice,
                                getattr(trade.order, 'trailStopPrice', None),
                                getattr(trade.orderStatus, 'lastFillPrice', None),
                            ]
                            for c in candidates:
                                if c and c > 0:
                                    stop_price = c
                                    break
                            if stop_price:
                                logger.info(f"Stop found for {contract.symbol}: {stop_price} (type={ot})")
                                break
                if not stop_price:
                    logger.debug(f"No stop found for {contract.symbol} (trades checked: {len(active_trades)})")

                # Stop Logic Hierarchy:
                # 1. If a hard stop order exists and is in the 'red' (principal risk), it takes priority.
                # 2. Moving Average only takes over once the hard stop is above cost or if no stop order exists.
                if position > 0: # Long
                    if stop_price and stop_price < avg_cost:
                        effective_exit = stop_price
                    else:
                        candidates = [c for c in [stop_price, ma_value] if c is not None]
                        effective_exit = max(candidates) if candidates else None
                else: # Short
                    if stop_price and stop_price > avg_cost:
                        effective_exit = stop_price
                    else:
                        candidates = [c for c in [stop_price, ma_value] if c is not None]
                        effective_exit = min(candidates) if candidates else None

                if stop_price:
                    if (position > 0 and market_price < stop_price) or (position < 0 and market_price > stop_price):
                        risk = 0.0 # Gapped past stop
                    else:
                        risk = abs(market_price - stop_price) * abs(position)
                elif ma_value:
                    if (position > 0 and market_price < ma_value) or (position < 0 and market_price > ma_value):
                        risk = 0.0 # Gapped past MA fallback
                    else:
                        risk = abs(market_price - ma_value) * abs(position)
                else:
                    risk = abs(market_value)

                total_open_risk += risk

                if effective_exit and (
                    (position > 0 and effective_exit > avg_cost) or
                    (position < 0 and effective_exit < avg_cost)
                ):
                    t_gain = abs(effective_exit - avg_cost) * abs(position)
                    # Constraint: Threshold gains cannot exceed actual Unrealized PnL
                    t_gain = min(t_gain, max(0.0, float(unrealized_pnl)))
                else:
                    t_gain = 0.0

                threshold_gains += t_gain

                ps_risk = max(0.0, risk - float(unrealized_pnl))
                if effective_exit and (
                    (position > 0 and effective_exit >= avg_cost) or
                    (position < 0 and effective_exit <= avg_cost)
                ):
                    ps_risk = 0.0
                
                total_ps_risk += ps_risk

                position_data.append({
                    "symbol": contract.symbol,
                    "pos": position,
                    "avgCost": avg_cost,
                    "price": market_price,
                    "pnl": unrealized_pnl,
                    "stop": stop_price,
                    "ma10": ma10,
                    "ma20": ma20,
                    "adr": adr,
                    "risk": risk,
                    "tGain": t_gain,
                    "psRisk": ps_risk
                })

                # Earnings Alert (Non-blocking background fetch)
                if symbol not in self._earnings_cache or (datetime.now() - self._earnings_cache[symbol]["ts"]).days > 7:
                    # Check if already pending to avoid multiple tasks
                    if symbol not in self._earnings_cache or self._earnings_cache[symbol]["date"] != "Pending":
                        self._earnings_cache[symbol] = {"date": "Pending", "ts": datetime.now()}
                        asyncio.create_task(self._bg_update_earnings(symbol))
                
                cached_earnings = self._earnings_cache.get(symbol)
                if cached_earnings and cached_earnings["date"] not in ["Pending", "Unknown", "Error"]:
                    earnings_val = cached_earnings["date"]
                    
                    # 1. Standard INFO Alert
                    earn_key = f"{symbol}-earnings-{earnings_val}"
                    if earn_key not in triggered_for_today:
                        self._add_alert("INFO", f"Next Earnings for {symbol}: {earnings_val} (Source: Yahoo Finance)")
                        triggered_for_today.add(earn_key)

                    # 2. High-Priority 5-Day Proximity Alert
                    try:
                        earn_date = datetime.strptime(earnings_val, "%Y-%m-%d").date()
                        today = datetime.now().date()
                        days_to = (earn_date - today).days
                        if 0 <= days_to <= 5:
                            prox_key = f"{symbol}-earnings-prox-{earnings_val}"
                            if prox_key not in triggered_for_today:
                                msg = f"Upcoming Earnings for {symbol}: {earnings_val} ({days_to} days away) (Source: Yahoo Finance)"
                                if days_to == 0: msg = f"EARNINGS TODAY for {symbol}: {earnings_val}! (Source: Yahoo Finance)"
                                self._add_alert("ALERT", msg)
                                triggered_for_today.add(prox_key)
                    except Exception as e:
                        logger.debug(f"Could not parse earnings date for {symbol}: {e}")

                # SMA Alerts Check
                ticker_low = getattr(ticker, 'low', None)
                # Use ticker.low if available, otherwise fallback to daily_low from historical bars
                actual_low = ticker_low if (ticker_low and ticker_low > 0 and not pd.isna(ticker_low)) else daily_low
                
                # Today's Low touches SMAs
                if actual_low and not pd.isna(actual_low) and actual_low > 0:
                    if ma10 and actual_low <= ma10:
                        key = f"{symbol}-touch-10sma"
                        if key not in triggered_for_today:
                            self._add_alert("ALERT", f"The ticker {symbol} has touched the 10SMA (Low: {actual_low:.2f})")
                            triggered_for_today.add(key)
                    if ma20 and actual_low <= ma20:
                        key = f"{symbol}-touch-20sma"
                        if key not in triggered_for_today:
                            self._add_alert("ALERT", f"The ticker {symbol} has touched the 20SMA (Low: {actual_low:.2f})")
                            triggered_for_today.add(key)

                # Price negotiated below SMAs
                if market_price > 0:
                    if ma10 and market_price < ma10:
                        key = f"{symbol}-below-10sma"
                        if key not in triggered_for_today:
                            self._add_alert("ALERT", f"The ticker {symbol} is being negotiated below the 10SMA (Price: {market_price:.2f})")
                            triggered_for_today.add(key)
                    if ma20 and market_price < ma20:
                        key = f"{symbol}-below-20sma"
                        if key not in triggered_for_today:
                            self._add_alert("ALERT", f"The ticker {symbol} is being negotiated below the 20SMA (Price: {market_price:.2f})")
                            triggered_for_today.add(key)


            total_abs_market_value = sum(abs(p["pos"] * p["price"]) for p in position_data)
            total_allocated_cost = sum(abs(p["pos"] * p["avgCost"]) for p in position_data)

            # --- CRITICAL STOP ORDER ALERTS ---
            portfolio_symbols = {p["symbol"] for p in position_data}
            stop_orders_by_symbol = {}
            for trade in active_trades:
                ot = (trade.order.orderType or "").upper()
                # Broaden stop order detection
                if ot in ['STP', 'STP LMT', 'TRAIL', 'TRAIL LIMIT', 'TRAILLMT', 'STOP', 'STOP LIMIT', 'TRAILING STOP', 'TRAIL LMT']:
                    s = trade.contract.symbol
                    if s not in stop_orders_by_symbol:
                        stop_orders_by_symbol[s] = []
                    stop_orders_by_symbol[s].append(trade)
                else:
                    # Log other orders for debugging if needed
                    logger.debug(f"Skipping non-stop order type for alert check: {trade.contract.symbol} {ot}")

            current_run_critical_keys = set()

            for sym, trades_list in stop_orders_by_symbol.items():
                total_stop_qty = sum(t.order.totalQuantity for t in trades_list)
                
                # Check 1: Stop on asset not in portfolio
                if sym not in portfolio_symbols:
                    key = f"{sym}-orphan-stop"
                    current_run_critical_keys.add(key)
                    if key not in self._active_critical_alerts:
                        self._add_alert("CRITICAL", f"Orphan Stop Order: {sym} ({total_stop_qty} shares) has no matching position in portfolio.", key=key)
                        self._active_critical_alerts.add(key)
                else:
                    # Find matching position
                    pos_obj = next(p for p in position_data if p["symbol"] == sym)
                    abs_pos = abs(pos_obj["pos"])
                    
                    # Check 2: Size mismatch
                    if total_stop_qty != abs_pos:
                        key = f"{sym}-stop-size-mismatch"
                        current_run_critical_keys.add(key)
                        if key not in self._active_critical_alerts:
                            self._add_alert("CRITICAL", f"Stop Size Mismatch: {sym} has {abs_pos} shares, but stop order is for {total_stop_qty} shares.", key=key)
                            self._active_critical_alerts.add(key)
                    
                    # Check 3: Non-GTC order
                    for t in trades_list:
                        tif = (t.order.tif or "").upper()
                        if tif != 'GTC':
                            key = f"{sym}-stop-not-gtc-{t.order.orderId}"
                            current_run_critical_keys.add(key)
                            if key not in self._active_critical_alerts:
                                self._add_alert("CRITICAL", f"Critical Stop Parameter: {sym} stop order is NOT GTC (TIF: {tif}).", key=key)
                                self._active_critical_alerts.add(key)

            # Check 4: Missing stop order for position
            for p in position_data:
                sym = p["symbol"]
                if sym not in stop_orders_by_symbol:
                    key = f"{sym}-missing-stop"
                    current_run_critical_keys.add(key)
                    if key not in self._active_critical_alerts:
                        self._add_alert("CRITICAL", f"Missing Stop: {sym} ({p['pos']} shares) has NO active stop order.", key=key)
                        self._active_critical_alerts.add(key)

            # Detect RESOLVED issues
            resolved_keys = self._active_critical_alerts - current_run_critical_keys
            if resolved_keys:
                for key in resolved_keys:
                    # Remove the critical alert from the log buffer
                    self._alerts = [a for a in self._alerts if a.get("key") != key]
                    
                    # Log the resolution for the audit trail
                    parts = key.split('-')
                    sym = parts[0]
                    reason = " ".join(parts[1:]).replace('size mismatch', 'size').replace('not gtc', 'TIF parameter').upper()
                    self._add_alert("INFO", f"RESOLVED: {sym} stop order issue ({reason}) has been corrected.")
                    self._active_critical_alerts.remove(key)
            # ----------------------------------


            weighted_adr = 0.0
            if total_abs_market_value > 0:
                weighted_adr = sum(
                    (abs(p["pos"] * p["price"]) / total_abs_market_value) * p["adr"]
                    for p in position_data if p["adr"] is not None
                )

            # Principal State uses the initial investment (allocated cost), not the fluctuating market value
            principal_state = (cash + total_allocated_cost) - total_ps_risk
            
            return {
                "status": "success",
                "totalMoney": principal_state + total_unrealized_pnl, # Total Money = Principal State + Growth State
                "netLiquidation": net_liquidation, # Add actual net liquidation value
                "totalPsRisk": total_ps_risk, # Added PS Risk aggregation
                "cash": cash,
                "moneyAllocated": total_allocated_cost,
                "marketValueOfPositions": total_market_value,
                "openRisk": total_open_risk,
                "weightedAdr": weighted_adr,
                "principalState": principal_state,
                "growthState": total_unrealized_pnl,
                "thresholdGains": threshold_gains,
                "dynamicGains": total_unrealized_pnl - threshold_gains,
                "positions": position_data,
                "trades": await self._coro_fetch_trades(target_acc),
                "alerts": self._alerts[::-1], # Return alerts in reverse chronological order
                "lastUpdate": datetime.now().strftime('%H:%M:%S')
            }
        except Exception as e:
            logger.error(f"Error in _coro_fetch_data: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {"status": "error", "message": str(e)}

    async def _coro_fetch_trades(self, account_id=None):
        """Fetches executions and aggregates them into active activity and closed trades for today, yesterday, and last 7 days."""
        ib = self._ib
        if not ib.isConnected():
            return {"today": {"active": [], "closed": []}, "yesterday": {"active": [], "closed": []}, "last7": {"active": [], "closed": []}}

        try:
            from ib_insync import ExecutionFilter
            # Using clientId=0 in the filter is crucial to catch trades from all sessions/manual
            seven_days_ago = (datetime.now() - timedelta(days=8)).strftime("%Y%m%d-00:00:00")
            filt = ExecutionFilter(clientId=0, time=seven_days_ago)
            executions = await ib.reqExecutionsAsync(filt)
            
            # Brief sleep to allow commissionReport events to be processed
            await asyncio.sleep(0.5)
            
            logger.info(f"Raw executions count from IB: {len(executions)}")
            if executions:
                # Log first 5 for sample
                target_execs = [e for e in executions if e.execution.acctNumber == account_id]
                logger.info(f"Executions for account {account_id}: {len(target_execs)}")
                for e in target_execs[:5]:
                    comm_val = "N/A"
                    if hasattr(e, 'commissionReport') and e.commissionReport:
                        comm_val = e.commissionReport.commission
                    logger.info(f"Execution sample: {e.execution.execId} {e.contract.symbol} {e.execution.time} comm={comm_val}")
                # Use the filtered list for processing
                executions = target_execs
            
            today_date = datetime.now().date()
            yesterday_date = today_date - timedelta(days=1)
            seven_days_limit = today_date - timedelta(days=7)
            
            # Data structure: period -> symbol -> { data }
            day_data = {
                "today": {},
                "yesterday": {},
                "last7": {}
            }
            
            for exec_report in executions:
                execution = exec_report.execution
                contract = exec_report.contract
                
                # Robust time parsing
                exec_time = execution.time
                if isinstance(exec_time, str):
                    try:
                        # Normalize string if needed
                        if '  ' in exec_time:
                            # 20260315  11:47:39 -> 2026-03-15 11:47:39
                            exec_time = datetime.strptime(exec_time, '%Y%m%d  %H:%M:%S')
                        else:
                            # 2026-03-15 or similar
                            exec_time = pd.to_datetime(exec_time).to_pydatetime()
                    except:
                        try:
                            # Fallback to date only if full parsing fails
                            if '  ' in exec_time:
                                exec_time = datetime.strptime(exec_time.split('  ')[0], '%Y%m%d')
                            else:
                                exec_time = pd.to_datetime(exec_time).to_pydatetime()
                        except:
                            logger.warning(f"Could not parse execution time: {exec_time}")
                            continue
                
                # Ensure it's a datetime object even if it came from pandas
                if hasattr(exec_time, 'to_pydatetime'):
                    exec_time = exec_time.to_pydatetime()

                # Use timezone-naive dates for comparison if needed, but keep exec_time for display
                if hasattr(exec_time, 'tzinfo') and exec_time.tzinfo is not None:
                    exec_date = exec_time.astimezone(None).date()
                else:
                    exec_date = exec_time.date() if hasattr(exec_time, 'date') else exec_time
                
                # Assign to specific buckets
                targets = []
                if exec_date == today_date: targets.append("today")
                if exec_date == yesterday_date: targets.append("yesterday")
                if exec_date >= seven_days_limit: targets.append("last7")
                
                if not targets:
                    continue
                
                symbol = contract.symbol
                for t in targets:
                    if symbol not in day_data[t]:
                        day_data[t][symbol] = {
                            "buys": {"shares": 0, "totalValue": 0.0, "totalCommission": 0.0, "lastTime": None},
                            "sells": {"shares": 0, "totalValue": 0.0, "totalCommission": 0.0, "lastTime": None},
                            "firstTime": exec_time,
                            "firstSide": execution.side
                        }
                    
                    sym_data = day_data[t][symbol]
                    side_key = "buys" if execution.side == 'BOT' else "sells"
                    group = sym_data[side_key]
                    group["shares"] += execution.shares
                    group["totalValue"] += (execution.shares * execution.price)
                    
                    # Commission retrieval: 
                    # 1. Try linked report
                    # 2. Try our manual map (more robust for async arrival)
                    comm = 0.0
                    if hasattr(exec_report, 'commissionReport') and exec_report.commissionReport and exec_report.commissionReport.commission > 0:
                        comm = exec_report.commissionReport.commission
                    elif execution.execId in self._commission_map:
                        comm = self._commission_map[execution.execId]
                    
                    group["totalCommission"] += comm
                    
                    if group["lastTime"] is None or exec_time > group["lastTime"]:
                        group["lastTime"] = exec_time
                    
                    if exec_time < sym_data["firstTime"]:
                        sym_data["firstTime"] = exec_time
                        sym_data["firstSide"] = execution.side
            
            # Process categories
            result = {
                "today": {"active": [], "closed": []},
                "yesterday": {"active": [], "closed": []},
                "last7": {"active": [], "closed": []}
            }
            
            for day_key in day_data:
                for symbol, data in day_data[day_key].items():
                    b_q = data["buys"]["shares"]
                    s_q = data["sells"]["shares"]
                    b_p = data["buys"]["totalValue"] / b_q if b_q > 0 else 0
                    s_p = data["sells"]["totalValue"] / s_q if s_q > 0 else 0
                    
                    # Commission pro-rating
                    b_comm_total = data["buys"]["totalCommission"]
                    s_comm_total = data["sells"]["totalCommission"]
                    
                    closed_qty = min(b_q, s_q)
                    
                    # 1. Realized Trade
                    if closed_qty > 0:
                        pnl = (s_p - b_p) * closed_qty
                        side = "Long" if data["firstSide"] == 'BOT' else "Short"
                        
                        # Calculate fees portion for the closed part
                        b_fees_part = (b_comm_total * (closed_qty / b_q)) if b_q > 0 else 0
                        s_fees_part = (s_comm_total * (closed_qty / s_q)) if s_q > 0 else 0
                        closed_fees = b_fees_part + s_fees_part
                        
                        last_trade_time = max(data["buys"]["lastTime"] or datetime.min, data["sells"]["lastTime"] or datetime.min)
                        if last_trade_time == datetime.min: last_trade_time = datetime.now() # Fallback

                        result[day_key]["closed"].append({
                            "symbol": symbol,
                            "side": side,
                            "shares": closed_qty,
                            "pnl": pnl,
                            "fees": closed_fees,
                            "date": last_trade_time.strftime('%Y-%m-%d'),
                            "time": last_trade_time.strftime('%H:%M:%S')
                        })
                    
                    # 2. Active Activity (Net remaining) - relevant for today/yesterday primarily
                    remaining_b = b_q - closed_qty
                    remaining_s = s_q - closed_qty
                    
                    if remaining_b > 0:
                        active_fees = b_comm_total * (remaining_b / b_q)
                        result[day_key]["active"].append({
                            "symbol": symbol,
                            "side": "BOT",
                            "shares": remaining_b,
                            "avgPrice": b_p,
                            "fees": active_fees,
                            "date": data["buys"]["lastTime"].strftime('%Y-%m-%d'),
                            "time": data["buys"]["lastTime"].strftime('%H:%M:%S')
                        })
                    elif remaining_s > 0:
                        active_fees = s_comm_total * (remaining_s / s_q)
                        result[day_key]["active"].append({
                            "symbol": symbol,
                            "side": "SLD",
                            "shares": remaining_s,
                            "avgPrice": s_p,
                            "fees": active_fees,
                            "date": data["sells"]["lastTime"].strftime('%Y-%m-%d'),
                            "time": data["sells"]["lastTime"].strftime('%H:%M:%S')
                        })
                
                # Sort both by time descending
                result[day_key]["active"].sort(key=lambda x: x["time"], reverse=True)
                result[day_key]["closed"].sort(key=lambda x: x["time"], reverse=True)
            
            return result
            
        except Exception as e:
            logger.error(f"Error in _coro_fetch_trades: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {"today": {"active": [], "closed": []}, "yesterday": {"active": [], "closed": []}}

    async def _coro_historical_metrics(self, contract):
        """Fetches 1M of daily bars once, computes and returns (MA10, MA20, ADR20, Low). Uses TRADES data."""
        cid = str(contract.conId)
        symbol = contract.symbol
        today_str = datetime.now().strftime('%Y-%m-%d')
        key = (cid, 'metrics10_20')

        # 1. Check persistent cache for today's value
        if cid in self.persistent_cache:
            cached_data = self.persistent_cache[cid]
            if cached_data.get("date") == today_str:
                return cached_data.get("ma10"), cached_data.get("ma20"), cached_data.get("adr"), cached_data.get("low")
        
        # In-memory cache checkout
        if key in self.ma_cache:
            (ma10, ma20, adr, low), ts = self.ma_cache[key]
            if (datetime.now() - ts).total_seconds() < 3600:
                return ma10, ma20, adr, low

        ma10 = ma20 = adr = low = None

        # 2. Try IBKR API
        try:
            import copy
            hist_contract = copy.copy(contract)
            if not hist_contract.exchange:
                hist_contract.exchange = 'SMART'

            async with self.hist_semaphore:
                bars = await asyncio.wait_for(
                    self._ib.reqHistoricalDataAsync(
                        hist_contract, endDateTime='', durationStr='1 M',
                        barSizeSetting='1 day', whatToShow='TRADES', useRTH=True
                    ),
                    timeout=8.0
                )

            if bars and len(bars) >= 10:
                # Basic averages
                ma10 = sum(b.close for b in bars[-10:]) / 10
                if len(bars) >= 20:
                    ma20 = sum(b.close for b in bars[-20:]) / 20
                    adr = 100 * ((sum(b.high / b.low for b in bars[-20:]) / 20) - 1)
                
                # Extract Low for the current date if the last bar is today
                last_bar = bars[-1]
                # Bars may have date or datetime objects
                bar_date = last_bar.date
                if hasattr(bar_date, 'strftime'):
                    bar_date_str = bar_date.strftime('%Y-%m-%d')
                else:
                    bar_date_str = str(bar_date)
                
                if bar_date_str == today_str:
                    low = last_bar.low
                    logger.info(f"Extracted daily low for {symbol} from historical bars: {low}")
                else:
                    logger.info(f"Last bar for {symbol} is from {bar_date_str}, expected {today_str}. Low remains None.")
                    
        except Exception as e:
            logger.warning(f"Metrics fetch error from IBKR for {symbol}: {e}")

        # 3. Try yfinance fallback
        if adr is None:
            try:
                loop = asyncio.get_event_loop()
                df = await loop.run_in_executor(None, self._fetch_yfinance_history, symbol)
                if df is not None and not df.empty and len(df) >= 10:
                    ma10 = df['Close'].tail(10).mean()
                    if len(df) >= 20:
                        ma20 = df['Close'].tail(20).mean()
                        adr = 100 * (((df['High'].tail(20) / df['Low'].tail(20)).sum() / 20) - 1)
                    
                    # Extract today's low from yfinance if date matches
                    last_date_str = df.index[-1].strftime('%Y-%m-%d')
                    if last_date_str == today_str:
                        low = float(df['Low'].iloc[-1])
                        
                    logger.info(f"Successfully fetched yfinance fallback for {symbol}")
            except Exception as e:
                logger.warning(f"yfinance fallback failed for {symbol}: {e}")

        # 4. Save to persistent cache if we got new values, otherwise use stale cache
        if adr is not None:
             self.persistent_cache[cid] = {
                 "date": today_str,
                 "ma10": float(ma10) if ma10 else None,
                 "ma20": float(ma20) if ma20 else None,
                 "adr": float(adr) if adr else None,
                 "low": float(low) if low else None
             }
             loop = asyncio.get_event_loop()
             loop.run_in_executor(None, self._save_persistent_cache)
             
             results = (ma10, ma20, adr, low)
             self.ma_cache[key] = (results, datetime.now())
             return results
        else:
             # Final fallback: return stale persistent cache if available
             if cid in self.persistent_cache:
                 cached_data = self.persistent_cache[cid]
                 logger.info(f"Using stale persistent cache for {symbol} from {cached_data.get('date')}")
                 return cached_data.get("ma10"), cached_data.get("ma20"), cached_data.get("adr"), cached_data.get("low")
                 
             self.ma_cache[key] = ((None, None, None, None), datetime.now() - timedelta(minutes=59))
             return None, None, None, None

    async def _coro_fetch_ticker_details(self, symbol):
        ib = self._ib
        if not ib.isConnected():
            return {"status": "error", "message": "IB is not connected."}
        
        try:
            from ib_insync import Stock
            contract = Stock(str(symbol).upper().strip(), 'SMART', 'USD')
            qualified = await ib.qualifyContractsAsync(contract)
            if not qualified:
                return {"status": "error", "message": f"Could not qualify contract for {symbol}"}
            
            contract = qualified[0]
            
            # Request market data for price
            ib.reqMktData(contract, '', False, False)
            await asyncio.sleep(0.5) # Wait for some ticks
            
            ticker = ib.ticker(contract)
            market_price = 0.0
            if ticker:
                for attr in ['marketPrice', 'last', 'close', 'bid']:
                    try:
                        if attr == 'marketPrice': val = ticker.marketPrice()
                        else: val = getattr(ticker, attr, None)
                        if val and not pd.isna(val) and val > 0:
                            market_price = val
                            break
                    except: pass
            
            # Fetch historical data for ATR(14) and Price Fallback
            bars = await ib.reqHistoricalDataAsync(
                contract, endDateTime='', durationStr='1 M',
                barSizeSetting='1 day', whatToShow='TRADES', useRTH=True
            )
            
            # Additional fallback: last historical bar close
            if market_price == 0.0 and bars:
                market_price = bars[-1].close

            atr = 0.0
            adr = 0.0
            if bars and len(bars) >= 2:
                # Calculate ATR
                if len(bars) >= 15:
                    tr_values = []
                    for i in range(1, len(bars)):
                        tr = max(
                            bars[i].high - bars[i].low,
                            abs(bars[i].high - bars[i-1].close),
                            abs(bars[i].low - bars[i-1].close)
                        )
                        tr_values.append(tr)
                    atr = sum(tr_values[-14:]) / 14
                
                # Calculate ADR (20-day)
                relevant_bars = bars[-20:]
                if relevant_bars:
                    adr = 100 * ((sum(b.high / b.low for b in relevant_bars) / len(relevant_bars)) - 1)
            
            return {
                "status": "success",
                "symbol": symbol,
                "price": market_price,
                "atr": atr,
                "adr": adr
            }
        except Exception as e:
            logger.error(f"Error in _coro_fetch_ticker_details for {symbol}: {e}")
            return {"status": "error", "message": str(e)}

    def _fetch_yfinance_history(self, symbol):
         try:
             import yfinance as yf
             ticker = yf.Ticker(symbol)
             df = ticker.history(period="1mo")
             return df
         except Exception:
             return None

    # ── Public API (called from FastAPI, bridges to IB loop) ────────────

    @property
    def ib(self):
        return self._ib

    def _fetch_yfinance_earnings(self, symbol):
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            cal = ticker.calendar
            if cal is None:
                return "Unknown"
            
            # Handle Dictionary format (common in recent yfinance)
            if isinstance(cal, dict):
                if "Earnings Date" in cal:
                    dates = cal["Earnings Date"]
                    if dates and len(dates) > 0:
                        d = dates[0]
                        return d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
                return "Unknown"

            # Handle DataFrame format
            if hasattr(cal, 'empty') and not cal.empty:
                try:
                    if "Earnings Date" in cal.index:
                        d = cal.loc["Earnings Date"].iloc[0]
                        if hasattr(d, "strftime"):
                            return d.strftime("%Y-%m-%d")
                except:
                    pass

            return "Unknown"
        except Exception as e:
            logger.debug(f"Earnings fetch error for {symbol}: {e}")
            return "Unknown"

    async def _bg_update_earnings(self, symbol):
        """Helper to update earnings cache in background without blocking main loop."""
        try:
            loop = asyncio.get_event_loop()
            date = await loop.run_in_executor(None, self._fetch_yfinance_earnings, symbol)
            self._earnings_cache[symbol] = {"date": date, "ts": datetime.now()}
        except Exception as e:
            logger.error(f"Background earnings fetch failed for {symbol}: {e}")
            self._earnings_cache[symbol] = {"date": "Unknown", "ts": datetime.now()}

    def _on_commission_report(self, trade, fill, report):
        """Handle incoming commission reports and store them in the map."""
        try:
            if report and report.execId:
                self._commission_map[report.execId] = report.commission
        except Exception as e:
            logger.error(f"Error in _on_commission_report: {e}")

    async def connect(self, host='127.0.0.1', port=7496, client_id=10):
        loop = asyncio.get_event_loop()
        future = asyncio.run_coroutine_threadsafe(
            self._coro_connect(host, port, client_id), self._ib_loop
        )
        return await loop.run_in_executor(None, future.result, 30)

    def disconnect(self):
        """Disconnects from IB and clears active alert state to allow re-triggering on next session."""
        self._active_critical_alerts.clear()
        if self._ib and self._ib.isConnected():
            try:
                self._ib.disconnect()
            except Exception:
                pass
        return {"status": "success"}

    async def fetch_data(self, account_id, ma_period=20):
        loop = asyncio.get_event_loop()
        future = asyncio.run_coroutine_threadsafe(
            self._coro_fetch_data(account_id, ma_period), self._ib_loop
        )
        return await loop.run_in_executor(None, future.result, 60)

    async def fetch_ticker_details(self, symbol):
        loop = asyncio.get_event_loop()
        future = asyncio.run_coroutine_threadsafe(
            self._coro_fetch_ticker_details(symbol), self._ib_loop
        )
        return await loop.run_in_executor(None, future.result, 30)
