from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
import uvicorn
import asyncio
import os
import sys

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # This runs inside the FastAPI event loop
    from ib_manager import IBManager
    app.state.ib_manager = IBManager()
    yield
    if hasattr(app.state, "ib_manager"):
        app.state.ib_manager.disconnect()

app = FastAPI(title="IBKR Portfolio Momentum API", lifespan=lifespan)

# Mount static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)
app.mount("/ui", StaticFiles(directory=static_dir, html=True), name="static")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ConnectRequest(BaseModel):
    host: str = "127.0.0.1"
    port: int = 7496
    clientId: int = 10

class DataRequest(BaseModel):
    accountId: str
    maPeriod: int = 20

@app.get("/api/status")
async def get_status():
    mgr = app.state.ib_manager
    ib = mgr.ib
    connected = ib.isConnected() if ib else False
    return {
        "connected": connected,
        "client_id": ib.client.clientId if connected else None
    }

@app.post("/api/connect")
async def connect_ib(req: ConnectRequest):
    res = await app.state.ib_manager.connect(req.host, req.port, req.clientId)
    if res["status"] == "error":
        raise HTTPException(status_code=400, detail=res["message"])
    return res

@app.post("/api/disconnect")
async def disconnect_ib():
    return app.state.ib_manager.disconnect()

@app.post("/api/data")
async def get_data(req: DataRequest):
    mgr = app.state.ib_manager
    if not mgr.ib or not mgr.ib.isConnected():
        raise HTTPException(status_code=400, detail="IB not connected")
    
    res = await mgr.fetch_data(req.accountId, req.maPeriod)
    if res["status"] == "error":
        raise HTTPException(status_code=500, detail=res["message"])
    return res

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
