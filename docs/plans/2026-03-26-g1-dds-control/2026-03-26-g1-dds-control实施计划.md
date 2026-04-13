# G1 DDS High-Level Control Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current G1 real-robot WebRTC control path with a pure DDS / `unitree_sdk2_python` high-level control backend that can execute basic locomotion and existing G1 command payloads on real hardware.

**Architecture:** Keep `G1Connection` as the stable RPC-facing module, but add a new DDS-backed connection implementation and a small backend factory inside `G1Connection` so backend selection happens without import-time WebRTC or DDS dependency failures. The DDS backend will lazy-load `unitree_sdk2py`, initialize the Unitree SDK channel factory, wrap `LocoClient` high-level controls, and expose the existing `move` / `publish_request` RPC surface with fail-fast validation and a normalized return contract.

**Tech Stack:** Python 3.12, DimOS modules/RPC, Unitree `unitree_sdk2_python`, CycloneDDS, pytest, ruff

---

## Scope and non-goals

### In scope
- Real G1 high-level locomotion control via DDS
- Explicit backend selection between `webrtc` and `dds`
- Minimal G1 command support required by current call sites:
  - `move`
  - mode commands routed through `publish_request("rt/api/sport/request", ...)`
  - arm commands routed through `publish_request("rt/api/arm/request", ...)`
- Clear runtime errors when DDS dependencies are missing or SDK return codes indicate failure
- Focused unit tests for backend selection, delegation, and DDS command mapping
- DDS-first documentation for G1 real-hardware setup

### Out of scope for this plan
- Video, lidar, odometry, or lowstate DDS ingestion
- Low-level motor control (`LowCmd`)
- Reworking navigation/perception blueprints
- Changing the user-facing G1 skill API beyond what is strictly necessary for backend compatibility
- Making `default.env` a runtime config source; runtime config stays `.env` plus exported environment variables

## File structure and responsibilities

### Files to create
- `dimos/robot/unitree/g1/dds_connection.py`
  - DDS-backed high-level G1 connection wrapper
  - owns SDK loading boundary, DDS initialization, `LocoClient` setup, command mapping, and fail-fast validation
- `test/dimos/robot/unitree/g1/dds_connection/test_dds_connection.py`
  - unit tests for DDS backend SDK loading, command mapping, normalized return values, and unsupported-command failures
- `test/dimos/robot/unitree/g1/connection/test_g1_connection_dds.py`
  - unit tests for config-driven backend selection and `G1Connection` delegation without requiring real transports

### Files to modify
- `dimos/core/global_config.py`
  - add explicit config for Unitree backend and DDS network interface
- `dimos/robot/unitree/g1/connection.py`
  - add backend factory, move WebRTC imports behind runtime branches, and remove runtime type references that force WebRTC import during module import
- `docs/platforms/humanoid/g1/index.md`
  - document DDS prerequisites and DDS-first launch flow for real hardware
- `docs/usage/cli.md`
  - align `.env` and environment-variable examples with the keys actually consumed by `GlobalConfig`

### Files to leave unchanged unless implementation proves otherwise
- `dimos/robot/unitree/g1/skill_container.py`
  - preserve the existing RPC payload shape and keep compatibility inside the DDS backend rather than changing the skill layer

## Test execution constraint

New tests live under `test/` to follow the user’s project rules. Because `/home/humanoid/.config/superpowers/worktrees/dimos/dds/pyproject.toml` currently defaults pytest discovery to `dimos/`, these new tests must be run by explicit path in this plan. Do not assume plain `pytest` will discover them automatically.

## Normalized DDS backend return contract

To keep `G1ConnectionBase.publish_request()` stable while using SDK methods that return integer status codes, the DDS backend will follow this contract:

- SDK success (`code == 0`) returns a normalized dict, for example:

```python
{"status": "ok", "code": 0, "topic": topic, "api_id": api_id}
```

- SDK non-zero return codes raise `RuntimeError` with the topic, api id, and return code included in the message
- malformed payloads raise `ValueError`
- unsupported topics raise `NotImplementedError`

This keeps success handling structured while still failing fast on bad or unsupported commands.

## Chunk 1: DDS backend implementation

### Task 1: Create a testable SDK loading boundary and DDS backend skeleton

