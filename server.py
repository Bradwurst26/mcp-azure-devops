from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from azure.devops.connection import Connection
from azure.devops.v7_1.core.core_client import CoreClient
from azure.devops.v7_1.work_item_tracking.models import JsonPatchOperation
from azure.devops.v7_1.work_item_tracking.work_item_tracking_client import (
    WorkItemTrackingClient,
)
from fastmcp import Context, FastMCP
from msrest.authentication import BasicAuthentication

AGILE_TEMPLATE_ID = "adcc42ab-9882-485e-a3ed-7678f01f66bc"

VALID_WORK_ITEM_TYPES = frozenset(
    {"Bug", "Product Backlog Item", "Feature", "Task", "Epic"}
)


def _get_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Environment variable {name} is required but not set")
    return value


def _org_url() -> str:
    return f"https://dev.azure.com/{_get_env('AZURE_DEVOPS_ORG')}"


def _default_project() -> str:
    return _get_env("AZURE_DEVOPS_PROJECT")


def get_clients() -> tuple[WorkItemTrackingClient, CoreClient]:
    credentials = BasicAuthentication("", _get_env("AZURE_DEVOPS_PAT"))
    connection = Connection(base_url=_org_url(), creds=credentials)
    wit_client = connection.clients.get_work_item_tracking_client()
    core_client = connection.clients.get_core_client()
    return wit_client, core_client


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    wit_client, core_client = get_clients()
    yield {"wit_client": wit_client, "core_client": core_client}


