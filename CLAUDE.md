# Azure DevOps MCP Server

## Project overview

A Python MCP (Model Context Protocol) server built with FastMCP 3.x that creates and manages Azure DevOps projects and work items. It exposes 5 tools over stdio: `create_project`, `create_work_item`, `create_work_items`, `update_work_item`, `update_work_items`.

## Tech stack

- Python 3.12+
- FastMCP 3.x (`fastmcp` package) — MCP server framework
- `azure-devops` 7.1 SDK — Azure DevOps REST API client
- `pytest` + `pytest-asyncio` — unit testing
- `uv` — package manager and virtual environment

## Directory structure

```
server.py              # MCP server entry point — all tools and helpers
tests/
  __init__.py
  test_server.py       # Unit tests (mocked Azure DevOps clients)
pyproject.toml         # uv-managed dependencies
uv.lock                # Lockfile (do not edit manually)
```

## Environment setup

```bash
uv sync                              # install all dependencies
uv run python server.py              # run the MCP server
uv run pytest tests/ -v              # run tests
```

Required environment variables (never commit real values):
- `AZURE_DEVOPS_PAT` — Personal Access Token
- `AZURE_DEVOPS_ORG` — Organization name
- `AZURE_DEVOPS_PROJECT` — Default project name

## Coding conventions

- Use `from __future__ import annotations` at the top of every Python file.
- Type-hint all function signatures using `dict[str, Any]`, `list[...]`, `int | None` syntax.
- Prefix internal helpers with `_` (e.g. `_build_patch_document`, `_create_recursive`).
- Tool functions are decorated with `@mcp.tool` and return JSON strings via `json.dumps()`.
- Each tool accepts an optional `ctx: Context | None = None` parameter for lifespan access.
- Valid work item types: `Bug`, `Product Backlog Item`, `Feature`, `Task`, `Epic`.
- Tests mock Azure DevOps SDK clients with `unittest.mock.MagicMock` — no real API calls.
- Tests use `unittest.mock.patch("server.get_clients", ...)` to inject mocked clients.

## Testing requirements

- All new tools and helpers must have corresponding unit tests in `tests/test_server.py`.
- Tests must pass before any commit: run `uv run pytest tests/ -v` and confirm 0 failures.
- When adding a new tool, follow the existing pattern: test the helper function directly, then test the `@mcp.tool` wrapper via direct function call with patched `get_clients`.

## Commit and push policy

- After every tested change that is confirmed working (all tests pass), create a git commit with a descriptive message and push to the remote.
- Do not batch unrelated changes into a single commit.
- Run `uv run pytest tests/ -v` before every commit to verify nothing is broken.

## Instruction file sync

This project maintains three instruction files with identical guidance:
- `.cursor/rules/azure-devops-mcp.mdc` (Cursor)
- `CLAUDE.md` (this file — Claude Code)
- `.github/copilot-instructions.md` (GitHub Copilot)

Whenever the content of any instruction file is modified, the same change must be applied to the other two files in the same commit.
