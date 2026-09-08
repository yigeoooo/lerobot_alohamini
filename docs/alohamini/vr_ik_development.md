# AlohaMini VR 摇操机械臂标准开发流程记录

本文是 `vr_gateway` 的 IK 开发主文档。它用于记录“发现问题 -> 复现 -> 定位 -> 设计 -> 实现 -> 单测 -> 仿真/回放 -> 树莓派台架 -> 低速实机 -> 完整验收 -> 回归关闭”的闭环过程。

标记规则：

- `[x]` 仅表示已经有代码/文档证据，或已完成静态检查。
- `[ ]` 表示未完成。
- `[~]` 表示部分完成、待验证，或只完成了非实机证据。
- 未做实机验证前，不要把 `[x]` 当作最终通过。
- 每一项都必须保留 `验证记录：____`，后续按日期持续更新。

主开发与验证环境：

- 树莓派上运行 `conda activate lerobot_alohamini`。
- PC 只通过 SSH 进入树莓派执行命令。
- Quest 通过 USB 连接树莓派，使用 `adb reverse tcp:8000 tcp:8000` 访问 `http://localhost:8000/`。

当前事实基础：

- `src/lerobot/robots/alohamini/alohamini.py` 中 `configure()` 会 `disable_torque()` 并设置位置/速度模式，但 `enable_torque()` 目前被注释。
- `src/lerobot/robots/alohamini/alohamini.py` 的 `calibrate()` 会读取/写回树莓派上的 motor calibration 文件。
- 树莓派上的 `/home/pi5/.cache/huggingface/lerobot/calibration/robots/alohamini/AlohaMiniRobot.json` 已核实只含 `id/drive_mode/homing_offset/range_min/range_max`，它是底层电机校准文件，不是 VR midpoint 文件。
- `vr_gateway` 当前 `_engage()` 使用实时机器人状态和当前手柄 pose 锁存 `_robot0/_ctrl0`，因此 VR 中位应作为运行时重锚定流程，而不是复用底层 motor calibration 文件。

## 标准执行顺序

1. 发现问题。
2. 复现问题。
3. 定位证据。
4. 设计方案。
5. 实现修改。
6. 单元测试。
7. 仿真/离线回放。
8. 树莓派台架验证。
9. 低速实机验证。
10. 完整验收。
11. 回归关闭。

## 状态流转规则

- 问题首次出现时记为 `[ ]`。
- 已找到代码/文档证据但未验证实机时，记为 `[~]`。
- 只有代码、仿真、台架和实机验收都满足通过标准后，才能改成 `[x]`。
- 如果回归复现，必须从 `[x]` 退回 `[~]` 或 `[ ]`，并补充新一轮验证记录。

## P0 安全与正确性

### P0-1 电机 torque enable/disable 生命周期

- 状态：`[ ]`
- 问题名称：`connect -> configure -> enable_torque` 生命周期不闭环
- 现象/风险：连接后可能进入配置模式但没有真正上扭矩，表现为“命令在变、机器人不跟”或外力可拖动。
- 根因证据：[`src/lerobot/robots/alohamini/alohamini.py`](../../src/lerobot/robots/alohamini/alohamini.py) 中 `configure()` 第 436-460 行，`enable_torque()` 被注释；`connect()` 第 274 行后直接调用 `configure()`。
- 开发任务：补齐连接后扭矩使能、断线/急停后扭矩处理、状态自检。
- 推荐解决方案：把 torque 生命周期显式化，连接后写入模式并 enable；断线和 E-STOP 时先停速度，再按策略 disable；启动时打印寄存器/状态。
- 需要修改的文件/模块：`src/lerobot/robots/alohamini/alohamini.py`、`src/lerobot/robots/alohamini/config_alohamini.py`。
- 验证步骤：单元测试 -> 树莓派台架 -> 低速实机。
- 通过标准：连接后扭矩状态明确为 enabled；断线/E-STOP 后两条总线速度为 0。
- 验证记录：____
- 回归项/完成后下一步：复查断线、watchdog、E-STOP 是否都覆盖 lift/base/arm。

### P0-2 型号与 URDF/DOF/关节映射

