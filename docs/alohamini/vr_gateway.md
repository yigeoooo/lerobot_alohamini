# AlohaMini VR Gateway 上线与操作记录

本文面向操作员和部署人员，记录 `vr_gateway` 的上线检查、VR 摇操流程、问题关闭模板和真实启动命令。

主运行环境：

- 树莓派上执行 `conda activate lerobot_alohamini`
- PC 通过 SSH 登录树莓派执行命令
- Quest 通过 USB 连树莓派，使用 ADB reverse 把 `localhost:8000` 桥接到树莓派上的服务
- 浏览器访问地址始终是 `http://localhost:8000/`

## Conda 依赖安装

VR 网关在 `lerobot_alohamini` 环境中运行，不以 `uv` 作为主流程。先激活环境，再安装 VR 相关依赖：

```bash
conda activate lerobot_alohamini
python -m pip install fastapi "uvicorn[standard]" websockets wsproto
python -m pip install "lerobot[placo-dep]"
```

如果仓库里的机器人依赖还未准备好，再补齐常见运行依赖：

```bash
python -m pip install numpy opencv-python-headless pillow requests
```

导入检查：

```bash
python - <<'PY'
import fastapi
import uvicorn
import websockets
import wsproto
import placo
print("VR imports ok")
PY
```

如果 `placo` 在树莓派上因为底层 `cmeel` 轮子缺库而失败，先不要改协议，先把缺的二进制依赖补齐，再重试导入检查。

真实启动命令：

```bash
conda activate lerobot_alohamini
adb reverse --remove-all
adb reverse tcp:8000 tcp:8000
python -m lerobot.vr_gateway.server --robot-model alohamini2pro --host 0.0.0.0 --port 8000
```

## 上线前检查表

### 代码与模型资产同步

PC 和树莓派都必须同步 `src/lerobot` 下的 `vr_gateway` 代码及其资源目录。使用
`alohamini2pro` 时，启动前确认以下文件在树莓派上存在：

```text
src/lerobot/vr_gateway/assets/alohamini2pro/urdf/alohamini2pro.urdf
```

该 URDF 是网关启动时固定加载的必需资产；只同步 Python 文件会导致启动失败。代码更新后请从同一版本同步整个
`src/lerobot/vr_gateway/` 目录（包括 `assets/`），再执行启动命令。

以下项目必须逐项确认。`[x]` 仅表示当前有代码/文档证据，`[ ]` 表示本次上线仍需验证。

- [ ] **conda 环境**。完成条件：树莓派激活 `lerobot_alohamini`，依赖可导入。验证方法：执行上面的 `python - <<'PY' ...` 导入检查。验证记录：____
- [ ] **ADB reverse**。完成条件：Quest 被 `adb devices` 识别，旧映射清除后 `tcp:8000 -> tcp:8000` 成功。验证方法：执行 `adb reverse --remove-all` 和 `adb reverse tcp:8000 tcp:8000`。验证记录：____
- [x] **health 入口**。完成条件：`/health` 可访问。验证方法：`curl http://127.0.0.1:8000/health`。验证记录：____
- [~] **完整 observation**。完成条件：左右全部关节、夹爪、升降和健康字段齐全且新鲜。验证方法：页面和日志核对。验证记录：2026-09-07，代码已加完整状态 gate，待树莓派实机核对 observation 字段。
- [x] **E-STOP 入口**。完成条件：软件和硬件 E-STOP 均可触发。验证方法：低速测试软件 E-STOP，再核对硬件优先级。验证记录：____
- [ ] **Torque 生命周期**。完成条件：`connect -> configure -> enable_torque` 明确且可重复。验证方法：记录连接、模式、扭矩寄存器和断线状态。验证记录：____
- [ ] **唯一客户端**。完成条件：同一时间只有一个控制客户端。验证方法：双浏览器并发和租约检查。验证记录：____
- [x] **底层 motor calibration 文件存在**。完成条件：`/home/pi5/.cache/huggingface/lerobot/calibration/robots/alohamini/AlohaMiniRobot.json` 存在，字段包含 `id/drive_mode/homing_offset/range_min/range_max`，并被 `AlohaMini.connect()/calibrate()` 使用。验证方法：只读核对文件和代码链路。验证记录：____
- [~] **VR 中位/重锚定**。完成条件：操作者摆好手柄后，通过显式确认捕获当前 controller pose 与当前 TCP/关节状态，作为本次会话的 `_ctrl0/_robot0`。验证方法：首帧不跳变，`Re-anchor / Align` 后继续跟随。验证记录：2026-09-07，按钮和协议已补，待 Quest+树莓派实机确认。