mcp = FastMCP(
    "Azure DevOps",
    instructions="Create and manage Azure DevOps projects and work items",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_field_ops(fields: dict[str, Any]) -> list[JsonPatchOperation]:
    return [
        JsonPatchOperation(op="add", path=f"/fields/{key}", value=value)
        for key, value in fields.items()
    ]


def _build_parent_op(parent_id: int, project: str | None = None) -> JsonPatchOperation:
    org = _org_url()
    proj = project or _default_project()
    parent_url = f"{org}/{proj}/_apis/wit/workItems/{parent_id}"
    return JsonPatchOperation(
        op="add",
        path="/relations/-",
        value={
            "rel": "System.LinkTypes.Hierarchy-Reverse",
            "url": parent_url,
        },
    )


def _build_patch_document(
    fields: dict[str, Any],
    parent_id: int | None = None,
    project: str | None = None,
) -> list[JsonPatchOperation]:
    ops = _build_field_ops(fields)
    if parent_id is not None:
        ops.append(_build_parent_op(parent_id, project))
    return ops


def _create_single(
    wit_client: WorkItemTrackingClient,
    work_item_type: str,
    fields: dict[str, Any],
    parent_id: int | None = None,
    project: str | None = None,
) -> dict[str, Any]:
    if work_item_type not in VALID_WORK_ITEM_TYPES:
        raise ValueError(
            f"Invalid work item type '{work_item_type}'. "
            f"Must be one of: {', '.join(sorted(VALID_WORK_ITEM_TYPES))}"
        )
    patch = _build_patch_document(fields, parent_id, project)
    result = wit_client.create_work_item(
        document=patch,
        project=project or _default_project(),
        type=work_item_type,
    )
    return {"id": result.id, "title": result.fields.get("System.Title", "")}


def _create_recursive(
    wit_client: WorkItemTrackingClient,
    items: list[dict[str, Any]],
    parent_id: int | None = None,
    project: str | None = None,
) -> list[dict[str, Any]]:
    results = []
    for item in items:
        created = _create_single(
            wit_client,
            work_item_type=item["type"],
            fields=item["fields"],
            parent_id=parent_id,
            project=project,
        )
        children = item.get("children", [])
        if children:
            created["children"] = _create_recursive(
                wit_client, children, parent_id=created["id"], project=project
            )
        results.append(created)
    return results


def _update_single(
    wit_client: WorkItemTrackingClient,
    work_item_id: int,
    fields: dict[str, Any],
    project: str | None = None,
) -> dict[str, Any]:
    patch = _build_field_ops(fields)
    result = wit_client.update_work_item(
        document=patch,
        id=work_item_id,
        project=project or _default_project(),
    )
    return {"id": result.id, "title": result.fields.get("System.Title", "")}


def _update_recursive(
    wit_client: WorkItemTrackingClient,
    items: list[dict[str, Any]],
    project: str | None = None,
) -> list[dict[str, Any]]:
    results = []
    for item in items:
        updated = _update_single(
            wit_client,
            work_item_id=item["id"],
            fields=item["fields"],
            project=project,
        )
        children = item.get("children", [])
        if children:
            updated["children"] = _update_recursive(
                wit_client, children, project=project
            )
        results.append(updated)
    return results


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool
def create_project(
    name: str,
    description: str = "",
    source_control_type: str = "Git",
    process_template_id: str = AGILE_TEMPLATE_ID,
    ctx: Context | None = None,
) -> str:
    """Create a new Azure DevOps project.

    Args:
        name: Project name.
        description: Optional project description.
        source_control_type: "Git" (default) or "Tfvc".
        process_template_id: Process template GUID. Defaults to Agile.
    """
    from azure.devops.v7_1.core.models import TeamProject

    if ctx and ctx.lifespan_context:
        core_client = ctx.lifespan_context["core_client"]
    else:
        _, core_client = get_clients()

    project = TeamProject(
        name=name,
        description=description,
        capabilities={
            "versioncontrol": {"sourceControlType": source_control_type},
            "processTemplate": {"templateTypeId": process_template_id},
        },
    )
    operation = core_client.queue_create_project(project)
    return json.dumps(
        {"id": str(operation.id), "status": str(operation.status), "name": name}
    )


@mcp.tool
def create_work_item(
    work_item_type: str,
    fields: dict[str, Any],
    parent_id: int | None = None,
    project: str | None = None,
    ctx: Context | None = None,
) -> str:
    """Create a single Azure DevOps work item.

    Args:
        work_item_type: One of "Bug", "Product Backlog Item", "Feature", "Task", "Epic".
        fields: Dict of Azure DevOps field paths to values, e.g. {"System.Title": "Fix login"}.
        parent_id: Optional ID of the parent work item to link under.
        project: Optional project name override (defaults to AZURE_DEVOPS_PROJECT env var).
    """
    if ctx and ctx.lifespan_context:
        wit_client = ctx.lifespan_context["wit_client"]
    else:
        wit_client, _ = get_clients()

    result = _create_single(wit_client, work_item_type, fields, parent_id, project)
    return json.dumps(result)


@mcp.tool
def create_work_items(
    items: list[dict[str, Any]],
    parent_id: int | None = None,
    project: str | None = None,
    ctx: Context | None = None,
) -> str:
    """Create multiple Azure DevOps work items from a nested structure.

    Each item in the list should have:
      - "type": Work item type (e.g. "Epic", "Feature", "Product Backlog Item", "Bug", "Task")
      - "fields": Dict of field paths to values (must include "System.Title")
      - "children": Optional list of child items (same structure, nested recursively)

    Args:
        items: List of work item definitions, optionally nested via "children".
        parent_id: Optional ID of the top-level parent to nest all root items under.
        project: Optional project name override.
    """
    if ctx and ctx.lifespan_context:
        wit_client = ctx.lifespan_context["wit_client"]
    else:
        wit_client, _ = get_clients()

    results = _create_recursive(wit_client, items, parent_id, project)
    return json.dumps(results)


@mcp.tool
def update_work_item(
    work_item_id: int,
    fields: dict[str, Any],
    project: str | None = None,
    ctx: Context | None = None,
) -> str:
    """Update a single existing Azure DevOps work item.

    Args:
        work_item_id: ID of the work item to update.
        fields: Dict of field paths to new values, e.g. {"System.State": "Active"}.
        project: Optional project name override.
    """
    if ctx and ctx.lifespan_context:
        wit_client = ctx.lifespan_context["wit_client"]
    else:
        wit_client, _ = get_clients()

    result = _update_single(wit_client, work_item_id, fields, project)
    return json.dumps(result)


@mcp.tool
def update_work_items(
    items: list[dict[str, Any]],
    project: str | None = None,
    ctx: Context | None = None,
) -> str:
    """Update multiple existing Azure DevOps work items.

    Each item in the list should have:
      - "id": The work item ID to update
      - "fields": Dict of field paths to new values
      - "children": Optional list of child items to update (same structure)

    Args:
        items: List of update definitions, optionally nested via "children".
        project: Optional project name override.
    """
    if ctx and ctx.lifespan_context:
        wit_client = ctx.lifespan_context["wit_client"]
    else:
        wit_client, _ = get_clients()

    results = _update_recursive(wit_client, items, project)
    return json.dumps(results)


if __name__ == "__main__":
    mcp.run()