- 状态：`[ ]`
- 问题名称：型号选择和 URDF/DOF 没有完全自检
- 现象/风险：模型与实机不匹配时，IK 会把错误关节当正确关节求解。
- 根因证据：[`src/lerobot/robots/alohamini/alohamini.py`](../../src/lerobot/robots/alohamini/alohamini.py) 第 119-128 行调用 `validate_robot_model()`；`docs/alohamini/vr_ik_development.md` 现有记录已指出 IK 固定用 AlohaMini 2 Pro URDF。
- 开发任务：为每个 SKU 明确型号、DOF、关节名、URDF 哈希和状态键。
- 推荐解决方案：启动时打印型号、URDF、关节顺序和 DOF；5-DoF 不得加载 6-DoF IK。
- 需要修改的文件/模块：`vr_gateway/arm_ik.py`、`vr_gateway/server.py`、`src/lerobot/robots/alohamini/model_specs.py`。
- 验证步骤：静态检查 -> 启动自检 -> 低速单轴实机。
- 通过标准：型号、关节数、状态键和 URDF 一一对应。
- 验证记录：____
- 回归项/完成后下一步：检查关节方向、零点和实际 ROM。

### P0-3 motor calibration 与 VR midpoint 的边界

- 状态：`[x]`
- 问题名称：底层 motor calibration 是否可直接当 VR 中位
- 现象/风险：如果把电机校准文件误当作 VR 中位文件，会把驱动零点当成操作员握持参考，导致首帧跳变或姿态错位。
- 根因证据：树莓派 `/home/pi5/.cache/huggingface/lerobot/calibration/robots/alohamini/AlohaMiniRobot.json` 已核实只含 `id/drive_mode/homing_offset/range_min/range_max`；[`src/lerobot/robots/alohamini/alohamini.py`](../../src/lerobot/robots/alohamini/alohamini.py) 第 291-337 行 `calibrate()` 会读取/写回此类校准；`_engage()` 使用实时状态 + 当前手柄 pose 锁存 `_robot0/_ctrl0`。
- 开发任务：把底层 motor calibration、机器人安全中位、VR 中位重锚定分开记录。
- 推荐解决方案：motor calibration 只用于电机零点/方向/行程；VR 中位由运行时重锚定产生，作为 `_ctrl0/_robot0`。
- 需要修改的文件/模块：`vr_gateway/arm_ik.py`、`vr_gateway/static/app.js`、`docs/alohamini/vr_gateway.md`。
- 验证步骤：只读校验文件内容 -> 实机重锚定 -> 首帧不跳。
- 通过标准：校准文件不直接驱动 VR 中位；重锚定流程可重复。
- 验证记录：____
- 回归项/完成后下一步：给 VR 中位单独建配置或运行时状态记录。

### P0-4 关节方向/零点/真实 ROM 与 URDF 映射

- 状态：`[ ]`
- 问题名称：逐关节方向、零点、真实范围没有实机闭环
- 现象/风险：方向反了会越解越错；零点错位会首帧跳变；范围过大则可能越界。
- 根因证据：[`src/lerobot/robots/alohamini/alohamini.py`](../../src/lerobot/robots/alohamini/alohamini.py) 中 calibration 生成和 `MotorCalibration` 读取链路；`arm_ik.py` 里关节映射和限位依赖配置。
- 开发任务：建立机械中位、正负小角度、极限位测试和版本化记录。
- 推荐解决方案：每个关节逐个标定 `sign/offset/ROM`，并写入配置文件。
- 需要修改的文件/模块：`vr_gateway/arm_ik.py`、`src/lerobot/robots/alohamini/alohamini.py`、配置文件。
- 验证步骤：机械中位 -> 正负小角度 -> 实测限位。
- 通过标准：实测方向和 URDF 方向一致，误差在可接受阈值内。
- 验证记录：____
- 回归项/完成后下一步：检查首次 engage 的状态 gate。

### P0-5 首次 engage 完整观测 gate

- 状态：`[~]`
- 问题名称：首次 engage 不能用缺失关节默认 0
- 现象/风险：WebSocket 刚连上时若状态未齐全，首帧可能把缺失关节当 0，造成大跳变。
- 根因证据：当前 `_engage()` 依赖完整左右臂关节状态；`vr_ik_development.md` 中已有“缺失键按 0 处理”的风险记录。
- 开发任务：在 engage 前校验左右全部关节、夹爪、升降和健康字段。
- 推荐解决方案：未满足完整观测时拒绝 engage，并返回明确原因码。
- 需要修改的文件/模块：`vr_gateway/server.py`、`vr_gateway/arm_ik.py`、`vr_gateway/static/app.js`。
- 验证步骤：删字段注入 -> stale 注入 -> 首次 engage 测试。
- 通过标准：缺字段时不进入 IK active，且不写入臂命令。
- 验证记录：2026-09-07，已补 `required_state_keys()` gate、缺字段/非法值拒绝、单测覆盖。
- 回归项/完成后下一步：补 release/reset 逻辑。

