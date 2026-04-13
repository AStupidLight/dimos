# Copyright 2025-2026 Dimensional Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import ast
import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from dimos.msgs.geometry_msgs import Twist, Vector3
import dimos.robot.unitree.g1.dds_connection as dds_connection_module
from dimos.robot.unitree.g1.dds_connection import UnitreeG1DDSConnection


def _make_sdk_mock() -> tuple[SimpleNamespace, MagicMock, MagicMock, MagicMock]:
    channel_factory_initialize = MagicMock()
    loco_client = MagicMock()
    loco_client.SetVelocity.return_value = 0
    loco_client.SetFsmId.return_value = 0
    loco_client.SetTaskId.return_value = 0
    loco_client_cls = MagicMock(return_value=loco_client)
    sdk = SimpleNamespace(
        ChannelFactoryInitialize=channel_factory_initialize,
        LocoClient=loco_client_cls,
    )
    return sdk, channel_factory_initialize, loco_client_cls, loco_client


def _make_started_connection(
    monkeypatch: pytest.MonkeyPatch,
    interface: str = "eth0",
) -> tuple[UnitreeG1DDSConnection, MagicMock]:
    sdk, _, _, loco_client = _make_sdk_mock()
    loader = MagicMock(return_value=sdk)
    monkeypatch.setattr(dds_connection_module, "_load_unitree_sdk", loader)

    connection = UnitreeG1DDSConnection(interface=interface)
    connection.start()
    return connection, loco_client


def test_init_is_lazy(monkeypatch: pytest.MonkeyPatch) -> None:
    loader = MagicMock(side_effect=AssertionError("SDK should not load during __init__"))
    monkeypatch.setattr(dds_connection_module, "_load_unitree_sdk", loader)

    connection = UnitreeG1DDSConnection(interface="eth0")

    assert connection.interface == "eth0"
    assert loader.call_count == 0


def test_move_signature_is_explicit() -> None:
    signature = inspect.signature(UnitreeG1DDSConnection.move)

    assert list(signature.parameters) == ["self", "twist", "duration"]
    assert all(
        parameter.kind not in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
        for parameter in signature.parameters.values()
    )


def test_publish_request_signature_is_explicit() -> None:
    signature = inspect.signature(UnitreeG1DDSConnection.publish_request)

    assert list(signature.parameters) == ["self", "topic", "data"]
    assert all(
        parameter.kind not in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
        for parameter in signature.parameters.values()
    )


def test_start_wraps_missing_sdk_import(monkeypatch: pytest.MonkeyPatch) -> None:
    loader = MagicMock(side_effect=ImportError("No module named 'unitree_sdk2py'"))
    monkeypatch.setattr(dds_connection_module, "_load_unitree_sdk", loader)
    connection = UnitreeG1DDSConnection(interface="eth0")

    with pytest.raises(RuntimeError, match="unitree_sdk2_python") as exc_info:
        connection.start()

    assert isinstance(exc_info.value.__cause__, ImportError)
    assert "pip install -e unitreesdk/unitree_sdk2_python" in str(exc_info.value)
    assert loader.call_count == 1


def test_start_loads_sdk_and_initializes_client(monkeypatch: pytest.MonkeyPatch) -> None:
    sdk, channel_factory_initialize, loco_client_cls, loco_client = _make_sdk_mock()
    loader = MagicMock(return_value=sdk)
    monkeypatch.setattr(dds_connection_module, "_load_unitree_sdk", loader)
    connection = UnitreeG1DDSConnection(interface="eth0")

    connection.start()

    assert loader.call_count == 1
    channel_factory_initialize.assert_called_once_with(0, "eth0")
    loco_client_cls.assert_called_once_with()
    loco_client.SetTimeout.assert_called_once()
    loco_client.Init.assert_called_once_with()
    assert connection._client is loco_client


def test_start_initializes_only_once(monkeypatch: pytest.MonkeyPatch) -> None:
    sdk, channel_factory_initialize, loco_client_cls, loco_client = _make_sdk_mock()
    loader = MagicMock(return_value=sdk)
    monkeypatch.setattr(dds_connection_module, "_load_unitree_sdk", loader)
    connection = UnitreeG1DDSConnection(interface="eth0")

    connection.start()
    connection.start()

    assert loader.call_count == 1
    channel_factory_initialize.assert_called_once_with(0, "eth0")
    loco_client_cls.assert_called_once_with()
    loco_client.SetTimeout.assert_called_once()
    loco_client.Init.assert_called_once_with()


