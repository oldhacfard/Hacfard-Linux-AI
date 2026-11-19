# Hacfard Linux AI

A Claude-style AI chat + Linux terminal workspace that runs locally through Docker Desktop. This is an original project, not a copied repository.

## Features

- Responsive dark chat interface and a separate Linux terminal tab
- AI tool-calling through an OpenAI-compatible Chat Completions API
- Linux command execution inside a non-root Docker container
- AI file creation/editing limited to persistent `/workspace`
- Docker hardening: read-only root filesystem, dropped Linux capabilities, no-new-privileges, PID/memory/CPU limits
- No Docker socket mount and no host filesystem mount

## Quick start (Windows 10 + Docker Desktop)

1. Start Docker Desktop.
2. Clone this repository or download it as a ZIP.
3. Copy `.env.example` to `.env`.
4. Set provider details in `.env`:

```env
AI_BASE_URL=https://api.openai.com/v1
AI_API_KEY=your_api_key
AI_MODEL=gpt-4o-mini
```

Use an OpenAI-compatible provider that supports Chat Completions and tool calling. Keep your real API key only in `.env`; never commit it.

5. In PowerShell, from the project folder, run:

```powershell
docker compose up --build -d
```

6. Open http://localhost:8000

Stop the app with `docker compose down`. Workspace files persist in the `hacfard_workspace` Docker volume.

## Security

Commands execute as an unprivileged user inside the app container. A strict command allowlist rejects shell chaining, redirection, privilege escalation, Docker/Podman access, host absolute paths and common network/system administration commands. The container has no Docker socket and no host directory bind mount.

**Do not expose port 8000 directly to the public internet.** The starter UI has no login/authentication. Keep it local or add authentication and HTTPS before remote access. Review the command policy before expanding its allowlist.

## Limitations

- AI chat requires an API key and a provider/model supporting tool calling.
- The terminal is intentionally restricted; arbitrary shell scripts, sudo and host control are not enabled.
- This is a containerized Linux workspace, not a bootable Linux distribution.
- File writes are limited to the workspace.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `AI_BASE_URL` | OpenAI API URL | OpenAI-compatible API base |
| `AI_API_KEY` | empty | Secret API key |
| `AI_MODEL` | `gpt-4o-mini` | Model name |
| `WORKSPACE` | `/workspace` | Persistent working directory |
| `MAX_STEPS` | `6` | Maximum tool rounds per request |
| `COMMAND_TIMEOUT` | `20` | Per-command timeout in seconds |

## API

- `GET /api/health`
- `GET /api/files`
- `POST /api/chat` with `{"message":"...","history":[]}`
- `POST /api/terminal` with `{"command":"pwd"}`

## License

MIT