### P0-6 E-stop、disconnect、watchdog 同时停底盘/升降/手臂

- 状态：`[ ]`
- 问题名称：安全停车没有覆盖所有通道
- 现象/风险：只停底盘不一定停升降；断线时升降可能继续 jog。
- 根因证据：当前文档和实现都提示 `lift_axis.vel` 的停车链路不完整；`vr_gateway.md` 已写明这是已知限制。
- 开发任务：将 E-STOP、disconnect、watchdog 做成同一安全停车动作。
- 推荐解决方案：base/arm/lift 分通道清零速度，并清除待处理姿态和 clutch 状态。
- 需要修改的文件/模块：`vr_gateway/server.py`、`src/lerobot/robots/alohamini/alohamini.py`、`vr_gateway/static/app.js`。
- 验证步骤：按住 A/B 后拔网线、断开浏览器、触发 E-STOP。
- 通过标准：底盘、升降、手臂都停，且状态机回到安全态。
- 验证记录：____
- 回归项/完成后下一步：验证 stale/replay 不会喂活 watchdog。

### P0-7 消息时间戳 / stale / replay / active=false release

- 状态：`[ ]`
- 问题名称：释放消息不能被 stale 丢弃
- 现象/风险：迟到的 `active=false` 若被丢弃，会保留旧 clutch，下一次重新握柄可能跳变。
- 根因证据：现有文档已指出 `active=false`/reset 不能走普通 stale 路径；`server.stage_message()` 需要区分消息类型。
- 开发任务：把 release/reset 与 active pose 分开处理。
- 推荐解决方案：`active=false`、reset、E-stop 直接生效；只有 `active=true` 需要 fresh pose 校验。
- 需要修改的文件/模块：`vr_gateway/server.py`、`vr_gateway/arm_ik.py`。
- 验证步骤：延迟包、乱序包、断包、单侧释放、重新 engage。
- 通过标准：release 一定清理 pending pose 和 clutch 基准。
- 验证记录：____
- 回归项/完成后下一步：继续做跟手质量和 state blend。

## P1 跟手质量

### P1-8 VR world → robot yaw、左右镜像、controller → TCP 标定

- 状态：`[ ]`
- 问题名称：坐标系与外参未实机标定
- 现象/风险：手向前，臂向侧面或后面走。
- 根因证据：`vr_ik_development.md` 中已有对 `VR_TO_ROBOT` 和头显朝向的风险分析。
- 开发任务：标定 Quest world 到 robot base 的 yaw，以及左右 controller 到 TCP 的镜像/旋转/平移。
- 推荐解决方案：把 yaw 和 controller 外参写成版本化参数。
- 需要修改的文件/模块：`vr_gateway/arm_ik.py`、`vr_gateway/static/app.js`、配置文件。
- 验证步骤：单轴平移、单轴旋转、重新朝向后重复测试。
- 通过标准：左右手动作在机器人上方向一致且可重复。
- 验证记录：____
- 回归项/完成后下一步：检查闭环 state blend。

### P1-9 state_blend 闭环与实测状态融合

- 状态：`[~]`
- 问题名称：IK 目前长期开环
- 现象/风险：串口延迟、堵转、外力和裁剪会让 solver 与真实关节逐渐偏离。
- 根因证据：`vr_ik_development.md` 已记录 `state_blend=0.0` 的问题。
- 开发任务：给实测关节一个明确的融合比例。
- 推荐解决方案：从小比例 measured-state blend 开始，并记录噪声和漂移。
- 需要修改的文件/模块：`vr_gateway/arm_ik.py`。
- 验证步骤：堵转、外力、目标裁剪对比测试。
- 通过标准：solver 和实测状态不会持续分离。
- 验证记录：2026-09-07，保持 `state_blend` 入口，补充空测量保护；仍需树莓派/实机抖动验证。
- 回归项/完成后下一步：补 clutch/丢帧状态机。