def test_stop_is_minimal_and_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    sdk, _, _, _ = _make_sdk_mock()
    loader = MagicMock(return_value=sdk)
    monkeypatch.setattr(dds_connection_module, "_load_unitree_sdk", loader)

    never_started_connection = UnitreeG1DDSConnection()
    never_started_connection.stop()
    never_started_connection.stop()
    assert never_started_connection._started is False
    assert never_started_connection._client is None
    assert loader.call_count == 0

    started_connection = UnitreeG1DDSConnection(interface="eth0")
    started_connection.start()
    started_connection.stop()
    started_connection.stop()
    assert started_connection._started is False
    assert started_connection._client is not None
    assert loader.call_count == 1


@pytest.mark.parametrize("interface", [None, "", "   "])
def test_start_requires_nonempty_interface(
    monkeypatch: pytest.MonkeyPatch,
    interface: str | None,
) -> None:
    sdk, _, _, _ = _make_sdk_mock()
    loader = MagicMock(return_value=sdk)
    monkeypatch.setattr(dds_connection_module, "_load_unitree_sdk", loader)
    connection = UnitreeG1DDSConnection(interface=interface)

    with pytest.raises(RuntimeError, match="interface"):
        connection.start()


def test_move_requires_started_connection() -> None:
    connection = UnitreeG1DDSConnection()
    twist = Twist(linear=Vector3(0.1, 0.0, 0.0), angular=Vector3(0.0, 0.0, 0.0))

    with pytest.raises(RuntimeError, match="start"):
        connection.move(twist)



def test_publish_request_requires_started_connection() -> None:
    connection = UnitreeG1DDSConnection()
    payload = {"api_id": 7101, "parameter": {"data": 500}}

    with pytest.raises(RuntimeError, match="start"):
        connection.publish_request("rt/api/sport/request", payload)



def test_move_rejects_commands_after_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    connection, _ = _make_started_connection(monkeypatch)
    connection.stop()
    twist = Twist(linear=Vector3(0.1, 0.0, 0.0), angular=Vector3(0.0, 0.0, 0.0))

    with pytest.raises(RuntimeError, match="start"):
        connection.move(twist)



def test_publish_request_rejects_commands_after_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    connection, _ = _make_started_connection(monkeypatch)
    connection.stop()
    payload = {"api_id": 7101, "parameter": {"data": 500}}

    with pytest.raises(RuntimeError, match="start"):
        connection.publish_request("rt/api/sport/request", payload)



def test_move_continuous_maps_to_loco_move(monkeypatch: pytest.MonkeyPatch) -> None:
    connection, loco_client = _make_started_connection(monkeypatch)
    twist = Twist(linear=Vector3(0.4, 0.1, 0.0), angular=Vector3(0.0, 0.0, 0.2))

    connection.move(twist, duration=0.0)

    loco_client.Move.assert_called_once_with(0.4, 0.1, 0.2, continous_move=True)
    loco_client.SetVelocity.assert_not_called()


def test_move_duration_maps_to_set_velocity(monkeypatch: pytest.MonkeyPatch) -> None:
    connection, loco_client = _make_started_connection(monkeypatch)
    loco_client.SetVelocity.return_value = 0
    twist = Twist(linear=Vector3(0.4, 0.1, 0.0), angular=Vector3(0.0, 0.0, 0.2))

    connection.move(twist, duration=1.5)

    loco_client.SetVelocity.assert_called_once_with(0.4, 0.1, 0.2, 1.5)
    loco_client.Move.assert_not_called()


def test_move_duration_raises_runtime_error_on_nonzero_sdk_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection, loco_client = _make_started_connection(monkeypatch)
    loco_client.SetVelocity.return_value = 9
    twist = Twist(linear=Vector3(0.4, 0.1, 0.0), angular=Vector3(0.0, 0.0, 0.2))

    with pytest.raises(RuntimeError, match="code=9"):
        connection.move(twist, duration=1.5)


