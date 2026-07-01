from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel

from app.config import NODE_API_KEY

router = APIRouter(prefix="/api/node", tags=["node"])

def verify_node_key(x_node_key: str = Header(...)):
    if x_node_key != NODE_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid Node API Key")
    return True

class NodeHeartbeat(BaseModel):
    node_id: str
    capacity: int
    active_workers: int
    version: Optional[str] = ""

@router.post("/heartbeat")
async def node_heartbeat(data: NodeHeartbeat, _=Depends(verify_node_key)):
    return {
        "launch": None,
        "shutdown": None,
        "jobs_pending": 0
    }

@router.get("/list")
async def node_list():
    return []

@router.get("/jobs")
async def get_jobs(node_id: str, _=Depends(verify_node_key)):
    return {"job": None}

@router.get("/token/{email}")
async def get_token(email: str, _=Depends(verify_node_key)):
    raise HTTPException(status_code=404, detail="Token not found")

class StatusUpdate(BaseModel):
    email: str
    status: str
    colab_pid: Optional[int] = None
    worker_session_id: Optional[str] = None
    error: Optional[str] = None

@router.post("/status")
async def update_status(data: StatusUpdate, _=Depends(verify_node_key)):
    return {"success": True}