### P1-10 XR clutch / 丢帧 / 重锚定 / 单臂状态机

- 状态：`[~]`
- 问题名称：抓握状态机不够完整
- 现象/风险：丢帧、重连、单侧释放时可能保留旧基准。
- 根因证据：当前文档中已经指出 `active=false`、reset、clutch 需要单独建模。
- 开发任务：明确 `DISCONNECTED -> READY -> ARMED -> HOLD -> ESTOP`。
- 推荐解决方案：把 grip deadman、网页冻结、断线、重锚定分别建模。
- 需要修改的文件/模块：`vr_gateway/server.py`、`vr_gateway/static/app.js`。
- 验证步骤：延迟、乱序、单侧释放、刷新页面。
- 通过标准：重锚定首帧不跳，丢帧自动回到 hold。
- 验证记录：2026-09-07，已补 `Re-anchor / Align` 按钮、`arm_pose.reanchor` 标记、status telemetry 和单测；待 Quest/树莓派实机验收。
- 回归项/完成后下一步：同步 lift/base 到 IK。

### P1-11 lift 高度和 base 位姿同步到 IK

- 状态：`[ ]`
- 问题名称：升降和底座位姿没有进入 IK 基座
- 现象/风险：升降改变后，模型中的工作空间和碰撞判断失真。
- 根因证据：`vr_ik_development.md` 中已指出 `_engage()` 把 frozen joints 置 0。
- 开发任务：把 `lift_axis.height_mm` 和 base 位姿注入模型。
- 推荐解决方案：将实时高度映射到 `vertical_move` 或等价 base transform。
- 需要修改的文件/模块：`vr_gateway/arm_ik.py`、`src/lerobot/robots/alohamini/lift_axis.py`。
- 验证步骤：改变升降高度，固定手柄姿态，检查末端世界高度。
- 通过标准：世界高度和模型高度一致。
- 验证记录：____
- 回归项/完成后下一步：统一 gripper 映射。

### P1-12 gripper 双侧映射与单位/方向

- 状态：`[ ]`
- 问题名称：左右夹爪映射和单位不统一
- 现象/风险：桌面 slider 可能只命中一侧或单位不对。
- 根因证据：`vr_ik_development.md` 和 `vr_gateway.md` 都指出桌面 `gripper.position` fallback 不可靠。
- 开发任务：分别定义左右 trigger 到左右夹爪的单位、方向和范围。
- 推荐解决方案：Quest trigger 为主，桌面入口作为诊断。
- 需要修改的文件/模块：`vr_gateway/static/app.js`、`vr_gateway/server.py`。
- 验证步骤：空载 0/中值/满值测试。
- 通过标准：左右动作独立且方向正确。
- 验证记录：____
- 回归项/完成后下一步：对齐控制周期和 solver_dt。

### P1-13 控制周期、solver_dt、串口阻塞与延迟

- 状态：`[ ]`
- 问题名称：控制节拍和求解节拍不一致
- 现象/风险：跟手慢、突然追赶、限速不一致。
- 根因证据：`vr_ik_development.md` 中已记录 `solver.dt=0.04` 与实际 tick 可能不一致。
- 开发任务：让 solver、平滑和限速使用同一实际 tick。
- 推荐解决方案：记录 wall dt、solver dt 和输出步长，并设置 min/max dt 保护。
- 需要修改的文件/模块：`vr_gateway/arm_ik.py`、`vr_gateway/server.py`。
- 验证步骤：注入串口阻塞和调度抖动。
- 通过标准：日志能解释每次延迟和输出步长。
- 验证记录：____
- 回归项/完成后下一步：进入鲁棒性和工程化。

## P2 IK 鲁棒性与工程化

### P2-14 真实关节限位、奇异性、不可达、自碰撞/工作空间约束

- 状态：`[ ]`
- 问题名称：安全约束还不够完整
- 现象/风险：不可达目标、奇异位形或自碰撞会造成抖动和拒绝。
- 根因证据：`vr_ik_development.md` 已指出关节限位和奇异性处理仍不足。
- 开发任务：建立统一安全层。
- 推荐解决方案：把硬限位、速度/加速度、工作空间、奇异性和自碰撞一起拒绝。
- 需要修改的文件/模块：`vr_gateway/arm_ik.py`。
- 验证步骤：离线边界扫描 + 低速实机越界测试。
- 通过标准：越界目标只保持安全目标，不追赶。
- 验证记录：____
- 回归项/完成后下一步：补 telemetry。