def test_publish_request_routes_sport_mode_and_normalizes_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection, loco_client = _make_started_connection(monkeypatch)
    loco_client.SetFsmId.return_value = 0
    payload = {"api_id": 7101, "parameter": {"data": 500}}

    result = connection.publish_request("rt/api/sport/request", payload)

    loco_client.SetFsmId.assert_called_once_with(500)
    assert result == {
        "status": "ok",
        "code": 0,
        "topic": "rt/api/sport/request",
        "api_id": 7101,
    }


def test_publish_request_routes_arm_task_and_normalizes_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection, loco_client = _make_started_connection(monkeypatch)
    loco_client.SetTaskId.return_value = 0
    payload = {"api_id": 7106, "parameter": {"data": 27}}

    result = connection.publish_request("rt/api/arm/request", payload)

    loco_client.SetTaskId.assert_called_once_with(27)
    assert result == {
        "status": "ok",
        "code": 0,
        "topic": "rt/api/arm/request",
        "api_id": 7106,
    }


def test_publish_request_raises_runtime_error_on_nonzero_sdk_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection, loco_client = _make_started_connection(monkeypatch)
    loco_client.SetFsmId.return_value = 3
    payload = {"api_id": 7101, "parameter": {"data": 500}}

    with pytest.raises(RuntimeError) as exc_info:
        connection.publish_request("rt/api/sport/request", payload)

    error_message = str(exc_info.value)
    assert "rt/api/sport/request" in error_message
    assert "7101" in error_message
    assert "3" in error_message


@pytest.mark.parametrize(
    ("topic", "payload"),
    [
        ("rt/api/sport/request", {"parameter": {"data": 500}}),
        ("rt/api/sport/request", {"api_id": 7101, "parameter": {}}),
        ("rt/api/arm/request", {"api_id": 7106, "parameter": "bad"}),
    ],
)
def test_publish_request_rejects_malformed_payload(
    monkeypatch: pytest.MonkeyPatch,
    topic: str,
    payload: dict[str, object],
) -> None:
    connection, _ = _make_started_connection(monkeypatch)

    with pytest.raises(ValueError):
        connection.publish_request(topic, payload)


def test_publish_request_rejects_unsupported_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    connection, _ = _make_started_connection(monkeypatch)
    payload = {"api_id": 7101, "parameter": {"data": 500}}

    with pytest.raises(NotImplementedError, match="rt/api/unsupported"):
        connection.publish_request("rt/api/unsupported", payload)


def test_publish_request_rejects_unsupported_api_combination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection, _ = _make_started_connection(monkeypatch)
    payload = {"api_id": 7102, "parameter": {"data": 500}}

    with pytest.raises(NotImplementedError):
        connection.publish_request("rt/api/sport/request", payload)


def test_load_unitree_sdk_is_the_only_import_boundary() -> None:
    module_source = inspect.getsource(dds_connection_module)
    module_ast = ast.parse(module_source)

    helper_def = next(
        node
        for node in module_ast.body
        if isinstance(node, ast.FunctionDef) and node.name == "_load_unitree_sdk"
    )
    helper_lineno = helper_def.lineno
    helper_end_lineno = helper_def.end_lineno
    assert helper_end_lineno is not None

    import_nodes = [
        node
        for node in ast.walk(module_ast)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "import_module"
    ]
    assert len(import_nodes) == 2

    import_target_nodes = []
    for import_node in import_nodes:
        assert helper_lineno <= import_node.lineno <= helper_end_lineno
        assert len(import_node.args) == 1
        import_target = import_node.args[0]
        assert isinstance(import_target, ast.Constant)
        assert isinstance(import_target.value, str)
        assert import_target.value.startswith("unitree_sdk2py")
        import_target_nodes.append(import_target)

    unitree_sdk_string_nodes = [
        node
        for node in ast.walk(module_ast)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "unitree_sdk2py" in node.value
    ]
    assert len(unitree_sdk_string_nodes) == 2
    assert {id(node) for node in unitree_sdk_string_nodes} == {id(node) for node in import_target_nodes}
