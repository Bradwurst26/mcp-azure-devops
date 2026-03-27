from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("AZURE_DEVOPS_PAT", "fake-pat")
os.environ.setdefault("AZURE_DEVOPS_ORG", "testorg")
os.environ.setdefault("AZURE_DEVOPS_PROJECT", "testproject")

from server import (  # noqa: E402
    _build_patch_document,
    _create_recursive,
    _create_single,
    _update_recursive,
    _update_single,
    mcp,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_work_item(work_item_id: int, title: str) -> MagicMock:
    wi = MagicMock()
    wi.id = work_item_id
    wi.fields = {"System.Title": title}
    wi.url = f"https://dev.azure.com/testorg/testproject/_apis/wit/workItems/{work_item_id}"
    return wi


@pytest.fixture
def wit_client():
    return MagicMock()


@pytest.fixture
def core_client():
    return MagicMock()


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------


class TestBuildPatchDocument:
    def test_fields_only(self):
        ops = _build_patch_document({"System.Title": "Bug1", "System.State": "New"})
        assert len(ops) == 2
        assert ops[0].op == "add"
        assert ops[0].path == "/fields/System.Title"
        assert ops[0].value == "Bug1"
        assert ops[1].path == "/fields/System.State"

    def test_with_parent_id(self):
        ops = _build_patch_document({"System.Title": "Task1"}, parent_id=99)
        parent_op = [o for o in ops if o.path == "/relations/-"]
        assert len(parent_op) == 1
        assert parent_op[0].value["rel"] == "System.LinkTypes.Hierarchy-Reverse"
        assert "99" in parent_op[0].value["url"]

    def test_no_parent_no_relation_op(self):
        ops = _build_patch_document({"System.Title": "Solo"})
        relation_ops = [o for o in ops if o.path == "/relations/-"]
        assert len(relation_ops) == 0


# ---------------------------------------------------------------------------
# create_project tests
# ---------------------------------------------------------------------------


class TestCreateProject:
    def test_creates_project_with_defaults(self, core_client):
        op_ref = MagicMock()
        op_ref.id = "op-123"
        op_ref.status = "queued"
        core_client.queue_create_project.return_value = op_ref

        with patch("server.get_clients", return_value=(None, core_client)):
            from server import create_project

            result = json.loads(create_project(name="MyProject"))

        assert result["name"] == "MyProject"
        assert result["id"] == "op-123"
        assert result["status"] == "queued"
        core_client.queue_create_project.assert_called_once()
        project_arg = core_client.queue_create_project.call_args[0][0]
        assert project_arg.name == "MyProject"

    def test_creates_project_with_custom_params(self, core_client):
        op_ref = MagicMock()
        op_ref.id = "op-456"
        op_ref.status = "queued"
        core_client.queue_create_project.return_value = op_ref

        with patch("server.get_clients", return_value=(None, core_client)):
            from server import create_project

            result = json.loads(
                create_project(
                    name="CustomProj",
                    description="A custom project",
                    source_control_type="Tfvc",
                )
            )

        assert result["name"] == "CustomProj"
        project_arg = core_client.queue_create_project.call_args[0][0]
        assert project_arg.description == "A custom project"
        assert project_arg.capabilities["versioncontrol"]["sourceControlType"] == "Tfvc"

    def test_create_project_api_error(self, core_client):
        core_client.queue_create_project.side_effect = RuntimeError("API down")

        with patch("server.get_clients", return_value=(None, core_client)):
            from server import create_project

            with pytest.raises(RuntimeError, match="API down"):
                create_project(name="FailProject")


# ---------------------------------------------------------------------------
# create_work_item tests
# ---------------------------------------------------------------------------


class TestCreateWorkItem:
    def test_create_bug(self, wit_client):
        wit_client.create_work_item.return_value = _make_work_item(42, "Login bug")

        result = _create_single(
            wit_client, "Bug", {"System.Title": "Login bug"}
        )

        assert result == {"id": 42, "title": "Login bug"}
        wit_client.create_work_item.assert_called_once()
        call_kwargs = wit_client.create_work_item.call_args
        assert call_kwargs.kwargs["type"] == "Bug"
        assert call_kwargs.kwargs["project"] == "testproject"

    def test_create_with_parent(self, wit_client):
        wit_client.create_work_item.return_value = _make_work_item(43, "Sub-task")

        result = _create_single(
            wit_client, "Task", {"System.Title": "Sub-task"}, parent_id=10
        )

        assert result == {"id": 43, "title": "Sub-task"}
        doc = wit_client.create_work_item.call_args.kwargs["document"]
        relation_ops = [o for o in doc if o.path == "/relations/-"]
        assert len(relation_ops) == 1
        assert "10" in relation_ops[0].value["url"]

    def test_create_with_project_override(self, wit_client):
        wit_client.create_work_item.return_value = _make_work_item(44, "Custom proj item")

        _create_single(
            wit_client, "Feature", {"System.Title": "Custom proj item"}, project="other"
        )

        assert wit_client.create_work_item.call_args.kwargs["project"] == "other"

    def test_invalid_type_raises(self, wit_client):
        with pytest.raises(ValueError, match="Invalid work item type"):
            _create_single(wit_client, "InvalidType", {"System.Title": "x"})

    def test_all_valid_types(self, wit_client):
        for wtype in ["Bug", "Product Backlog Item", "Feature", "Task", "Epic"]:
            wit_client.create_work_item.return_value = _make_work_item(1, "t")
            result = _create_single(wit_client, wtype, {"System.Title": "t"})
            assert result["id"] == 1


# ---------------------------------------------------------------------------
# create_work_items tests
# ---------------------------------------------------------------------------


class TestCreateWorkItems:
    def test_flat_list(self, wit_client):
        call_count = 0

        def mock_create(**kwargs):
            nonlocal call_count
            call_count += 1
            return _make_work_item(call_count, kwargs["document"][0].value)

        wit_client.create_work_item.side_effect = mock_create

        items = [
            {"type": "Bug", "fields": {"System.Title": "Bug1"}},
            {"type": "Task", "fields": {"System.Title": "Task1"}},
        ]
        results = _create_recursive(wit_client, items, parent_id=50)

        assert len(results) == 2
        assert results[0] == {"id": 1, "title": "Bug1"}
        assert results[1] == {"id": 2, "title": "Task1"}
        assert wit_client.create_work_item.call_count == 2

    def test_nested_hierarchy(self, wit_client):
        id_counter = [0]

        def mock_create(**kwargs):
            id_counter[0] += 1
            title = next(
                o.value for o in kwargs["document"] if o.path == "/fields/System.Title"
            )
            return _make_work_item(id_counter[0], title)

        wit_client.create_work_item.side_effect = mock_create

        items = [
            {
                "type": "Epic",
                "fields": {"System.Title": "Epic1"},
                "children": [
                    {
                        "type": "Feature",
                        "fields": {"System.Title": "Feature1"},
                        "children": [
                            {
                                "type": "Product Backlog Item",
                                "fields": {"System.Title": "PBI1"},
                                "children": [
                                    {"type": "Task", "fields": {"System.Title": "Task1"}},
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
        results = _create_recursive(wit_client, items, parent_id=None)

        assert results[0]["id"] == 1
        assert results[0]["title"] == "Epic1"
        assert results[0]["children"][0]["id"] == 2
        assert results[0]["children"][0]["title"] == "Feature1"
        assert results[0]["children"][0]["children"][0]["id"] == 3
        assert results[0]["children"][0]["children"][0]["children"][0]["id"] == 4
        assert wit_client.create_work_item.call_count == 4

    def test_parent_id_chaining(self, wit_client):
        """Verify that child items receive the created parent's ID as parent_id."""
        id_counter = [100]

        def mock_create(**kwargs):
            id_counter[0] += 1
            title = next(
                o.value for o in kwargs["document"] if o.path == "/fields/System.Title"
            )
            return _make_work_item(id_counter[0], title)

        wit_client.create_work_item.side_effect = mock_create

        items = [
            {
                "type": "Feature",
                "fields": {"System.Title": "F1"},
                "children": [
                    {"type": "Task", "fields": {"System.Title": "T1"}},
                ],
            }
        ]
        _create_recursive(wit_client, items, parent_id=50)

        # First call: Feature with parent 50
        first_doc = wit_client.create_work_item.call_args_list[0].kwargs["document"]
        parent_ops_1 = [o for o in first_doc if o.path == "/relations/-"]
        assert len(parent_ops_1) == 1
        assert "50" in parent_ops_1[0].value["url"]

        # Second call: Task with parent 101 (the created Feature)
        second_doc = wit_client.create_work_item.call_args_list[1].kwargs["document"]
        parent_ops_2 = [o for o in second_doc if o.path == "/relations/-"]
        assert len(parent_ops_2) == 1
        assert "101" in parent_ops_2[0].value["url"]


# ---------------------------------------------------------------------------
# update_work_item tests
# ---------------------------------------------------------------------------


class TestUpdateWorkItem:
    def test_update_fields(self, wit_client):
        wit_client.update_work_item.return_value = _make_work_item(10, "Updated Bug")

        result = _update_single(
            wit_client, 10, {"System.State": "Resolved", "System.AssignedTo": "dev@org.com"}
        )

        assert result == {"id": 10, "title": "Updated Bug"}
        wit_client.update_work_item.assert_called_once()
        call_kwargs = wit_client.update_work_item.call_args.kwargs
        assert call_kwargs["id"] == 10
        assert len(call_kwargs["document"]) == 2

    def test_update_with_project_override(self, wit_client):
        wit_client.update_work_item.return_value = _make_work_item(11, "Item")

        _update_single(wit_client, 11, {"System.State": "Active"}, project="otherproj")

        assert wit_client.update_work_item.call_args.kwargs["project"] == "otherproj"


# ---------------------------------------------------------------------------
# update_work_items tests
# ---------------------------------------------------------------------------


class TestUpdateWorkItems:
    def test_flat_list(self, wit_client):
        def mock_update(**kwargs):
            return _make_work_item(kwargs["id"], f"Item-{kwargs['id']}")

        wit_client.update_work_item.side_effect = mock_update

        items = [
            {"id": 10, "fields": {"System.State": "Active"}},
            {"id": 11, "fields": {"System.State": "Resolved"}},
        ]
        results = _update_recursive(wit_client, items)

        assert len(results) == 2
        assert results[0] == {"id": 10, "title": "Item-10"}
        assert results[1] == {"id": 11, "title": "Item-11"}

    def test_nested_tree(self, wit_client):
        def mock_update(**kwargs):
            return _make_work_item(kwargs["id"], f"Item-{kwargs['id']}")

        wit_client.update_work_item.side_effect = mock_update

        items = [
            {
                "id": 100,
                "fields": {"System.State": "Resolved"},
                "children": [
                    {
                        "id": 101,
                        "fields": {"System.State": "Active"},
                        "children": [
                            {"id": 102, "fields": {"System.AssignedTo": "dev@org.com"}},
                        ],
                    }
                ],
            }
        ]
        results = _update_recursive(wit_client, items)

        assert results[0]["id"] == 100
        assert results[0]["children"][0]["id"] == 101
        assert results[0]["children"][0]["children"][0]["id"] == 102
        assert wit_client.update_work_item.call_count == 3

    def test_output_structure_mirrors_input(self, wit_client):
        def mock_update(**kwargs):
            return _make_work_item(kwargs["id"], f"Title-{kwargs['id']}")

        wit_client.update_work_item.side_effect = mock_update

        items = [
            {
                "id": 1,
                "fields": {"System.State": "Done"},
                "children": [
                    {"id": 2, "fields": {"System.State": "Done"}},
                    {"id": 3, "fields": {"System.State": "Done"}},
                ],
            }
        ]
        results = _update_recursive(wit_client, items)

        assert results[0]["title"] == "Title-1"
        assert len(results[0]["children"]) == 2
        assert results[0]["children"][0]["title"] == "Title-2"
        assert results[0]["children"][1]["title"] == "Title-3"


# ---------------------------------------------------------------------------
# MCP tool wrapper tests (via direct function call)
# ---------------------------------------------------------------------------


class TestMCPToolWrappers:
    def test_create_work_item_tool_returns_json(self, wit_client):
        wit_client.create_work_item.return_value = _make_work_item(55, "Tool Bug")

        with patch("server.get_clients", return_value=(wit_client, None)):
            from server import create_work_item

            raw = create_work_item(
                work_item_type="Bug",
                fields={"System.Title": "Tool Bug"},
            )

        result = json.loads(raw)
        assert result == {"id": 55, "title": "Tool Bug"}

    def test_create_work_items_tool_returns_json(self, wit_client):
        id_counter = [0]

        def mock_create(**kwargs):
            id_counter[0] += 1
            title = next(
                o.value for o in kwargs["document"] if o.path == "/fields/System.Title"
            )
            return _make_work_item(id_counter[0], title)

        wit_client.create_work_item.side_effect = mock_create

        with patch("server.get_clients", return_value=(wit_client, None)):
            from server import create_work_items

            raw = create_work_items(
                items=[
                    {"type": "Bug", "fields": {"System.Title": "B1"}},
                    {"type": "Task", "fields": {"System.Title": "T1"}},
                ],
            )

        result = json.loads(raw)
        assert len(result) == 2
        assert result[0]["title"] == "B1"
        assert result[1]["title"] == "T1"

    def test_update_work_item_tool_returns_json(self, wit_client):
        wit_client.update_work_item.return_value = _make_work_item(66, "Updated")

        with patch("server.get_clients", return_value=(wit_client, None)):
            from server import update_work_item

            raw = update_work_item(
                work_item_id=66,
                fields={"System.State": "Active"},
            )

        result = json.loads(raw)
        assert result == {"id": 66, "title": "Updated"}

    def test_update_work_items_tool_returns_json(self, wit_client):
        def mock_update(**kwargs):
            return _make_work_item(kwargs["id"], f"U-{kwargs['id']}")

        wit_client.update_work_item.side_effect = mock_update

        with patch("server.get_clients", return_value=(wit_client, None)):
            from server import update_work_items

            raw = update_work_items(
                items=[
                    {"id": 10, "fields": {"System.State": "Active"}},
                ],
            )

        result = json.loads(raw)
        assert len(result) == 1
        assert result[0] == {"id": 10, "title": "U-10"}
