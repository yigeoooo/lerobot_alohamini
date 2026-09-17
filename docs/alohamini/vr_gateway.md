# AlohaMini VR Gateway 上线与操作记录

本文面向操作员和部署人员，记录 `vr_gateway` 的上线检查、VR 摇操流程、问题关闭模板和真实启动命令。

2026-09-17 起，默认 `--arm-ik-mode legacy` 使用 **本机 Folded Home 零位映射**。启动前先完成下文的一次性参考姿态采集与核对；缺少映射或文件与当前电机标定不符时，网关在连接硬件前报错退出。已有且确认正确的本机 Home 文件可复用。仍使用原 CAD 模型、Moving_Jaw 末端、0.5 位移倍率、Goal_Velocity=2000 和原长轴拧腕手势；从当前位置握住 Grip 建立锚点，不自动回 Home。

Home 将电机行程中点角度转换成真实 CAD 参考角度，左右臂的上下限也一起转换。原先为了错误零位增加的前后反向补偿已去掉，前移手柄对应 CAD −Y（机身前方）。本次没有把水平转手柄改成肩部一对一角度控制；位置/姿态和肩肘偏好权重也保持 legacy 默认值。离线效果与剩余限制见 [Home 接入验证](vr_legacy_home.md)。

开始一轮操控时自动按当前头部朝向对齐：任一手或双手首次 Grip 都可触发；只要还有一侧正在控制，中途加入或重新握持的另一侧就沿用同一个方向基准，仅建立自身的位置/姿态锚点。两侧均松开后，下次握持重新对齐。跟随期间转头不改变映射，Y 仍可手动重新对齐。缺少有效头部追踪时不会开始自动对齐的跟随。

桌面和 VR 画面内会弹出“限位警告”，列出对应侧和关节。依据现有电机行程与模型范围，实测角度或已接受目标距边界不超过 0.5° 时提示；离开范围边缘后消失。速度限幅或单纯 IK 残差不会冒充关节限位。反馈过期时不继续显示旧限位状态。

legacy 的夹爪端点仍使用电机行程：沿用现有电机的 RANGE_0_100 行程，两侧均为增大值打开、减小值闭合。夹爪默认闭合，按住 Trigger 打开，按得越深打开越大，松开闭合，无需同时按 Grip。进入 VR 后有有效手柄追踪和健康反馈时即发送当前扳机目标；追踪丢失、暂停、急停或反馈失效时停止发送。电机夹持电流保护继续生效。

VR 现在支持头部、左腕、右腕三路相机，**仅在传入对应启动参数时打开，不传则关闭（包括头部）**。头部使用 1280×720，腕部各使用 640×480；均请求 30 fps / MJPEG，默认最多推流 10 fps、JPEG 质量 90，不放大小尺寸来源。采集由各相机后台线程进行，读取最新帧和编码均在机器人控制锁外；一路运行中断流不会中断其他画面和状态反馈。头显关闭固定注视点降采样并启用抗锯齿。此前树莓派头部单帧 JPEG 编码约 5.3 ms、单路 10 fps 约 14.5 Mbps 的结果不能代表三路总开销；CLI 的 `--video-hz` / `--max-frame-width` / `--jpeg-quality` 可调整推流开销。

更新后重启网关并退出 VR、刷新页面；诊断栏应显示 `页面 cameras7`。桌面与头显都按名称显示已启用的相机，三路全开时头部在上方、左右腕在下方；仅开一路时放大居中。各路独立显示实时分辨率，超过 1.5 秒无新画面则隐藏旧图并显示“画面已过期”，恢复后自动显示。只同步磁盘文件不会更新已经打开的 Quest 页面。

vr5 修复高清画面进入 VR 后黑屏：改变 canvas 分辨率前释放旧 GPU 纹理，使 Three.js 按新尺寸分配存储。此前只设置 `needsUpdate`，Quest 报 `GL_INVALID_VALUE: glCopySubTextureCHROMIUM: destination texture bad dimensions`，桌面图片仍正常。保留 720p 和原画面方向。用户已确认修复后 VR 内可见诊断测试图；真实相机画面仍需在运行网关后核对。左右摆腕移除额外的 yaw 取反，恢复 d569ef96 的转向映射，保留已确认可用的长轴 twist。

机械参考采集流程与另一套模式共用，但本页运行命令统一使用 `legacy`。加载 Home 不会切换到另一套模式，也不会改用其速度、TCP 或求解权重。

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
python -m pip install fastapi "uvicorn[standard]" websockets wsproto pyyaml matplotlib
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

完成下文 Home 流程后的日常启动命令（使用默认映射目录）：

