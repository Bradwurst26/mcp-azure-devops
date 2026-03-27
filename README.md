# Azure DevOps MCP Server

An MCP (Model Context Protocol) server for creating and managing Azure DevOps projects and work items via AI agents.

## Tools

| Tool | Description |
|------|-------------|
| `create_project` | Create a new Azure DevOps project |
| `create_work_item` | Create a single work item (Bug, PBI, Feature, Task, Epic) |
| `create_work_items` | Create multiple work items from a nested hierarchy |
| `update_work_item` | Update a single existing work item |
| `update_work_items` | Update multiple existing work items in a nested structure |

## Setup

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- An Azure DevOps Personal Access Token (PAT) with work item read/write permissions

### Install dependencies

```bash
cd azure-devops
uv sync
```

### Environment variables

Set the following before running the server:

```bash
export AZURE_DEVOPS_PAT="your-personal-access-token"
export AZURE_DEVOPS_ORG="your-organization-name"
export AZURE_DEVOPS_PROJECT="your-default-project"
```

### Run the server

```bash
uv run python server.py
```

### Cursor / MCP client configuration

Add to your MCP client config (e.g. `.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "azure-devops": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/azure-devops", "python", "server.py"],
      "env": {
        "AZURE_DEVOPS_PAT": "your-pat",
        "AZURE_DEVOPS_ORG": "your-org",
        "AZURE_DEVOPS_PROJECT": "your-project"
      }
    }
  }
}
```

## Usage examples

### Create a single work item

```json
{
  "work_item_type": "Bug",
  "fields": {
    "System.Title": "Login page crashes on submit",
    "System.Description": "Repro: click submit with empty form"
  },
  "parent_id": 42
}
```

Returns: `{"id": 123, "title": "Login page crashes on submit"}`

### Create a nested hierarchy

```json
{
  "items": [
    {
      "type": "Epic",
      "fields": {"System.Title": "Q3 Deliverables"},
      "children": [
        {
          "type": "Feature",
          "fields": {"System.Title": "Auth module"},
          "children": [
            {
              "type": "Product Backlog Item",
              "fields": {"System.Title": "Login page"},
              "children": [
                {"type": "Task", "fields": {"System.Title": "Build login form"}}
              ]
            }
          ]
        }
      ]
    }
  ],
  "parent_id": 10
}
```

Returns a mirrored structure with `id` and `title` at each level.

### Update multiple work items

```json
{
  "items": [
    {
      "id": 100,
      "fields": {"System.State": "Resolved"},
      "children": [
        {
          "id": 101,
          "fields": {"System.State": "Active"}
        }
      ]
    }
  ]
}
```

## Testing

```bash
uv run pytest tests/ -v
```