**Files:**
- Create: `dimos/robot/unitree/g1/dds_connection.py`
- Test: `test/dimos/robot/unitree/g1/dds_connection/test_dds_connection.py`

- [ ] **Step 1: Write the failing backend tests**

Cover these behaviors with mocks only; do not require a real robot, CycloneDDS daemon, or installed `unitree_sdk2py` package:
- constructor stores the interface name and defers SDK imports until `start()`
- missing SDK imports raise an actionable `RuntimeError`
- `start()` loads SDK symbols through a helper boundary instead of direct module-level imports

Example skeleton:

```python
import pytest

from dimos.robot.unitree.g1.dds_connection import UnitreeG1DDSConnection


def test_start_uses_sdk_loader(mocker) -> None:
    sdk = mocker.Mock()
    sdk.ChannelFactoryInitialize = mocker.Mock()
    sdk.LocoClient = mocker.Mock()
    mocker.patch(
        "dimos.robot.unitree.g1.dds_connection._load_unitree_sdk",
        return_value=sdk,
    )

    conn = UnitreeG1DDSConnection(interface="enp2s0")
    conn.start()

    sdk.ChannelFactoryInitialize.assert_called_once_with(0, "enp2s0")
    sdk.LocoClient.assert_called_once_with()


def test_start_raises_actionable_error_when_sdk_missing(mocker) -> None:
    mocker.patch(
        "dimos.robot.unitree.g1.dds_connection._load_unitree_sdk",
        side_effect=ImportError("unitree_sdk2py missing"),
    )

    conn = UnitreeG1DDSConnection(interface="enp2s0")

    with pytest.raises(RuntimeError, match="unitree_sdk2_python"):
        conn.start()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
pytest test/dimos/robot/unitree/g1/dds_connection/test_dds_connection.py -v
```

Expected: FAIL because the backend module and SDK loader helper do not exist yet.

- [ ] **Step 3: Write the minimal backend skeleton**

Implement in `dimos/robot/unitree/g1/dds_connection.py`:

```python
from typing import Any


def _load_unitree_sdk() -> Any:
    ...


class UnitreeG1DDSConnection:
    def __init__(self, interface: str | None = None) -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def move(self, twist: Twist, duration: float = 0.0) -> None: ...
    def publish_request(self, topic: str, data: dict[str, Any]) -> dict[str, Any]: ...
```

Implementation requirements:
- `_load_unitree_sdk()` is the only place that imports `unitree_sdk2py`
- `start()` calls `_load_unitree_sdk()` and translates `ImportError` into an actionable `RuntimeError`
- `start()` initializes `ChannelFactoryInitialize(0, interface)` and `LocoClient` exactly once per instance
- `stop()` is minimal and idempotent; do not invent SDK shutdown APIs that are not present

- [ ] **Step 4: Run the tests again**

Run:
```bash
pytest test/dimos/robot/unitree/g1/dds_connection/test_dds_connection.py -v
```

Expected: PASS for SDK-loading and startup tests.

- [ ] **Step 5: Commit**

```bash
git add dimos/robot/unitree/g1/dds_connection.py test/dimos/robot/unitree/g1/dds_connection/test_dds_connection.py
git commit -m "feat: add g1 dds backend skeleton"
```

### Task 2: Implement DDS command mapping and normalized `publish_request()` behavior

**Files:**
- Modify: `dimos/robot/unitree/g1/dds_connection.py`
- Test: `test/dimos/robot/unitree/g1/dds_connection/test_dds_connection.py`

- [ ] **Step 1: Extend the failing tests for command mapping**

Add tests that verify:
- `move(Twist(...), duration=0.0)` maps to `LocoClient.Move(vx, vy, vyaw, continous_move=True)`
- `move(..., duration > 0.0)` maps to `LocoClient.SetVelocity(vx, vy, vyaw, duration)`
- `publish_request("rt/api/sport/request", {"api_id": 7101, "parameter": {"data": 500}})` dispatches to the locomotion mode command path
- `publish_request("rt/api/arm/request", {"api_id": 7106, "parameter": {"data": 27}})` dispatches to the arm-task path
- SDK success returns a normalized dict
- SDK non-zero codes raise `RuntimeError`
- malformed payloads raise `ValueError`
- unsupported topics raise `NotImplementedError`

