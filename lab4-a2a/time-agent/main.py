import uuid
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="time-agent")

CITY_TO_TZ: dict[str, str] = {
    "kyiv": "Europe/Kyiv",
    "kiev": "Europe/Kyiv",
    "london": "Europe/London",
    "berlin": "Europe/Berlin",
    "paris": "Europe/Paris",
    "new york": "America/New_York",
    "los angeles": "America/Los_Angeles",
    "tokyo": "Asia/Tokyo",
    "dubai": "Asia/Dubai",
    "warsaw": "Europe/Warsaw",
}

AGENT_CARD = {
    "name": "time-agent",
    "description": "Returns current time for a given city or timezone",
    "url": "http://time-agent:8080",
    "version": "1.0.0",
    "capabilities": {"streaming": False},
    "authentication": {"schemes": ["none"]},
    "skills": [
        {
            "id": "get_current_time",
            "name": "Get Current Time",
            "description": "Returns current time for a city or IANA timezone name",
            "inputModes": ["text/plain"],
            "outputModes": ["text/plain"],
        }
    ],
}


def resolve_timezone(text: str) -> str:
    lower = text.lower()
    for city, tz in CITY_TO_TZ.items():
        if city in lower:
            return tz
    # assume the text itself is an IANA tz name
    return text.strip()


def get_time_for(text: str) -> str:
    tz_name = resolve_timezone(text)
    try:
        tz = ZoneInfo(tz_name)
        now = datetime.now(tz)
        return f"Current time in {tz_name}: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}"
    except ZoneInfoNotFoundError:
        return f"Unknown city or timezone: '{text}'"


@app.get("/.well-known/agent.json")
def agent_card():
    return AGENT_CARD


@app.post("/")
async def handle_message(request: Request):
    body = await request.json()
    rpc_id = body.get("id")
    parts = body.get("params", {}).get("message", {}).get("parts", [])
    text = parts[0].get("text", "") if parts else ""

    result_text = get_time_for(text) if text else "Please provide a city or timezone."

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
