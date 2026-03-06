import sys
import os
import asyncio

# Critical: Patch asyncio before importing uvicorn or FastAPI
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn

# Add backend to path
sys.path.append(os.path.join(os.path.dirname(__file__), "backend"))

if __name__ == "__main__":
    print("--------------------------------------------------")
    print("Starting IBKR Risk Monitor...")
    print("Dashboard URL: http://localhost:8000/ui/index.html")
    print("--------------------------------------------------")
    
    try:
        from backend.main import app
        uvicorn.run(app, host="0.0.0.0", port=8000)
    except ImportError as e:
        print(f"Error: Could not find backend modules. {e}")
    except Exception as e:
        print(f"Error starting server: {e}")