Example skeleton:

```python
from dimos.msgs.geometry_msgs import Twist, Vector3


def test_move_continuous_maps_to_loco_move(mocker) -> None:
    sdk = mocker.Mock()
    sdk.ChannelFactoryInitialize = mocker.Mock()
    sdk.LocoClient = mocker.Mock()
    loco = sdk.LocoClient.return_value
    mocker.patch("dimos.robot.unitree.g1.dds_connection._load_unitree_sdk", return_value=sdk)

    conn = UnitreeG1DDSConnection(interface="enp2s0")
    conn.start()
    conn.move(
        Twist(linear=Vector3(0.4, 0.1, 0.0), angular=Vector3(0.0, 0.0, 0.2)),
        duration=0.0,
    )

    loco.Move.assert_called_once_with(0.4, 0.1, 0.2, continous_move=True)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
pytest test/dimos/robot/unitree/g1/dds_connection/test_dds_connection.py -v
```

Expected: FAIL because the backend still lacks command mapping and normalized return handling.

- [ ] **Step 3: Implement the minimal command mapping**

Implementation requirements:
- `duration <= 0.0` => `LocoClient.Move(vx, vy, vyaw, continous_move=True)`
- `duration > 0.0` => `LocoClient.SetVelocity(vx, vy, vyaw, duration)`
- preserve the current skill payload shape inside `publish_request()` instead of changing `dimos/robot/unitree/g1/skill_container.py`
- support these topic/api combinations only:
  - `rt/api/sport/request` with `api_id == 7101`
  - `rt/api/arm/request` with `api_id == 7106`
- convert SDK return codes into the normalized dict contract described above
- raise clear exceptions for everything else

- [ ] **Step 4: Run the tests again**

Run:
```bash
pytest test/dimos/robot/unitree/g1/dds_connection/test_dds_connection.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dimos/robot/unitree/g1/dds_connection.py test/dimos/robot/unitree/g1/dds_connection/test_dds_connection.py
git commit -m "feat: map g1 dds commands to unitree sdk"
```

## Chunk 2: Config and `G1Connection` integration

### Task 3: Add explicit backend and DDS interface config

**Files:**
- Modify: `dimos/core/global_config.py`
- Test: `test/dimos/robot/unitree/g1/connection/test_g1_connection_dds.py`

- [ ] **Step 1: Write the failing config tests**

```python
from dimos.core.global_config import GlobalConfig


def test_unitree_connection_type_uses_explicit_backend() -> None:
    cfg = GlobalConfig(unitree_backend="dds")
    assert cfg.unitree_connection_type == "dds"


def test_unitree_connection_type_keeps_simulation_priority() -> None:
    cfg = GlobalConfig(unitree_backend="dds", simulation=True)
    assert cfg.unitree_connection_type == "mujoco"


def test_unitree_dds_interface_is_configurable() -> None:
    cfg = GlobalConfig(unitree_dds_interface="enp2s0")
    assert cfg.unitree_dds_interface == "enp2s0"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
pytest test/dimos/robot/unitree/g1/connection/test_g1_connection_dds.py -v
```

Expected: FAIL because `GlobalConfig` does not yet accept the DDS-specific fields.

- [ ] **Step 3: Implement the minimal config changes**

In `dimos/core/global_config.py`:
- add `unitree_backend: str | None = None`
- add `unitree_dds_interface: str | None = None`
- update `unitree_connection_type` to return:
  1. `"replay"` when `replay=True`
  2. `"mujoco"` when `simulation=True`
  3. explicit `unitree_backend` when set
  4. otherwise `"webrtc"`

Do not expand scope into unrelated config cleanup.

- [ ] **Step 4: Run the tests again**

Run:
```bash
pytest test/dimos/robot/unitree/g1/connection/test_g1_connection_dds.py -v
```

Expected: PASS for config tests.

- [ ] **Step 5: Commit**

```bash
git add dimos/core/global_config.py test/dimos/robot/unitree/g1/connection/test_g1_connection_dds.py
git commit -m "feat: add g1 dds backend config"
```

### Task 4: Route `G1Connection` through a backend factory with lazy imports

**Files:**
- Modify: `dimos/robot/unitree/g1/connection.py`
- Test: `test/dimos/robot/unitree/g1/connection/test_g1_connection_dds.py`

