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

from importlib import import_module
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from dimos.core.resource import Resource

if TYPE_CHECKING:
    from dimos.msgs.geometry_msgs import Twist

DEFAULT_CLIENT_TIMEOUT_SECONDS = 10.0
SPORT_REQUEST_TOPIC = "rt/api/sport/request"
ARM_REQUEST_TOPIC = "rt/api/arm/request"
LOCOMOTION_MODE_API_ID = 7101
ARM_TASK_API_ID = 7106


def _load_unitree_sdk() -> Any:
    channel_module = import_module("unitree_sdk2py.core.channel")
    loco_module = import_module("unitree_sdk2py.g1.loco.g1_loco_client")
    return SimpleNamespace(
        ChannelFactoryInitialize=channel_module.ChannelFactoryInitialize,
        LocoClient=loco_module.LocoClient,
    )


class UnitreeG1DDSConnection(Resource):
    def __init__(self, interface: str | None = None) -> None:
        self.interface = interface
        self._client: Any | None = None
        self._started = False
        self._initialized = False

    def start(self) -> None:
        if self.interface is None or self.interface.strip() == "":
            raise RuntimeError(
                "DDS connection requires an interface; set UNITREE_DDS_INTERFACE before start()"
            )

        if self._initialized:
            self._started = True
            return

        try:
            sdk = _load_unitree_sdk()
        except ImportError as exc:
            raise RuntimeError(
                "unitree_sdk2_python is required to use UnitreeG1DDSConnection; "
                "install it with: pip install -e unitreesdk/unitree_sdk2_python"
            ) from exc

        sdk.ChannelFactoryInitialize(0, self.interface)
        client = sdk.LocoClient()
        client.SetTimeout(DEFAULT_CLIENT_TIMEOUT_SECONDS)
        client.Init()

        self._client = client
        self._initialized = True
        self._started = True

    def stop(self) -> None:
        self._started = False

    def move(self, twist: Twist, duration: float = 0.0) -> None:
        if not self._started or self._client is None:
            raise RuntimeError("DDS connection must be started before move()")

        vx = twist.linear.x
        vy = twist.linear.y
        vyaw = twist.angular.z

        if duration <= 0.0:
            self._client.Move(vx, vy, vyaw, continous_move=True)
            return

        code = self._client.SetVelocity(vx, vy, vyaw, duration)
        if code != 0:
            raise RuntimeError(f"DDS move failed: duration={duration}, code={code}")

    def publish_request(self, topic: str, data: dict[str, Any]) -> dict[str, Any]:
        if not self._started or self._client is None:
            raise RuntimeError("DDS connection must be started before publish_request()")

        api_id, parameter_data = self._parse_payload(data)

        if topic == SPORT_REQUEST_TOPIC and api_id == LOCOMOTION_MODE_API_ID:
            code = self._client.SetFsmId(parameter_data)
        elif topic == ARM_REQUEST_TOPIC and api_id == ARM_TASK_API_ID:
            code = self._client.SetTaskId(parameter_data)
        elif topic in {SPORT_REQUEST_TOPIC, ARM_REQUEST_TOPIC}:
            raise NotImplementedError(f"Unsupported DDS request: topic={topic}, api_id={api_id}")
        else:
            raise NotImplementedError(f"Unsupported DDS request topic: {topic}")

        if code != 0:
            raise RuntimeError(f"DDS request failed: topic={topic}, api_id={api_id}, code={code}")

        return {
            "status": "ok",
            "code": 0,
            "topic": topic,
            "api_id": api_id,
        }

    def _parse_payload(self, data: dict[str, Any]) -> tuple[int, Any]:
        if "api_id" not in data:
            raise ValueError("DDS payload must include 'api_id'")
        if "parameter" not in data:
            raise ValueError("DDS payload must include 'parameter'")

        parameter = data["parameter"]
        if not isinstance(parameter, dict):
            raise ValueError("DDS payload 'parameter' must be a dict")
        if "data" not in parameter:
            raise ValueError("DDS payload parameter must include 'data'")

        return data["api_id"], parameter["data"]