## 运行拓扑

- 所有机器人相关启动都在树莓派上执行。
- PC 只负责 SSH 登录树莓派，不直接替代运行环境。
- Quest 不直接连局域网地址，而是通过 USB + ADB reverse 访问 `localhost:8000`。
- 如果已有别的 host 进程占用串口，需要先停止，否则不要继续启动网关。

## 每次上线前操作顺序

1. SSH 到树莓派。
2. 激活 `conda` 环境。
3. 清理旧的 ADB reverse。
4. 重新建立 `tcp:8000 -> tcp:8000`。
5. 启动网关。
6. 检查 `/health`。
7. 在 Quest 浏览器打开 `http://localhost:8000/`。
8. 先确认画面、状态栏、手柄追踪和 observation。
9. 再进入 VR 摇操。

## Quest 摇操流程

### 1. 启动和连接

1. 清空机械臂和底盘周围。
2. 在树莓派上执行启动命令。
3. 确认 `curl http://127.0.0.1:8000/health` 返回正常。
4. 在 Quest 浏览器打开 `http://localhost:8000/`。
5. 先不握 grip，确认页面状态、相机画面和 observation 正常。

### 2. VR 中位/对齐

1. 操作者先摆好手柄姿势。
2. 在页面上点击 `Re-anchor / Align`。
3. 系统应锁存当前 controller pose 和当前机器人状态作为本次会话参考。
4. 首次动作应从当前机器人姿态开始，不应瞬移。

### 3. 手臂控制

1. 双手同时握住 grip/squeeze 后再开始移动。
2. 小范围慢动作优先。
3. 任一侧释放后应进入保持或 reset 状态。
4. 发现反向、跳变、抖动、过流或延迟时，立即释放并停机。

### 4. 底盘和升降

| 输入 | 当前行为 |
| --- | --- |
| 左手柄摇杆上下 | 前后速度 |
| 左手柄摇杆左右 | 平移速度 |
| 右手柄摇杆左右 | 旋转速度 |
| 右手柄 A | 升降下降 |
| 右手柄 B | 升降上升 |

### 5. 停止

1. 松开所有 grip 和按键。
2. 确认机器人停止。
3. 必要时使用软件 E-STOP。
4. 硬件 E-STOP 永远优先。

## 每次上线前问题关闭记录

当某个问题从未完成变成完成时，按下面格式补充：

```md
### 关闭记录：问题名

- 编号：
- 关闭日期：
- 硬件/环境：
- 修改文件：
- 验证命令：
- 验证结果：
- 日志/截图：
- 备注：
```

## 常见问题排障

| 现象 | 可能原因 | 处理 |
| --- | --- | --- |
| `adb devices` 看不到 Quest | USB 调试未开启、线缆只充电、设备未授权 | 打开开发者模式和 USB 调试，重新插线并确认授权。 |
| `adb reverse` 失败 | ADB 未连上、端口被占用、Quest 断链 | 先 `adb reverse --remove-all` 再重试。 |
| 页面能开但 VR 不进 | 不是 `localhost` 访问、WebXR 不支持、桥接失败 | 确认 Quest 访问的是 `http://localhost:8000/`。 |
| 手臂不动 | 扭矩未使能、calibration 不完整、状态未齐全 | 先核对 torque、health 和 observation。 |
| 升降一直动 | A/B 被锁存或断线未停车 | 立即松开按键并按硬件 E-STOP。 |

## 已知限制

- `AlohaMini.configure()` 当前会 disable torque，enable torque 需要继续核实。
- motor calibration 文件不是 VR midpoint 文件。
- `vr_gateway` 仍需要单客户端租约、lift 停车和更完整的 IK 观测。
- 只有一个控制客户端可写入控制状态。

## 当前推荐命令

```bash
conda activate lerobot_alohamini
adb reverse --remove-all
adb reverse tcp:8000 tcp:8000
python -m lerobot.vr_gateway.server --robot-model alohamini2pro --host 0.0.0.0 --port 8000
```

Quest 浏览器访问：

```text
http://localhost:8000/
```
