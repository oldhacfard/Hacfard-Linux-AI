import json
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

APP_DIR = Path(__file__).resolve().parent.parent
WORKSPACE = Path(os.getenv("WORKSPACE", "/workspace")).resolve()
WORKSPACE.mkdir(parents=True, exist_ok=True)
BASE_URL = os.getenv("AI_BASE_URL", "https://ai-gateway.kilo.ai/api/v1").rstrip("/")
API_KEY = os.getenv("AI_API_KEY", "").strip()
MODEL = os.getenv("AI_MODEL", "minimax/minimax-m2.1:free")
MAX_STEPS = min(int(os.getenv("MAX_STEPS", "6")), 10)
TIMEOUT = min(int(os.getenv("COMMAND_TIMEOUT", "20")), 60)

app = FastAPI(title="Hacfard Linux AI", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")

SYSTEM_PROMPT = """You are Hacfard Linux AI, a helpful Linux workspace agent.
You operate ONLY inside a disposable, non-root Docker container. The current directory is /workspace.
Help the user with Linux tasks. Use run_command for safe, ordinary Linux commands and write_file for creating or editing project files.
Explain what you are doing in concise Turkish unless the user writes another language.
Never claim an action succeeded unless the tool result confirms it. Inspect before changing files.
Commands are automatically executed only when they pass the server's strict safety filter.
Do not try privilege escalation, access host files, access Docker, mount devices, alter networking, or disable security.
If a command is blocked, explain why and suggest a safe alternative.
"""

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    history: list[dict[str, str]] = Field(default_factory=list)

def safe_path(raw: str) -> Path:
    candidate = (WORKSPACE / raw).resolve()
    if candidate != WORKSPACE and WORKSPACE not in candidate.parents:
        raise ValueError("Path must stay inside /workspace.")
    return candidate

BLOCKED = re.compile(r"(;|&&|\|\||\||>|<|\$\(|`|\n|\r)")
ALLOWED = {
    "pwd", "ls", "dir", "whoami", "id", "uname", "date", "echo",
    "cat", "head", "tail", "wc", "grep", "find", "tree", "stat",
    "file", "which", "python", "python3", "pip", "pip3", "git",
    "env", "printenv", "df", "du", "free", "ps"
}
DENIED_WORDS = {
    "sudo", "su", "doas", "mount", "umount", "docker", "podman",
    "iptables", "ufw", "systemctl", "reboot", "shutdown", "mkfs",
    "dd", "fdisk", "parted", "passwd", "useradd", "userdel",
    "curl", "wget", "ssh", "scp", "nc", "netcat"
}

def run_command(command: str) -> dict[str, Any]:
    if len(command) > 1000 or BLOCKED.search(command):
        return {"ok": False, "error": "Komut güvenlik filtresine takıldı (zincirleme komut, yönlendirme veya çoklu satır kapalı)."}
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if not parts:
        return {"ok": False, "error": "Boş komut."}
    if any(Path(p).name in DENIED_WORDS for p in parts):
        return {"ok": False, "error": "Bu komut güvenlik nedeniyle engellendi."}
    executable = Path(parts[0]).name
    if executable not in ALLOWED:
        return {"ok": False, "error": f"'{executable}' izin verilen komut listesinde değil."}
    # Keep path arguments and working directory inside the workspace.
    for arg in parts[1:]:
        if arg.startswith("/") and arg not in ("/workspace",):
            return {"ok": False, "error": "Mutlak dosya yollarına erişim kapalı; göreli yol kullan."}
        if arg == ".." or arg.startswith("../") or "/../" in arg:
            return {"ok": False, "error": "Üst dizine çıkış engellendi."}
    try:
        result = subprocess.run(parts, cwd=WORKSPACE, text=True, capture_output=True,
                                timeout=TIMEOUT, check=False, env={"PATH": os.getenv("PATH", "/usr/local/bin:/usr/bin:/bin"),
                                "HOME": "/home/app", "PYTHONUNBUFFERED": "1"})
        output = (result.stdout + result.stderr).strip()
        return {"ok": result.returncode == 0, "exit_code": result.returncode,
                "output": output[:12000] or "(çıktı yok)"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Komut {TIMEOUT} saniyede zaman aşımına uğradı."}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

def write_file(path: str, content: str) -> dict[str, Any]:
    if len(content) > 100_000:
        return {"ok": False, "error": "Dosya 100 KB sınırını aşıyor."}
    try:
        target = safe_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {"ok": True, "path": str(target.relative_to(WORKSPACE)), "bytes": len(content.encode("utf-8"))}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

TOOLS = [
    {"type": "function", "function": {"name": "run_command", "description": "Run one safe Linux command inside /workspace.", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "write_file", "description": "Create or replace a text file inside /workspace.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}}
]

async def call_model(messages: list[dict[str, Any]]) -> dict[str, Any]:
    url = BASE_URL + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if API_KEY and API_KEY != "replace_me":
        headers["Authorization"] = f"Bearer {API_KEY}"
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(url, headers=headers,
                                     json={"model": MODEL, "messages": messages, "tools": TOOLS, "tool_choice": "auto"})
        if response.status_code >= 400:
            raise HTTPException(502, f"AI sağlayıcısı hata verdi ({response.status_code}): {response.text[:600]}")
        return response.json()["choices"][0]["message"]

@app.get("/")
async def index():
    return FileResponse(APP_DIR / "static" / "index.html")

@app.get("/api/health")
async def health():
    return {"ok": True, "ai_configured": True, "provider": "Kilo Gateway",
            "authentication": "api_key" if API_KEY and API_KEY != "replace_me" else "anonymous_free",
            "model": MODEL, "workspace": str(WORKSPACE)}

@app.get("/api/files")
async def list_files():
    items = []
    for p in sorted(WORKSPACE.rglob("*")):
        if p.is_file():
            items.append({"path": str(p.relative_to(WORKSPACE)), "bytes": p.stat().st_size})
            if len(items) >= 200:
                break
    return {"files": items}

@app.post("/api/chat")
async def chat(body: ChatRequest):
    history = [{"role": m["role"], "content": m["content"]} for m in body.history[-12:]
               if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)]
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}, *history,
                                      {"role": "user", "content": body.message}]
    events = []
    for _ in range(MAX_STEPS):
        assistant = await call_model(messages)
        messages.append(assistant)
        calls = assistant.get("tool_calls") or []
        if not calls:
            return {"reply": assistant.get("content") or "Tamamlandı.", "events": events}
        for call in calls:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"]["arguments"])
            except Exception:
                args = {}
            if name == "run_command":
                result = run_command(str(args.get("command", "")))
                events.append({"type": "command", "input": args.get("command", ""), **result})
            elif name == "write_file":
                result = write_file(str(args.get("path", "")), str(args.get("content", "")))
                events.append({"type": "file", **result})
            else:
                result = {"ok": False, "error": "Bilinmeyen araç."}
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, ensure_ascii=False)})
    return {"reply": "Güvenlik için bu istekteki araç adımı sınırına ulaştım. Sonuçları kontrol edip devam edebilirsin.", "events": events}

@app.post("/api/terminal")
async def terminal(body: dict):
    command = str(body.get("command", ""))
    result = run_command(command)
    return result
