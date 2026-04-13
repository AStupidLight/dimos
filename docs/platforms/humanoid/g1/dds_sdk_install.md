# Unitree G1 DDS SDK 安装记录

这份文档记录了在当前仓库环境中，把 `unitree_sdk2_python` 安装到 **当前 worktree 的 `.venv`** 里的实际过程、踩坑和最终可复现步骤。

适用目录：
- 仓库 worktree： `/home/humanoid/.config/superpowers/worktrees/dimos/dds`
- Python 环境： `/home/humanoid/.config/superpowers/worktrees/dimos/dds/.venv`

## 目标

在不依赖 WebRTC 的前提下，为 G1 真机 DDS 控制链准备运行环境，使当前 worktree 的 Python 环境可以成功导入：

- `unitree_sdk2py`
- `cyclonedds`

## 最终结论

直接执行下面命令通常**不会成功**：

```bash
python3 -m pip install -e unitreesdk/unitree_sdk2_python
```

常见报错：

```text
Could not locate cyclonedds. Try to set CYCLONEDDS_HOME or CMAKE_PREFIX_PATH
```

在这台机器上，最终可行的办法是：

1. 先按官方 FAQ 编译并安装 `CycloneDDS 0.10.x`
2. 编译时显式关闭 SHM：`-DENABLE_SHM=OFF`
3. 设置 `CYCLONEDDS_HOME`
4. 再把 `unitree_sdk2_python` 安装到当前 worktree 的 `.venv`

## 遇到的问题

### 问题 1：系统包不够

虽然可以通过 apt 安装：

- `cyclonedds-dev`
- `cyclonedds-tools`

但仅依赖系统包并不能让 `unitree_sdk2_python` 的 Python 依赖链正常工作。

原因是：
- Ubuntu 系统包提供的是较旧的 CycloneDDS 开发库
- `unitree_sdk2_python` 依赖的 Python 包是 `cyclonedds==0.10.2`
- 仅使用系统包路径，`pip/uv` 在构建 `cyclonedds==0.10.2` 时仍然可能找不到兼容的安装布局

### 问题 2：官方源码默认构建会卡在 iceoryx / SHM

按官方 FAQ 编译 `CycloneDDS 0.10.x` 时，默认构建在这台机器上卡在：

```text
fatal error: iceoryx_binding_c/config.h: No such file or directory
```

根因是：
- `ENABLE_SHM` 自动被打开
- 编译过程走到了 `iceoryx` 相关头文件路径
- 当前机器的这套依赖布局不满足该构建要求

解决方法是：
- 在编译 CycloneDDS 时显式关闭 SHM

## 当前机器上实际可复现的步骤

### 1. 安装系统构建依赖

```bash
sudo apt-get update
sudo apt-get install -y cmake cyclonedds-dev
```

> 说明：`git` 和 `make` 在当前机器上已经存在；如果你的机器没有，请一并安装。

### 2. 按官方目录编译 CycloneDDS 0.10.x

```bash
cd ~
git clone https://github.com/eclipse-cyclonedds/cyclonedds -b releases/0.10.x
rm -rf ~/cyclonedds/build ~/cyclonedds/install
cmake -S ~/cyclonedds -B ~/cyclonedds/build -DCMAKE_INSTALL_PREFIX=~/cyclonedds/install -DENABLE_SHM=OFF
cmake --build ~/cyclonedds/build --target install -j"$(nproc)"
```

### 3. 确认 CycloneDDS 安装完成

```bash
test -f ~/cyclonedds/install/lib/cmake/CycloneDDS/CycloneDDSConfig.cmake && echo OK
```

如果输出：

```bash
OK
```

说明本地 CycloneDDS 安装已就绪。

### 4. 把 SDK 安装到当前 worktree 的 `.venv`

当前 worktree：

```bash
cd /home/humanoid/.config/superpowers/worktrees/dimos/dds
```

使用当前 worktree 的 Python：

```bash
CYCLONEDDS_HOME="$HOME/cyclonedds/install" uv pip install -e "/home/humanoid/.config/superpowers/worktrees/dimos/dds/unitreesdk/unitree_sdk2_python" --python "/home/humanoid/.config/superpowers/worktrees/dimos/dds/.venv/bin/python3"
```

### 5. 验证安装结果

```bash
CYCLONEDDS_HOME="$HOME/cyclonedds/install" /home/humanoid/.config/superpowers/worktrees/dimos/dds/.venv/bin/python3 - <<'PY'
import unitree_sdk2py
import cyclonedds
print('unitree_sdk2py OK', getattr(unitree_sdk2py, '__file__', '<builtin>'))
print('cyclonedds OK', getattr(cyclonedds, '__file__', '<builtin>'))
PY
```

如果成功，输出会类似：

```text
unitree_sdk2py OK /home/humanoid/.config/superpowers/worktrees/dimos/dds/unitreesdk/unitree_sdk2_python/unitree_sdk2py/__init__.py
cyclonedds OK /home/humanoid/.config/superpowers/worktrees/dimos/dds/.venv/lib/python3.12/site-packages/cyclonedds/__init__.py
```

## 当前 worktree 的建议用法

后续在这个 worktree 中，只要要用到 DDS SDK，建议先带上：

```bash
export CYCLONEDDS_HOME="$HOME/cyclonedds/install"
```

如果你已经在当前仓库根目录下，并且想用当前 `.venv` 跑命令，可以直接用：

```bash
CYCLONEDDS_HOME="$HOME/cyclonedds/install" uv run --extra dev python - <<'PY'
import unitree_sdk2py
print('SDK ready')
PY
```

## 为什么这份记录重要

这次安装过程说明：

1. `unitree_sdk2_python` 的 README / FAQ 基本方向是对的
2. 但在 Ubuntu 22.04 这类环境里，直接依赖系统包路径不一定够
3. `CycloneDDS 0.10.x` 在当前机器上需要显式：
   - 从源码编译
   - 关闭 SHM：`-DENABLE_SHM=OFF`
4. 最终成功路径是：
   - `~/cyclonedds/install`
   - `CYCLONEDDS_HOME=~/cyclonedds/install`
   - 当前 worktree `.venv` 内安装 SDK

## 后续建议

如果后面要把这套 DDS 环境用于 G1 真机控制开发，建议统一使用：

- CycloneDDS 安装目录： `~/cyclonedds/install`
- worktree Python 环境： `/home/humanoid/.config/superpowers/worktrees/dimos/dds/.venv`
- SDK 源码目录： `/home/humanoid/.config/superpowers/worktrees/dimos/dds/unitreesdk/unitree_sdk2_python`

这样可以避免把依赖散落到多个 Python 环境里。
