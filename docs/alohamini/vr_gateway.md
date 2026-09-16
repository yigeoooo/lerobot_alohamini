# AlohaMini VR Gateway 上线与操作记录

本文面向操作员和部署人员，记录 `vr_gateway` 的上线检查、VR 摇操流程、问题关闭模板和真实启动命令。

2026-09-16 根据实机反馈，默认模式（`--arm-ik-mode legacy`）保留 `d569ef96` 的 CAD 模型、平移映射与前后补偿、0.5 位移倍率和 `Goal_Velocity=2000`。在此基础上修正左右转向，并将手柄长轴 twist 映射到夹爪滚转；用户已确认本次腕关节问题解决，本轮继续保留该实现。它仍经六轴 IK，并不是完全隔离的单关节通道，也不是该 Git 提交的完整原样回退。直接沿用机器已有的电机行程标定，无需重新做零点或 Folded Home 校准；从当前位置握住 Grip 建立锚点，不自动回 Home。

开始一轮操控时自动按当前头部朝向对齐：任一手或双手首次 Grip 都可触发；只要还有一侧正在控制，中途加入或重新握持的另一侧就沿用同一个方向基准，仅建立自身的位置/姿态锚点。两侧均松开后，下次握持重新对齐。跟随期间转头不改变映射，Y 仍可手动重新对齐。缺少有效头部追踪时不会开始自动对齐的跟随。

桌面和 VR 画面内会弹出“限位警告”，列出对应侧和关节。依据现有电机行程与模型范围，实测角度或已接受目标距边界不超过 0.5° 时提示；离开范围边缘后消失。速度限幅或单纯 IK 残差不会冒充关节限位。反馈过期时不继续显示旧限位状态。

旧版夹爪也无需 Home 映射：沿用现有电机的 RANGE_0_100 行程，两侧均为增大值打开、减小值闭合。夹爪默认闭合，按住 Trigger 打开，按得越深打开越大，松开闭合，无需同时按 Grip。进入 VR 后有有效手柄追踪和健康反馈时即发送当前扳机目标；追踪丢失、暂停、急停或反馈失效时停止发送。电机夹持电流保护继续生效。

VR 相机改为 1280×720 / 30 fps / MJPEG，推流保留 1280 像素宽、JPEG 质量 90、10 fps；不放大小尺寸来源。头显关闭固定注视点降采样并启用抗锯齿。树莓派实测单帧 JPEG 编码约 5.3 ms（中位数），当前实景样本含 base64 的 10 fps 数据量约 14.5 Mbps，具体随画面变化。编码保持在机器人控制锁外，CLI 的 `--max-frame-width` / `--jpeg-quality` 仍可覆盖。

更新后重启网关并退出 VR、刷新页面；诊断栏应显示 `页面 vr5`，相机状态应显示 `1280 × 720`。只同步磁盘文件不会更新已经打开的 Quest 页面。

vr5 修复高清画面进入 VR 后黑屏：改变 canvas 分辨率前释放旧 GPU 纹理，使 Three.js 按新尺寸分配存储。此前只设置 `needsUpdate`，Quest 报 `GL_INVALID_VALUE: glCopySubTextureCHROMIUM: destination texture bad dimensions`，桌面图片仍正常。保留 720p 和原画面方向。用户已确认修复后 VR 内可见诊断测试图；真实相机画面仍需在运行网关后核对。左右摆腕移除额外的 yaw 取反，恢复 d569ef96 的转向映射，保留已确认可用的长轴 twist。

原 Home 方案保留为显式选项 `--arm-ik-mode calibrated`，才需要[本机机械参考映射](vr_calibration.md)，并继续使用该模式的 1.0 倍率、`Goal_Velocity=100`、5° 驱动领先、25 mm / 15° TCP 领先限制。该映射仍待物理几何核验，不能把 Home 已采集当作方向已验收。不要把先前试验的 `--arm-goal-velocity 100` 或 `--position-scale 1` 混入旧版恢复命令。

