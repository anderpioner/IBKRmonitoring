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
        self.ma_cache = {}  # key: (conId, period) → (value, timestamp)
        self.persistent_cache_file = "metrics_cache.json"
        self._load_persistent_cache()
        self._ready = threading.Event()
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
        self.hist_semaphore = asyncio.Semaphore(3)  # Maximum 3 concurrent historical requests
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
                # Request all open orders so stop orders from prior sessions are loaded
                await self._ib.reqAllOpenOrdersAsync()
                logger.info(f"Open orders loaded: {len(self._ib.openTrades())} trades")
                
                # Fetch available managed accounts
                managed_accounts = self._ib.managedAccounts()
                
                return {
                    "status": "success", 
                    "client_id": cid,
                    "accounts": managed_accounts
                }
            except Exception as e:
                logger.error(f"Attempt {attempt} failed: {e}")

        return {"status": "error", "message": "Could not connect to TWS/Gateway. Check if TWS is open and API is enabled."}

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

            # Fetch MA10, MA20 and ADR(20) for all positions using a SINGLE historical request per contract
            hist_tasks = [self._coro_historical_metrics(p.contract) for p in portfolio_items]
            hist_results = await asyncio.gather(*hist_tasks, return_exceptions=True)
            hist_results = [r if not isinstance(r, Exception) else (None, None, None) for r in hist_results]

            # Request fresh open orders to get updated stop prices from TWS
            try:
                # Use the return value of reqAllOpenOrdersAsync which only contains truly open trades at this moment
                active_trades = await ib.reqAllOpenOrdersAsync()
            except Exception as e:
                logger.warning(f"reqAllOpenOrdersAsync error: {e}")
                # Fallback to cache
                active_trades = ib.openTrades()

            total_open_risk = threshold_gains = total_unrealized_pnl = total_market_value = 0.0
            position_data = []

            for i, item in enumerate(portfolio_items):
                contract = item.contract
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

                ma10, ma20, adr = hist_results[i] if i < len(hist_results) else (None, None, None)

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

                if stop_price and ma_value:
                    effective_exit = stop_price if abs(market_price - stop_price) < abs(market_price - ma_value) else ma_value
                elif stop_price:
                    effective_exit = stop_price
                elif ma_value:
                    effective_exit = ma_value
                else:
                    effective_exit = None

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
                    "psRisk": max(0.0, risk - float(unrealized_pnl))
                })

            total_abs_market_value = sum(abs(p["pos"] * p["price"]) for p in position_data)
            total_allocated_cost = sum(abs(p["pos"] * p["avgCost"]) for p in position_data)

            weighted_adr = 0.0
            if total_abs_market_value > 0:
                weighted_adr = sum(
                    (abs(p["pos"] * p["price"]) / total_abs_market_value) * p["adr"]
                    for p in position_data if p["adr"] is not None
                )

            # Principal State uses the initial investment (allocated cost), not the fluctuating market value
            principal_state = (cash + total_allocated_cost) - total_open_risk
            
            return {
                "status": "success",
                "totalMoney": principal_state + total_unrealized_pnl, # Total Money = Principal State + Growth State
                "netLiquidation": net_liquidation, # Add actual net liquidation value
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
                "lastUpdate": datetime.now().strftime('%H:%M:%S')
            }
        except Exception as e:
            logger.error(f"Error in _coro_fetch_data: {e}")
            import traceback
            logger.error(traceback.format_exc())
    async def _coro_historical_metrics(self, contract):
        """Fetches 1M of daily bars once, computes and returns (MA10, MA20, ADR20). Uses TRADES data."""
        cid = str(contract.conId)
        symbol = contract.symbol
        today_str = datetime.now().strftime('%Y-%m-%d')
        key = (cid, 'metrics10_20')

        # 1. Check persistent cache for today's value
        if cid in self.persistent_cache:
            cached_data = self.persistent_cache[cid]
            if cached_data.get("date") == today_str:
                return cached_data.get("ma10"), cached_data.get("ma20"), cached_data.get("adr")
        
        # In-memory cache checkout
        if key in self.ma_cache:
            (ma10, ma20, adr), ts = self.ma_cache[key]
            if (datetime.now() - ts).total_seconds() < 3600:
                return ma10, ma20, adr

        ma10 = ma20 = adr = None

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
                ma10 = sum(b.close for b in bars[-10:]) / 10
                if len(bars) >= 20:
                    ma20 = sum(b.close for b in bars[-20:]) / 20
                    adr = 100 * ((sum(b.high / b.low for b in bars[-20:]) / 20) - 1)
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
                    logger.info(f"Successfully fetched yfinance fallback for {symbol}")
            except Exception as e:
                logger.warning(f"yfinance fallback failed for {symbol}: {e}")

        # 4. Save to persistent cache if we got new values, otherwise use stale cache
        if adr is not None:
             self.persistent_cache[cid] = {
                 "date": today_str,
                 "ma10": float(ma10) if ma10 else None,
                 "ma20": float(ma20) if ma20 else None,
                 "adr": float(adr) if adr else None
             }
             loop = asyncio.get_event_loop()
             loop.run_in_executor(None, self._save_persistent_cache)
             
             results = (ma10, ma20, adr)
             self.ma_cache[key] = (results, datetime.now())
             return results
        else:
             # Final fallback: return stale persistent cache if available
             if cid in self.persistent_cache:
                 cached_data = self.persistent_cache[cid]
                 logger.info(f"Using stale persistent cache for {symbol} from {cached_data.get('date')}")
                 return cached_data.get("ma10"), cached_data.get("ma20"), cached_data.get("adr")
                 
             self.ma_cache[key] = ((None, None, None), datetime.now() - timedelta(minutes=59))
             return None, None, None

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

    async def connect(self, host='127.0.0.1', port=7496, client_id=10):
        loop = asyncio.get_event_loop()
        future = asyncio.run_coroutine_threadsafe(
            self._coro_connect(host, port, client_id), self._ib_loop
        )
        return await loop.run_in_executor(None, future.result, 30)

    def disconnect(self):
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