```bash
conda activate lerobot_alohamini
adb reverse --remove-all
adb reverse tcp:8000 tcp:8000
python -m lerobot.vr_gateway.server --robot-model alohamini2pro --arm-ik-mode legacy \
  --head-camera --left-wrist-camera --right-wrist-camera \
  --host 0.0.0.0 --port 8000
```

## 可选相机启动参数

三个参数各自独立，可任意组合；启动时打开所选相机，进入 VR 后即可看到画面。刷新页面或退出再进入 VR 不会重复打开相机。

| 参数 | 不指定设备值时使用 | 画面 |
| --- | --- | --- |
| `--head-camera [DEVICE]` | `/dev/am_camera_forward` | 头部 |
| `--left-wrist-camera [DEVICE]` | `/dev/am_camera_wrist_left` | 左腕 |
| `--right-wrist-camera [DEVICE]` | `/dev/am_camera_wrist_right` | 右腕 |

参数省略时，该相机不打开、也不显示画面窗口。比如只开头部，在原启动命令后加 `--head-camera`；全部省略时仍可使用 VR 遥操，界面显示“相机未启用”。这与旧版本默认打开头部相机的行为不同。

设备路径不同可直接传入，也支持 OpenCV 数字索引，例如：

```bash
python -m lerobot.vr_gateway.server --robot-model alohamini2pro --arm-ik-mode legacy \
  --head-camera /dev/video0 --left-wrist-camera /dev/video2 --right-wrist-camera /dev/video4 \
  --host 0.0.0.0 --port 8000
```

优先使用稳定的 `/dev/am_camera_*` 设备别名。传入参数的相机需已连接且支持上述 MJPEG 采集格式；打开失败时会报告启动错误，应核对设备路径和格式。未传参数的相机不需要接入。三路在真实树莓派和 Quest 上的帧率、USB 带宽与画面方向仍需实机核对。

## 首次使用：Folded Home 零位流程

这一步补充软件零位，保留现有电机行程，不写 EEPROM。机械安装、编码器零偏或标定范围发生变化后需要重新核对/采集；日常启动复用文件，不要求每次摆回 Home。头显 Y 对齐和 Grip 锚点不能替代机械参考。

### 1. 生成姿态参考图

在树莓派已有环境内执行：

```bash
cd ~/lerobot_alohamini
conda activate lerobot_alohamini
python -m lerobot.vr_gateway.calibration.verify_arm_mapping \
  --arm-ik-mode legacy --show-home --output-dir /tmp/alohamini_home
```

查看 `/tmp/alohamini_home/arm_reference.svg`（同时生成 PNG）。图中使用机身前/左/上的方向展示 legacy 的原 CAD 链和 Moving_Jaw 末端。扭矩关闭、停止网关/Host 等串口占用程序后，手动将双臂摆到图中姿态，并闭合夹爪。按上臂、前臂和腕部的方向确认，不要把任意折叠收纳姿态当作 Home。参考角度并非全部为零：左腕俯仰约 82.27°、右腕俯仰约 85.94°。

### 2. 只读采集或复用本机 Home

如果已有同一台机器、同一电机标定下采集且几何已确认的 Home，可以直接进入第 3 步。

首次采集：

```bash
python -m lerobot.vr_gateway.calibration.sync_arm_mapping
```

按提示输入 `CAPTURE FOLDED HOME`。脚本对照当前 JSON 和 EEPROM，读取 10 组稳定编码器值；不发送运动、不改变扭矩、不写电机零偏。默认输出：

```text
~/.config/lerobot/alohamini/arm_mapping/
  AlohaMiniRobot.json
  hardware_joint_map_left.yaml
  hardware_joint_map_right.yaml
```

目录存在时脚本拒绝覆盖。需要重采可指定新目录，例如 `--output-dir ~/.config/lerobot/alohamini/arm_mapping_legacy_v2`，并在后续核对和网关命令中使用相同的 `--arm-mapping-dir`。不要把仓库的历史参考 tick 或测试夹具复制成当前机器的正式 Home。

### 3. 核对姿态和转换

保持所采集的 Home，执行：

```bash
python -m lerobot.vr_gateway.calibration.verify_arm_mapping \
  --arm-ik-mode legacy --read-hardware --expect-home \
  --output-dir /tmp/alohamini_home_check
```

检查 `report.json` 与 `arm_reference.svg`：全行程双向转换应通过，实测关节与 Home 参考相差不超过 2°。随后可在扭矩关闭时手动小幅改变单关节，去掉 `--expect-home` 再核对实际方向与图形。**转换通过仅证明数值一致，不能证明摆放姿态正确。** 之前文件若仍标记 `home_captured_requires_physical_geometry_check`，需要完成这一步实物对照。