- [ ] **Step 1: Extend the failing tests to cover backend factory and delegation**

Design tests around patching `_create_backend(...)`, not around patching module-level backend classes. Add tests that verify:
- `_create_backend("dds", ...)` returns a DDS backend instance
- `_create_backend("webrtc", ...)` returns a WebRTC backend instance
- `G1Connection.move()` delegates to the chosen backend
- `G1Connection.publish_request()` delegates to the chosen backend

To avoid `cmd_vel.subscribe(...)` interfering with the test, patch `_create_backend` plus `cmd_vel.subscribe`, or test the helper and delegation methods separately.

Example skeleton:

```python
def test_g1_connection_start_uses_factory(mocker) -> None:
    fake_backend = mocker.Mock()
    factory = mocker.patch(
        "dimos.robot.unitree.g1.connection._create_backend",
        return_value=fake_backend,
    )

    conn = G1Connection(ip="192.168.0.10", connection_type="dds")
    conn.cmd_vel = mocker.Mock()
    conn.cmd_vel.subscribe.return_value = lambda: None

    conn.start()

    factory.assert_called_once_with("dds", "192.168.0.10", None)
    fake_backend.start.assert_called_once_with()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
pytest test/dimos/robot/unitree/g1/connection/test_g1_connection_dds.py -v
```

Expected: FAIL because the helper/factory and DDS branch do not exist yet.

- [ ] **Step 3: Implement the minimal backend factory**

In `dimos/robot/unitree/g1/connection.py`:
- remove the module-level import of `UnitreeWebRTCConnection`
- remove or generalize runtime type references that force WebRTC imports during module import
- add a local helper such as:

```python
def _create_backend(connection_type: str, ip: str | None, dds_interface: str | None):
    ...
```

Implementation requirements:
- import `UnitreeWebRTCConnection` only inside the `"webrtc"` branch
- import `UnitreeG1DDSConnection` only inside the `"dds"` branch
- keep fail-fast behavior for unknown backends
- in `G1Connection.start()`, call `_create_backend(...)` before starting the backend
- pass `self._global_config.unitree_dds_interface` into the DDS backend

- [ ] **Step 4: Run the tests again**

Run:
```bash
pytest test/dimos/robot/unitree/g1/connection/test_g1_connection_dds.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dimos/robot/unitree/g1/connection.py test/dimos/robot/unitree/g1/connection/test_g1_connection_dds.py
git commit -m "feat: route g1 connection through lazy backend factory"
```

## Chunk 3: Documentation and verification

### Task 5: Document the DDS-first G1 setup

**Files:**
- Modify: `docs/platforms/humanoid/g1/index.md`
- Modify: `docs/usage/cli.md`
- Test: none

- [ ] **Step 1: Draft the documentation changes**

Update `docs/platforms/humanoid/g1/index.md` so the real-hardware path no longer reads as WebRTC-only. Document:
- DDS is the supported path for environments where WebRTC cannot connect
- runtime prerequisites for the vendored SDK:
  - CycloneDDS installed
  - if editable install requires it, set `CYCLONEDDS_HOME` (or `CMAKE_PREFIX_PATH`) before installing the SDK
  - install the vendored SDK into the active environment:

```bash
conda activate agentic_subtask
pip install -e '.[dev,dds]'
export CYCLONEDDS_HOME=<path-to-cyclonedds-install>
pip install -e unitreesdk/unitree_sdk2_python
```

- actual config keys used by `GlobalConfig` and `.env`/environment variables:

```bash
export UNITREE_BACKEND=dds
export UNITREE_DDS_INTERFACE=<YOUR_NIC>
export ROBOT_IP=<YOUR_G1_IP>  # only document this if the final implementation still uses it
```

Update `docs/usage/cli.md` so the environment-variable guidance matches the keys actually consumed by `GlobalConfig`. Do not leave behind contradictory statements that all variables must use a `DIMOS_` prefix if the implementation does not use one.

- [ ] **Step 2: Apply the documentation changes**

In `docs/platforms/humanoid/g1/index.md`:
- revise the existing “Run on Your G1” and “What’s Running” sections so they no longer claim real-hardware G1 is WebRTC-only
- add a concise DDS setup section

