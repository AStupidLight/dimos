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

import importlib
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from dimos.core.global_config import GlobalConfig


class _DisposableRecorder:
    def __init__(self) -> None:
        self.values: list[object] = []

    def add(self, value: object) -> None:
        self.values.append(value)


@pytest.fixture
def connection_module(monkeypatch: pytest.MonkeyPatch):
    fake_langchain_core = types.ModuleType("langchain_core")
    fake_langchain_tools = types.ModuleType("langchain_core.tools")
    fake_langchain_tools.tool = lambda func=None, *args, **kwargs: func
    fake_langchain_core.tools = fake_langchain_tools
    monkeypatch.setitem(sys.modules, "langchain_core", fake_langchain_core)
    monkeypatch.setitem(sys.modules, "langchain_core.tools", fake_langchain_tools)

    connection_module = importlib.import_module("dimos.robot.unitree.g1.connection")

    return connection_module


def test_unitree_connection_type_uses_explicit_backend() -> None:
    cfg = GlobalConfig(unitree_backend="dds")

    assert cfg.unitree_connection_type == "dds"


def test_unitree_connection_type_keeps_simulation_priority() -> None:
    cfg = GlobalConfig(unitree_backend="dds", simulation=True)

    assert cfg.unitree_connection_type == "mujoco"


def test_unitree_connection_type_keeps_replay_priority() -> None:
    cfg = GlobalConfig(unitree_backend="dds", replay=True, simulation=True)

    assert cfg.unitree_connection_type == "replay"


def test_unitree_dds_interface_is_configurable() -> None:
    cfg = GlobalConfig(unitree_dds_interface="enp2s0")

    assert cfg.unitree_dds_interface == "enp2s0"



def test_unitree_connection_type_defaults_to_webrtc() -> None:
    cfg = GlobalConfig()

    assert cfg.unitree_connection_type == "webrtc"



def test_create_backend_returns_dds_backend(
    monkeypatch: pytest.MonkeyPatch,
    connection_module,
) -> None:
    fake_backend = MagicMock()
    fake_cls = MagicMock(return_value=fake_backend)
    fake_module = SimpleNamespace(UnitreeG1DDSConnection=fake_cls)
    monkeypatch.setitem(sys.modules, "dimos.robot.unitree.g1.dds_connection", fake_module)

    backend = connection_module._create_backend("dds", "192.168.0.10", "enp2s0")

    fake_cls.assert_called_once_with(interface="enp2s0")
    assert backend is fake_backend


def test_create_backend_returns_webrtc_backend(
    monkeypatch: pytest.MonkeyPatch,
    connection_module,
) -> None:
    fake_backend = MagicMock()
    fake_cls = MagicMock(return_value=fake_backend)
    fake_module = SimpleNamespace(UnitreeWebRTCConnection=fake_cls)
    monkeypatch.setitem(sys.modules, "dimos.robot.unitree.connection", fake_module)

    backend = connection_module._create_backend("webrtc", "192.168.0.10", None)

    fake_cls.assert_called_once_with("192.168.0.10")
    assert backend is fake_backend



def test_connection_module_import_is_lazy_for_backend_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_langchain_core = types.ModuleType("langchain_core")
    fake_langchain_tools = types.ModuleType("langchain_core.tools")
    fake_langchain_tools.tool = lambda func=None, *args, **kwargs: func
    fake_langchain_core.tools = fake_langchain_tools
    monkeypatch.setitem(sys.modules, "langchain_core", fake_langchain_core)
    monkeypatch.setitem(sys.modules, "langchain_core.tools", fake_langchain_tools)

    monkeypatch.delitem(sys.modules, "dimos.robot.unitree.connection", raising=False)
    monkeypatch.delitem(sys.modules, "dimos.robot.unitree.g1.dds_connection", raising=False)
    monkeypatch.delitem(sys.modules, "dimos.robot.unitree.g1.connection", raising=False)

    connection_module = importlib.import_module("dimos.robot.unitree.g1.connection")

    assert connection_module is not None
    assert "dimos.robot.unitree.connection" not in sys.modules
    assert "dimos.robot.unitree.g1.dds_connection" not in sys.modules



def test_create_backend_requires_ip_for_webrtc(connection_module) -> None:
    with pytest.raises(ValueError, match="IP address must be provided"):
        connection_module._create_backend("webrtc", None, None)


def test_create_backend_fails_fast_for_unknown_backend(connection_module) -> None:
    with pytest.raises(ValueError, match="Unknown connection type: invalid"):
        connection_module._create_backend("invalid", "192.168.0.10", None)


def test_g1_connection_start_uses_factory_and_passes_dds_interface(
    monkeypatch: pytest.MonkeyPatch,
    connection_module,
) -> None:
    fake_backend = MagicMock()
    factory = MagicMock(return_value=fake_backend)
    monkeypatch.setattr(connection_module, "_create_backend", factory)

    cfg = GlobalConfig(unitree_dds_interface="enp2s0")
    connection = connection_module.G1Connection(ip="192.168.0.10", connection_type="dds", cfg=cfg)
    connection.cmd_vel = MagicMock()
    connection.cmd_vel.subscribe.return_value = lambda: None
    connection._disposables = _DisposableRecorder()

    connection.start()

    factory.assert_called_once_with("dds", "192.168.0.10", "enp2s0")
    fake_backend.start.assert_called_once_with()
    assert connection.connection is fake_backend
    connection.cmd_vel.subscribe.assert_called_once_with(connection.move)
    assert len(connection._disposables.values) == 1


def test_g1_connection_move_delegates_to_selected_backend(connection_module) -> None:
    connection = connection_module.G1Connection(
        ip="192.168.0.10", connection_type="dds", cfg=GlobalConfig()
    )
    backend = MagicMock()
    connection.connection = backend
    twist = MagicMock()

    connection.move(twist, duration=1.2)

    backend.move.assert_called_once_with(twist, 1.2)


def test_g1_connection_publish_request_delegates_to_selected_backend(connection_module) -> None:
    connection = connection_module.G1Connection(
        ip="192.168.0.10", connection_type="dds", cfg=GlobalConfig()
    )
    backend = MagicMock()
    backend.publish_request.return_value = {"status": "ok"}
    connection.connection = backend
    payload = {"api_id": 7101, "parameter": {"data": 500}}

    result = connection.publish_request("rt/api/sport/request", payload)

    backend.publish_request.assert_called_once_with("rt/api/sport/request", payload)
    assert result == {"status": "ok"}
