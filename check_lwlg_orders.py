import asyncio
from ib_insync import IB
import sys

async def main():
    ib = IB()
    try:
        # Try common ports
        for port in [7496, 7497]:
            try:
                print(f"Attempting to connect to TWS on port {port}...")
                await ib.connectAsync('127.0.0.1', port, clientId=99)
                print(f"Connected to port {port}")
                break
            except Exception as e:
                print(f"Port {port} failed: {e}")
        
        if not ib.isConnected():
            print("Could not connect to TWS. Please ensure TWS is open and API is enabled.")
            return

        print("\n--- ALL OPEN ORDERS ---")
        trades = await ib.reqAllOpenOrdersAsync()
        for i, t in enumerate(trades):
            o = t.order
            print(f"\nOrder {i+1}: {t.contract.symbol}")
            print(f"  Type: {o.orderType}")
            print(f"  TIF: {o.tif}")
            print(f"  OrderId: {o.orderId}")
            print(f"  PermId: {o.permId}")
            print(f"  Status: {t.orderStatus.status}")

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        ib.disconnect()
        print("\nDisconnected.")

if __name__ == "__main__":
    asyncio.run(main())