In `docs/usage/cli.md`:
- update the `.env` example near the file-location table so it matches the implemented keys, for example `ROBOT_IP=...`, `UNITREE_BACKEND=dds`, `UNITREE_DDS_INTERFACE=...`
- remove or rewrite any broader guidance that contradicts the implemented environment-variable naming rules

- [ ] **Step 3: Verify documentation consistency**

Check that:
- every documented env var maps to a real `GlobalConfig` field
- the DDS install steps mention the vendored SDK path that actually exists in this repo: `unitreesdk/unitree_sdk2_python`
- no G1 real-hardware section still claims DDS users must rely on WebRTC

- [ ] **Step 4: Commit**

```bash
git add docs/platforms/humanoid/g1/index.md docs/usage/cli.md
git commit -m "docs: document g1 dds setup"
```

### Task 6: Run focused verification before handoff

**Files:**
- Modify: none
- Test: `test/dimos/robot/unitree/g1/dds_connection/test_dds_connection.py`
- Test: `test/dimos/robot/unitree/g1/connection/test_g1_connection_dds.py`

- [ ] **Step 1: Run focused unit tests**

Run:
```bash
pytest test/dimos/robot/unitree/g1/dds_connection/test_dds_connection.py test/dimos/robot/unitree/g1/connection/test_g1_connection_dds.py -v
```

Expected: PASS.

- [ ] **Step 2: Run a lightweight regression slice**

Run:
```bash
pytest dimos/core/test_blueprints.py -v
```

Expected: PASS.

- [ ] **Step 3: Run a static check on touched Python files**

Run:
```bash
ruff check dimos/core/global_config.py dimos/robot/unitree/g1/connection.py dimos/robot/unitree/g1/dds_connection.py test/dimos/robot/unitree/g1/dds_connection/test_dds_connection.py test/dimos/robot/unitree/g1/connection/test_g1_connection_dds.py
```

Expected: PASS.

- [ ] **Step 4: Run an exact manual DDS smoke test in the conda env**

In the configured environment:

```bash
conda activate agentic_subtask
pip install -e '.[dev,dds]'
export CYCLONEDDS_HOME=<path-to-cyclonedds-install>
pip install -e unitreesdk/unitree_sdk2_python
export UNITREE_BACKEND=dds
export UNITREE_DDS_INTERFACE=<YOUR_NIC>
python - <<'PY'
from dimos.msgs.geometry_msgs import Twist, Vector3
from dimos.robot.unitree.g1.dds_connection import UnitreeG1DDSConnection

conn = UnitreeG1DDSConnection(interface="<YOUR_NIC>")
conn.start()
conn.publish_request("rt/api/sport/request", {"api_id": 7101, "parameter": {"data": 500}})
conn.move(Twist(linear=Vector3(0.1, 0.0, 0.0), angular=Vector3(0.0, 0.0, 0.0)), duration=0.5)
PY
```

Expected: the backend starts without attempting WebRTC imports at runtime, the DDS command path returns success, and the robot accepts a short forward motion command.

- [ ] **Step 5: Commit**

```bash
git add dimos/core/global_config.py dimos/robot/unitree/g1/connection.py dimos/robot/unitree/g1/dds_connection.py docs/platforms/humanoid/g1/index.md docs/usage/cli.md test/dimos/robot/unitree/g1/dds_connection/test_dds_connection.py test/dimos/robot/unitree/g1/connection/test_g1_connection_dds.py
git commit -m "test: verify g1 dds backend integration"
```

## Implementation notes for the engineer

- Fail fast everywhere. Do not silently fall back from DDS to WebRTC.
- Keep `unitree_sdk2py` imports fully localized to `dimos/robot/unitree/g1/dds_connection.py`.
- Move the `UnitreeWebRTCConnection` import behind a runtime branch in `dimos/robot/unitree/g1/connection.py`.
- Remove or generalize runtime type references in `dimos/robot/unitree/g1/connection.py` that would force WebRTC imports during module import.
- Do not modify `dimos/robot/unitree/g1/skill_container.py` unless DDS compatibility cannot be achieved inside `publish_request()`.
- Keep the first backend focused on high-level control only. Do not add video or sensor placeholders in this task.
- Tests live under `test/` to follow user project rules; run them by explicit path rather than relying on default pytest discovery.