### 4. 启动 legacy

```bash
adb reverse --remove-all
adb reverse tcp:8000 tcp:8000
python -m lerobot.vr_gateway.server \
  --robot-model alohamini2pro --arm-ik-mode legacy \
  --arm-mapping-dir ~/.config/lerobot/alohamini/arm_mapping \
  --head-camera --left-wrist-camera --right-wrist-camera \
  --host 0.0.0.0 --port 8000 --diagnostics true
```

首次检查新零位时可增加 `--max-joint-speed-deg-s 15`，从小范围前移、上移、左右和拧腕开始。页面应显示 `Legacy · Home 零位已加载`、`页面 cameras7`。松开 Grip 再握持会从实测姿态重新开始，不执行自动归位。若提示文件缺失或过期，先按上述流程修复文件，不退回无零位运行。

完整采集选项见 [VR 双臂标定与零点确认](vr_calibration.md)。

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
- [ ] **Home 零位与几何核对**。完成条件：本机 Home 文件与当前标定匹配，并完成上臂、前臂和腕部的实物方向对照。验证记录：____
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
5. 确认已完成一次性 Home 流程，再启动 legacy 网关。
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

原始 WebXR 位姿在后端统一转换。legacy 在未叠加头部朝向时使用 CAD 基准 `(x_cad, y_cad, z_cad) = (-x_xr, z_xr, y_xr)`；CAD −Y 是机身前方，−X 是机身右方。末端使用 `left_Moving_Jaw/right_Moving_Jaw`，旋转继续使用 swing/twist 分解，升降高度仅用于 FK。

legacy 保留 Placo、位置/姿态权重 1/1、`posture_weight=5e-4`、90°/s 关节速度上限和最多 0.2 s 的实际周期预算。45° IK 实测领先保护和网关 20° 单步保护继续生效。Home 映射转换后的左右臂限位同时用于 Placo 与输出，保留电机原有行程。没有叠加另一模式的 5° 驱动领先或 TCP 领先限制。零位修正明显改善已知目标的跟踪，但默认姿态约束仍可能阻碍完全伸直。

显式 calibrated 模式继续使用标定模型和 TCP 领先限制；连续五帧残差较大才尝试一个附近初值，额外预算默认 6 ms（在 QP 迭代之间检查，单次 QP 不可抢占）。默认旧版模式不启用这项多初值策略。

默认反馈最大年龄 0.5 s、每侧姿态超时 0.3 s；生产设备需测量总线、相机和 QP 时延后验收。网关分别保留实测状态、操作者请求和驱动接受的目标。正常心跳保持驱动接受值，单侧释放才一次性切换到该侧实测保持值。

控制循环把 IK 与串口耗时计入 40 ms 周期，只等待剩余时间；若本轮已经超时，下一轮直接处理最新输入，不积压补发。诊断栏显示实际控制 Hz。电机寄存器参数 2000 和配置 25 Hz 都不代表实机必然达到相应速度；靠近电机行程边界时仍可能无法继续某些动作。

离线验收见 `tests/vr_gateway/test_legacy_home.py`、`test_legacy_ik.py`、`test_wrist_controls.py` 和 `test_server.py`。当前测试覆盖 Home 缺失/过期拒绝、双向转换、实际电机范围、不同对齐方向、拧腕及释放重握。零位改变后关节输出不再应与无零位的 d569ef96 快照相等。

```bash
# 不访问硬件：用归档成套标定比较接入前后
python tests/vr_gateway/benchmark_legacy_home.py --output /tmp/legacy_home_replay.json
# 使用已采集的本机文件，仍然只做离线合成回放
python tests/vr_gateway/benchmark_legacy_home.py \
  --arm-mapping-dir ~/.config/lerobot/alohamini/arm_mapping \
  --calibration-json ~/.cache/huggingface/lerobot/calibration/robots/alohamini/AlohaMiniRobot.json \
  --output /tmp/legacy_home_machine_replay.json
node tests/vr_gateway/test_frontend.cjs
```

回放使用合成轨迹和理想反馈，不连接串口；不能替代当前机器的几何、真实方向、负载及完整工作空间验收。当前模型没有完整碰撞检测。

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
| 启动报 `Arm mapping missing` / `calibration differs` | Home 缺失或与当前电机标定不匹配 | 按首次 Home 流程采集/核对，检查 `--arm-mapping-dir`。 |
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
python -m lerobot.vr_gateway.server --robot-model alohamini2pro --arm-ik-mode legacy --host 0.0.0.0 --port 8000
```

Quest 浏览器访问：

```text
http://localhost:8000/
```
