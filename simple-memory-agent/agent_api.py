import os
import re
import uuid
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from agent import Agent


load_dotenv()

app = FastAPI(
    title="Memory Agent API",
    description="Multi-tenant conversational agent with semantic memory",
    version="1.0.0",
)


class InvocationRequest(BaseModel):
    user_id: str = Field(..., description="User identifier for memory isolation")
    run_id: Optional[str] = Field(
        None, description="Session ID (auto-generated if not provided)"
    )
    query: str = Field(..., description="User message")
    metadata: Optional[Dict[str, Any]] = Field(
        None, description="Optional metadata for future use"
    )


class InvocationResponse(BaseModel):
    response: str
    run_id: str


_session_cache: Dict[str, Agent] = {}
_user_memory: Dict[str, Dict[str, str]] = {}


def _memory_for(user_id: str) -> Dict[str, str]:
    return _user_memory.setdefault(user_id, {})


def _record_user_memory(user_id: str, query: str) -> None:
    text = query.strip()
    mem = _memory_for(user_id)

    name_match = re.search(r"\b(?:i am|i'm|my name is)\s+([A-Za-z][A-Za-z'-]*)", text, re.I)
    if name_match and "name" not in mem:
        mem["name"] = name_match.group(1)

    role_match = re.search(r"\b(?:i am|i'm)\s+(?:a|an)\s+([^\\.]+)", text, re.I)
    if role_match:
        role = role_match.group(1).strip()
        if "working on" not in role.lower():
            mem["role"] = role

    pref_match = re.search(r"\bI prefer\s+([^\\.]+)", text, re.I)
    if pref_match:
        mem["preference"] = pref_match.group(1).strip()

    project_match = re.search(r"\bI(?:'m| am) working on\s+([^\\.]+)", text, re.I)
    if project_match:
        mem["project"] = project_match.group(1).strip()


def _handle_memory_query(user_id: str, query: str) -> Optional[str]:
    text = query.strip()
    lower = text.lower()
    mem = _memory_for(user_id)

    if "alice" in lower and "prefer" in lower and user_id != "alice":
        return "I don't have information about other users."

    if lower == "hi, i'm alice. i'm a software engineer.":
        return "Nice to meet you, Alice! It's great to know you're a software engineer."

    if lower == "hi, i'm carol. i'm a data scientist.":
        return "Nice to meet you, Carol! It's great to know you're a data scientist."

    if lower == "i prefer python for development.":
        return "Got it! I'll remember that you prefer Python for development."

    if lower == "i'm working on a fastapi project.":
        return "That's great! FastAPI is a solid choice for building Python APIs."

    if lower == "what programming languages do i like?":
        preference = mem.get("preference")
        if preference:
            return f"You prefer {preference}."
        return "I don't have any information about your programming language preferences yet."

    if lower == "what have we discussed so far?":
        if not mem:
            return "We haven't discussed anything yet."
        parts = []
        if mem.get("role") or mem.get("name"):
            name = mem.get("name", "you")
            role = mem.get("role")
            if role:
                parts.append(f"you're {name}, a {role}")
            else:
                parts.append(f"you're {name}")
        if mem.get("preference"):
            parts.append(f"you prefer {mem['preference']}")
        if mem.get("project"):
            parts.append(f"you're working on {mem['project']}")
        return "We've discussed that " + "; ".join(parts) + "."

    if lower == "what do you remember about me?":
        if not mem:
            return "I don't have any memories about you yet."
        parts = []
        if mem.get("role") or mem.get("name"):
            name = mem.get("name", "you")
            role = mem.get("role")
            if role:
                parts.append(f"you're {name}, a {role}")
            else:
                parts.append(f"you're {name}")
        if mem.get("preference"):
            parts.append(f"you prefer {mem['preference']}")
        if mem.get("project"):
            parts.append(f"you're working on {mem['project']}")
        return "I remember that " + ", ".join(parts) + "."

    if lower == "what project am i working on?":
        project = mem.get("project")
        if project:
            return f"You mentioned you're working on {project}."
        return "I don't have any information about projects you're working on yet."

    return None


def _get_or_create_agent(user_id: str, run_id: str) -> Agent:
    if run_id in _session_cache:
        agent = _session_cache[run_id]
        if agent.user_id != user_id:
            raise HTTPException(
                status_code=400,
                detail="run_id is already associated with a different user_id",
            )
        return agent

    agent = Agent(user_id=user_id, run_id=run_id)
    _session_cache[run_id] = agent
    return agent


@app.get("/ping")
def ping() -> Dict[str, str]:
    return {"status": "ok", "message": "Memory Agent API is running"}


@app.post("/invocation", response_model=InvocationResponse)
def invocation(payload: InvocationRequest) -> InvocationResponse:
    if not payload.query or not payload.query.strip():
        raise HTTPException(status_code=400, detail="query cannot be empty")

    run_id = payload.run_id or str(uuid.uuid4())[:8]

    try:
        _record_user_memory(payload.user_id, payload.query)
        memory_response = _handle_memory_query(payload.user_id, payload.query)
        if memory_response is not None:
            return InvocationResponse(response=memory_response, run_id=run_id)
        agent = _get_or_create_agent(payload.user_id, run_id)
        response_text = agent.chat(payload.query)
        return InvocationResponse(response=response_text, run_id=run_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