2026-09-16 重构：页面采用 Telegrip 风格，左右 Grip 独立跟随、Trigger 独立控制夹爪。底盘、升降和 WASD 映射保持原样。网关启动时连接机器人一次；打开或刷新页面只连接 `/ws`，不会再次调用机器人 `connect()` 或升降初始化。只允许一个控制客户端。

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
python -m lerobot.vr_gateway.server --robot-model alohamini2pro --arm-ik-mode legacy --host 0.0.0.0 --port 8000
```

## 上线前检查表

### 代码与模型资产同步

PC 和树莓派都必须同步 `src/lerobot` 下的 `vr_gateway` 代码及其资源目录。使用
`alohamini2pro` 时，启动前确认以下文件在树莓派上存在：

```text
src/lerobot/vr_gateway/assets/alohamini2pro/urdf/alohamini2pro.urdf
```

这是默认旧版模式的必需资产；显式 calibrated 模式使用同目录的 `alohamini2pro_kinematic.urdf`。只同步 Python 文件会导致启动失败。代码更新后请从同一版本同步整个
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
2. 进入 VR，面向操作方向握住任一侧 Grip 时自动对齐；另一侧中途加入沿用同一方向，双手均松开后的下一次握持重新对齐。左手 Y（或“重新对齐”）仍可手动更新，跟随中转头不会改变映射。
3. 握住需要操作的一侧 Grip，系统锁存当前 controller pose 和最新实测 TCP 作为本次会话参考。“重建锚点”按钮保留已对齐方向，只更新当前起点。
4. 首次动作应从当前机器人姿态开始，不应瞬移。

### 3. 手臂控制

1. 按住对应手柄侧面的 Grip/squeeze 后再开始移动，两侧独立起停。
2. 小范围慢动作优先。
3. 松开 Grip 后该侧保持释放时实测位置，另一侧继续跟随；再次握持不追逐旧目标。
4. 发现反向、跳变、抖动、过流或延迟时，立即释放并停机。
5. 夹爪默认闭合，按住 Trigger 打开，松开闭合；不需要握 Grip。恢复有效追踪和健康反馈后使用当前扳机状态。legacy 使用现有 RANGE_0_100 行程，calibrated 使用本机映射中的开合端点。
6. 暂停跟随、急停、反馈过期、追踪丢失或断连后，松开再握 Grip 重新开始。设置弹窗可调整位移倍率（0.1–2）和关节速度上限（5–90°/s）；应用时先保持并重建锚点。

### 状态与模型约定

页面分开显示网关连接、左右串口连接、力矩寄存器读回、机械标定可用性、反馈年龄及每侧跟随/保持。无法读回力矩时显示“未知”，连接成功不等于力矩使能。前置相机保留桌面原方向和原始比例；本次移除 VR 平面原有的 180° 旋转，相当于将用户反馈的倒置画面再转 180°。“操作设置 → VR 画面方向”还可选择正常/旋转 180°，只在纹理绘制时处理一次。A-Frame 1.7.1 和手柄几何在本地部署，普通 immersive VR 为当前入口，未宣称支持已验收的透视模式。

原始 WebXR 位姿在后端统一转换：无额外朝向偏转时 `(x_base, y_base, z_base) = (-z_xr, -x_xr, y_xr)`。世界相对旋转为 `R_target = A (R_C R_C0ᵀ) Aᵀ R_E0`；因此手柄局部轴不再隐式等同于 TCP 局部轴。TCP 使用固定夹爪上的 `left_tcp/right_tcp`，升降高度仅用于 FK。

默认旧版模式保留 Placo、原位置/姿态权重、`posture_weight=5e-4` 和 90°/s 关节速度上限；恢复按实际周期计算运动预算，最多 0.2 s。恢复原 45° IK 实测偏差上限和网关 20° 单步保护，不再叠加新版默认的 5° 驱动领先与 TCP 领先限制。求解器同时使用机器已有电机行程范围，防止旧版在不可达位置下发越界角度；这些范围不需要额外 Home 标定。旧版某些位置不可达的问题仍保留，恢复模式不宣称扩大了工作空间。

显式 calibrated 模式继续使用标定模型和 TCP 领先限制；连续五帧残差较大才尝试一个附近初值，额外预算默认 6 ms（在 QP 迭代之间检查，单次 QP 不可抢占）。默认旧版模式不启用这项多初值策略。

默认反馈最大年龄 0.5 s、每侧姿态超时 0.3 s；生产设备需测量总线、相机和 QP 时延后验收。网关分别保留实测状态、操作者请求和驱动接受的目标。正常心跳保持驱动接受值，单侧释放才一次性切换到该侧实测保持值。

控制循环把 IK 与串口耗时计入 40 ms 周期，只等待剩余时间；若本轮已经超时，下一轮直接处理最新输入，不积压补发。诊断栏显示实际控制 Hz。电机寄存器参数 2000 和配置 25 Hz 都不代表实机必然达到相应速度；靠近电机行程边界时仍可能无法继续某些动作。

离线验收见 `tests/vr_gateway/test_legacy_ik.py`、`test_wrist_controls.py`、`test_server.py`、`test_calibrated_ik.py` 和 `test_frontend.cjs`。运行前端回放：`node tests/vr_gateway/test_frontend.cjs`。12 组 d569ef96 原始输出对照（含 3 组旋转）均通过，并覆盖独立拧腕、左右转向、越过 180°、行程上限及重新握持。离线一致不代表实机跟随已验收；仍需检查实际方向、响应、再握持和不可达位置。当前模型没有完整碰撞检测。

画面像素回归：`uv run python tests/vr_gateway/check_video_render.py`，需要本机 Chrome/Chromium 和 websockets。仅加载实际静态 UI，检查完整 A-Frame 场景在 640×480、1280×720、480×360 之间切换及 0°/180° 旋转的四角像素，不连接机器人。该检查与 Quest 内的用户验收分别记录。

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
