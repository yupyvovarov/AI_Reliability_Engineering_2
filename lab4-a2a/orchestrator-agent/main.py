import os
import uuid

import httpx
from fastapi import FastAPI, Request

app = FastAPI(title="orchestrator-agent")

TIME_AGENT_URL = os.getenv("TIME_AGENT_URL", "http://time-agent:8080")

AGENT_CARD = {
    "name": "orchestrator-agent",
    "description": "Orchestrates time queries by delegating to time-agent via A2A",
    "url": "http://orchestrator-agent:8080",
    "version": "1.0.0",
    "capabilities": {"streaming": False},
    "authentication": {"schemes": ["none"]},
    "skills": [
        {
            "id": "query_time",
            "name": "Query Time",
            "description": "Accepts a natural language time query, delegates to time-agent, returns result",
            "inputModes": ["text/plain"],
            "outputModes": ["text/plain"],
        }
    ],
}


async def call_time_agent(query: str) -> str:
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "message/send",
        "params": {
            "message": {
                "messageId": str(uuid.uuid4()),
                "role": "user",
                "parts": [{"kind": "text", "text": query}],
            }
        },
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(TIME_AGENT_URL + "/", json=payload)
        resp.raise_for_status()
        data = resp.json()

    parts = (
        data.get("result", {})
        .get("status", {})
        .get("message", {})
        .get("parts", [])
    )
    return parts[0].get("text", "No response from time-agent") if parts else "No response from time-agent"


@app.get("/.well-known/agent.json")
def agent_card():
    return AGENT_CARD


@app.post("/")
async def handle_message(request: Request):
    body = await request.json()
    rpc_id = body.get("id")
    parts = body.get("params", {}).get("message", {}).get("parts", [])
    text = parts[0].get("text", "") if parts else ""

    if not text:
        result_text = "Please provide a query, e.g. 'What time is it in Kyiv?'"
    else:
        try:
            result_text = await call_time_agent(text)
        except Exception as e:
            result_text = f"Failed to reach time-agent: {e}"

    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "result": {
            "id": str(uuid.uuid4()),
            "status": {
                "state": "completed",
                "message": {
                    "role": "agent",
                    "parts": [{"kind": "text", "text": result_text}],
                },
            },
        },
    }