### P2-15 IK telemetry / 错误码 / 残差 / 测量-命令误差

- 状态：`[ ]`
- 问题名称：缺少可观测性
- 现象/风险：无法区分模型错、执行器没使能、网络延迟还是 IK 不可达。
- 根因证据：`vr_ik_development.md` 已指出当前只有有限计数器。
- 开发任务：补充日志和错误码。
- 推荐解决方案：记录残差、求解耗时、拒绝原因、测量-命令误差。
- 需要修改的文件/模块：`vr_gateway/arm_ik.py`、`vr_gateway/server.py`。
- 验证步骤：构造拒绝、堵转和延迟场景。
- 通过标准：每次拒绝都可追溯原因。
- 验证记录：____
- 回归项/完成后下一步：补单客户端租约。

### P2-16 单客户端租约、依赖/部署自检

- 状态：`[ ]`
- 问题名称：多客户端覆盖和依赖风险
- 现象/风险：多个浏览器互相抢控制；环境缺包会导致启动失败。
- 根因证据：`vr_gateway.md` 已说明 `/ws` 目前无认证/无租约；依赖自检也仍需补齐。
- 开发任务：加单客户端租约和启动自检。
- 推荐解决方案：第二客户端只能观察，不能写控制。
- 需要修改的文件/模块：`vr_gateway/server.py`、`vr_gateway/static/app.js`。
- 验证步骤：双浏览器并发和依赖故障注入。
- 通过标准：只有一个控制源。
- 验证记录：____
- 回归项/完成后下一步：做离线回放。

### P2-17 自动化测试、XR payload + state 离线回放、仿真与真实 URDF 一致性

- 状态：`[ ]`
- 问题名称：缺少可复现回放与一致性测试
- 现象/风险：问题只能靠手工感觉判断，难以回归。
- 根因证据：`vr_ik_development.md` 已指出没有专门的 VR/IK 测试。
- 开发任务：建立离线回放、几何测试和仿真一致性测试。
- 推荐解决方案：保存 XR payload 和 robot state，重复喂给 solver。
- 需要修改的文件/模块：`tests/vr_gateway/`、`vr_gateway/arm_ik.py`。
- 验证步骤：固定输入回放、比较关节和末端误差。
- 通过标准：CI 或本机可重复跑出一致结果。
- 验证记录：____
- 回归项/完成后下一步：做实机验收矩阵。

### P2-18 实机验收矩阵和回归测试

- 状态：`[ ]`
- 问题名称：缺少标准验收表
- 现象/风险：无法判断“已经完成”还是“暂时能用”。
- 根因证据：`vr_ik_development.md` 已列出验收指标，但还没形成固定矩阵。
- 开发任务：把低速单关节、双臂中心工作区、重新 engage、底盘/升降、E-STOP、断线、长时间闭环写成验收矩阵。
- 推荐解决方案：每个验收项都记录日期、硬件、命令和结果。
- 需要修改的文件/模块：`docs/alohamini/vr_ik_development.md`、`docs/alohamini/vr_gateway.md`。
- 验证步骤：按脚本逐项验收并签字。
- 通过标准：矩阵中的所有必测项通过。
- 验证记录：____
- 回归项/完成后下一步：进入正式回归关闭。

## 统一记录模板

当你发现新问题时，按下面格式追加：

```md
### P?-编号 问题名称

- 状态：`[ ]` / `[~]` / `[x]`
- 问题名称：
- 现象/风险：
- 根因证据：
- 开发任务：
- 推荐解决方案：
- 需要修改的文件/模块：
- 验证步骤：
- 通过标准：
- 验证记录：____
- 回归项/完成后下一步：
```

## 当前结论

- motor calibration 文件不能直接作为 VR midpoint。
- VR midpoint 应由运行时重锚定产生。
- 没有 torque enable、完整状态 gate 和 lift 停车之前，不应宣称 VR IK 已完成。
- `conda activate lerobot_alohamini` 是当前主运行环境；Quest 通过 USB + ADB reverse 访问 `http://localhost:8000/`。
