# VR 前伸和向上伸直受限：诊断记录

日期：2026-09-15。代码基线：`feature-vr` / `d569ef96`。

用户现象：大致运动方向正确；移动到某处后停止，继续移动手柄也不再前进；向上操作主要表现为腕关节上翻。

诊断阶段完成代码核查、离线 Placo 对照，以及用户授权后的双臂小幅真机复测。以下问题描述针对修复前基线 d569ef96；后续移植实现见文末。实测使用合成手柄平移驱动当前 IK，并读取真实电机反馈；它不是用户原始 VR 操作的回放，也没有验证完整工作空间。以下区分软件问题、离线证据与真机证据。

## 已确认的问题

### 1. 电机角度与 URDF 之间缺少参考零点映射

`motors/motors_bus.py` 的 `DEGREES` 归一化以各电机标定行程的中点作为零度：

```text
robot_deg = (tick - (range_min + range_max) / 2) * 360 / 4095
```

ROS2 保存的实机参考映射使用 `reference_tick`、`reference_q_rad` 和 `sign`：

```text
urdf_rad = reference_q_rad + sign * tick_delta * 2*pi / 4096
```

其中 tick_delta 还需按周期和已标定区间选择连续分支，不能对跨周期关节直接使用未处理的角度差。

网关入口只传入 `joint_signs`，没有传入 `joint_offsets_deg`；IK 的 offset 默认全为零。因此当前实现相当于把“行程中点”当成“CAD 零位”。当前 offset 接口也只按关节名索引，无法直接表达左右臂各自不同的零点。

对本地 ROS2 成套保存的电机标定和参考姿态进行检查：

| 关节 | 参考姿态应有的 URDF 角度 | 当前转换得到的左臂角度 | 当前转换得到的右臂角度 |
| --- | ---: | ---: | ---: |
| shoulder_lift | 0° | +99.912° | +99.516° |
| elbow_flex | 0° | -93.055° | -95.077° |

这组参考姿态经错误映射后的 TCP 位置偏差分别为 186.81 mm 和 196.29 mm。肩肘的角度误差可以部分抵消末端朝向误差，因此“姿态方向看起来基本对”不代表 FK 几何正确。

证据来源：

- 当前仓库 `src/lerobot/motors/motors_bus.py`、`src/lerobot/vr_gateway/arm_ik.py`、`src/lerobot/vr_gateway/server.py`。
- 本地 `alohamini_ros2/src/alohamini_calibration/config/lerobot/AlohaMiniRobot.json`。
- 同目录下 `hardware/hardware_joint_map_left.yaml`、`hardware_joint_map_right.yaml`。
- `alohamini_ros2/src/alohamini_lerobot_bridge/alohamini_lerobot_bridge/protocol.py` 的 `JointMapper`。

**不能直接部署上述旧标定数值。** 树莓派当前电机标定的 12 个臂关节 `homing_offset` 都与本地 ROS2 保存值不同，非腕滚转关节的行程范围也不同。上表证明当前算法与已有实机参考模型不兼容；它不是新标定下已确认的角度误差。当前机器需要重新绑定参考姿态，或使用经过验证的标定迁移结果。

### 2. IK 没有使用当前机器的真实关节范围

树莓派当前电机标定换算出的 robot/action 角度范围如下。这里只列出与症状最相关的关节，没有加入额外余量。

| 关节 | 左臂 | 右臂 | 当前 IK 使用的范围 |
| --- | ---: | ---: | ---: |
| shoulder_lift | ±101.319° | ±102.198° | 约 ±179.909° |
| elbow_flex | ±96.835° | ±94.857° | 约 ±179.909° |
| wrist_flex | ±94.374° | ±94.242° | 约 ±179.909° |
| wrist_yaw | ±85.626° | ±85.231° | 约 ±179.909° |

入口没有把电机标定转换成 URDF 限位。即使显式提供 `joint_limits_deg`，当前实现也只是覆盖输出裁剪数组，没有更新求解器内部的模型限位。这会使求解与可执行输出不一致。

从当前默认姿态出发、保持手柄朝向并上移 40 cm（目标上移 20 cm），理想反馈回放给出的肩关节命令约为 -144°，已超出当前电机标定范围。真实肩部无法继续执行时，腕部仍可能调整，表现与用户描述相符。后续小幅真机复测也观察到上移时肩部基本不动、腕部上翻，右臂的求解命令继续趋向肩部下限；测试在预留的保护边界处停止，没有触碰硬限位。

树莓派保留的历史诊断日志也存在命令越界：与当前标定比较，右肩升降关节 277 条、右肘 945 条 IK 输出超出范围。该日志结束于右 `shoulder_pan` 过流；不能把它当成本次伸展问题的记录，也不能据此把过流原因归到肩升降关节。

### 3. 固定肩肘起始姿态的任务会阻碍伸直

`posture_tasks` 将前三个关节持续拉向握柄时的角度，默认权重为 `5e-4`。它与末端任务都是 `soft`，属于同一个加权优化问题，并不是严格只作用于末端任务的零空间。

当臂接近伸直时，位置对部分关节角度的变化不敏感。求解器可以保留明显的肘部弯曲，以换取更小的姿态偏离，最终位置误差也不会通过等待或增加迭代次数自动消失。

使用旧标定构建一个独立、理想执行的模型，并用 FK 生成整条路径都在该标定范围内的前伸/上伸目标；通过真实 `AlohaMiniDualArmIK.update()` 输入对应的手柄位置和姿态：

| 对照条件 | 前伸终点误差，左右臂 | 上伸终点误差，左右臂 |
| --- | ---: | ---: |
| 当前关节转换、默认 posture 权重 | 302–320 mm | 129–160 mm |
| 仅在离线实例补齐参考映射 | 12.715 mm | 6.485 mm |
| 补齐映射，posture 权重改为 `1e-6` | 0.270 mm | 0.167 mm |
| 补齐映射，posture 权重改为 `0` | <0.1 mm | <0.1 mm |

这组结果说明已知可达目标会被当前转换和任务偏好阻碍。它使用旧参考标定、理想反馈和合成的完整位姿路径，不是新标定机器的精度测量，也不是用户仅平移手柄动作的原始回放。完全去除 posture 权重只用于定位；部署前仍须检查奇异位形、分支连续性和限位。

## 其他因素的对照结果

- 求解次数从 20 增加到 100：轴向回放的稳态误差基本不变，不支持“迭代次数不足”作为主要原因。
- 平移倍率 `0.5`：手柄移动 40 cm，目标移动 20 cm。它影响单次可用行程，但不是固定关节范围，也不能解释继续移动后只翻腕的全部现象。
- 降低末端姿态权重至 `0.01`：部分上伸误差减小，但朝向误差增大，不能修复零点和限位问题。
- 完全取消末端姿态权重：出现超过 100° 的夹爪朝向偏差，不能直接用作保留当前腕部操作语义的修复。
- `max_state_deviation_deg=45` 是命令相对于最新实测角度的最大领先量，不是相对于初始姿态的总行程限制。关节正常跟随时可以累计移动超过 45°。

## 树莓派核查

- `arm_ik.py`、`server.py`、URDF 的 SHA-256 与本地完全一致。
- 远端 Git HEAD 较旧，当前代码主要通过文件同步部署；存在较多本地改动，不能用远端提交号单独判断运行代码版本。
- 核查时没有运行中的 VR 网关进程。
- `/home/pi5/vr_gateway_diag_current.log` 与本地此前保存的历史日志逐字节一致，记录时段为日志自身时间 `2026-09-15 03:42:17` 至 `03:44:04`。
- `/home/pi5/vr_tel.log` 是更早的记录。
- 当前电机标定已只读下载到本地 `/tmp/vr_pi_calibration.json`；历史日志保存在 `/tmp/vr_pi_gateway.log`。

## 小幅真机复测

通过独立探针直接访问左右 Feetech 总线，使用当前 `AlohaMiniDualArmIK` 和真实反馈，保持合成手柄朝向不变，采用默认身体坐标基准。没有调用会执行升降回零及电机配置的 `AlohaMini.connect()`，没有向底盘、升降或夹爪发送运动目标。

最终四组试验每个关节相对本组起点的目标变化最多 5°，单步命令最多 0.25°，测试期间 `Goal_Velocity=100`、`Acceleration=100`。位置保护在标定限位内预留 1°；若初始已处在余量内，只允许向区间内部运动。结束后各组均返回至距本组起始关节角不超过 1°。

| 试验 | 合成手柄位移 | 肩升降关节最大实测变化 | 腕俯仰关节最大实测变化 | 结果 |
| --- | ---: | ---: | ---: | --- |
| 左臂上移 | 25 mm | 0° | 1.407° | 完成并返回 |
| 左臂前移 | 20 mm | 2.901° | 0.527° | 完成并返回 |
| 右臂上移 | 最后已发送样本 11.75 mm | 0° | 1.143° | 保护停止并返回 |
| 右臂前移 | 20 mm | 2.989° | 0.088° | 完成并返回 |

右臂上移停止时，IK 请求肩升降关节到 `−101.214°`，超出探针预留的下界 `−101.198°`。电机标定的实际下界为 `−102.198°`，因此这是提前约 1° 的软件保护停止，不能写成“撞到物理硬限位”。

四组试验按现有 6.5 mA/raw 换算的峰值电流为 110.5 mA，没有过流。前移时两侧肩部均能运动；上移时当前 IK 把肩部目标推向下限，同时依赖肘腕补偿，支持优先修复参考零点和限位模型。受限于测试幅度和相机视角，仍不能据此确认全行程可达性、实际 TCP 精度或当前姿态就是 CAD Home。

此前两组更保守的探针使用较低加速度或较小命令领先阈值，因 `no_progress` / `tracking_lead` 提前终止，之后已恢复并调整探针参数。它们属于测试参数触发的停止，不能作为用户原始问题的原因。

结束后的寄存器快照与复测前初始快照逐字段比较通过：两臂共 14 个电机扭矩全部关闭，速度和加速度恢复原值，EEPROM 的 `Homing_Offset`、`Min_Position_Limit`、`Max_Position_Limit` 均未改变。没有遗留网关或测试运动进程。

原始证据位于本机 `/tmp/vr_retest_evidence/`：`left_up_v2.jsonl`、`left_forward_v2.jsonl`、`right_up.jsonl`、`right_forward.jsonl` 和 `final_verified.json`。初始快照为 `/tmp/vr_retest_snapshot_local.json`。这些临时文件没有纳入版本控制；真机探针 `/tmp/vr_hardware_retest.py` 会产生实际运动，不属于下面的离线复现命令。

## 离线可复现命令

下面保留诊断阶段基于 d569ef96 的命令记录。移植后内部转换接口已变化，当前版本应运行 `tests/vr_gateway/test_calibrated_ik.py`；不要把旧 `/tmp` 探针作为新版回归。诊断时使用现有 Conda 环境，因为 uv 环境缺少 Placo。

```bash
# 当前配置的前移/上移扫描；理想执行反馈。
conda run -n lerobot_alohamini python /tmp/diagnose_vr_reach.py

# 参考姿态转换契约：当前代码失败，肩肘约有 93–100° 差异。
conda run -n lerobot_alohamini python /tmp/vr_mapping_probe.py --mode reference

# 旧参考标定下的已知可达完整位姿路径：当前映射 4/4 失败。
conda run -n lerobot_alohamini python /tmp/vr_mapping_probe.py --mode current

# 只在离线实例替换转换函数并减弱肩肘偏好：4/4 通过。
conda run -n lerobot_alohamini python /tmp/vr_mapping_probe.py \
  --mode calibrated --posture-weight 0.000001
```

探针中的单变量实验没有修改仓库运行代码。轴向扫描的结果文件为 `/tmp/vr_reach_*.json`；参考映射对照为 `/tmp/vr_mapping_current.json` 和 `/tmp/vr_mapping_calibrated.json`。探针依赖上述本地 ROS2 标定文件，不应直接复制到树莓派作为运动脚本。

## alohamini_ros2 标定流程与文件的复用

建议复用完整的电机角度到 URDF 的映射链，以及对应的文件格式。当前 VR 缺少参考零点，并没有使用左右臂实际限位；ROS2 已有这些机制。但现存 ROS2 文件是旧 EEPROM 状态下的机器数据，不能原样替换当前标定。

| ROS2 内容 | 复用方式 |
| --- | --- |
| `alohamini_lerobot_bridge/protocol.py` 的 `JointMapper` | 提取单位转换、左右臂参考映射、周期连续性和逆向限位校验逻辑；适配 VR 的状态与 IK 接口，无需启动整套 ROS2。 |
| `hardware_joint_map_left.yaml` / `hardware_joint_map_right.yaml` | 复用结构和同一机械装配下的参考姿态定义；依据当前机器重新采集 `reference_tick`，更新标定指纹和 `safe_q_min_rad/max_rad`。 |
| `alohamini_calibration/scripts/sync_arm_mapping` | 复用“当前 LeRobot JSON + 已确认折叠 CAD Home 的稳定读数 → 候选机器配置”流程。脚本只读取 Host 状态，不写 EEPROM；当前 LeRobot Host 已实现所需 `:state` 和元数据协议。 |
| `alohamini_calibration/scripts/calibrate_arms` | 可复用手动电机行程标定流程；会写 EEPROM，默认保留 Homing Offset、重写行程，也可选择重标零偏。当前 JSON 与 EEPROM 匹配，暂没有证据表明修复 VR 映射必须先重做这一步。 |
| `alohamini_description` 的运动学 URDF 与 TCP | 可作为统一模型来源，但必须一起对齐基座坐标、末端坐标和当前机器限位，不能只替换 URDF 文件。 |

`sync_arm_mapping` 保留模板的 `reference_q_rad` 和 `sign`，要求双臂处于已确认的折叠 CAD Home，夹爪闭合后采集稳定读数。它不能仅凭新旧 JSON 自动推断当前真实姿态，也不能把本轮任意静止姿态的编码器读数当成 Home。生成文件标记为 `candidate_requires_rviz_and_collision_validation`；夹爪 open tick 也会按当前行程校验。

ROS2 的 `base_cad_joint` 在标准 `base_link` 与 CAD 基座之间加入 +90° yaw，TCP 基于 `Fixed_Jaw`，当前 VR 末端采用 `Moving_Jaw`。此外 `config/kinematics/kinematics.yaml` 明确标注 `source: cad_export_unverified`、`calibrated: false`。这意味着 ROS2 提供了更完整的编码器到模型映射，但尚不能证明连杆尺寸、轴线与 TCP 已完成实机几何校准。

预期收益是让求解器看到真实的关节姿态和可用范围，避免沿错误方向逼近限位。伸直能力还受当前肩肘 posture 任务影响，需要单独修复和验证，不能承诺复制标定文件就解决全部症状。

## 后续修复顺序

1. 根据当前 EEPROM 标定，建立左右臂独立的已知实机姿态与 URDF 参考角度对应关系，验证 FK 与真实上臂、前臂方向一致。
2. 将完整的 `sign/reference/offset` 双向转换接入网关，处理 4095/4096 的比例差异和跨周期关节；把同一标定换算出的限位同时接入求解器与输出保护。
3. 将固定起始肩肘姿态的强制偏好改为不会阻碍主要末端任务的策略；先验证较弱权重、目标跟踪、分支连续性，再决定最终实现。
4. 在模型正确后重新验证前后平移和头显 yaw 对齐。当前平移反向补偿是在旧转换下增加的经验修正，不能假定补齐零点后仍应原样保留。
5. 修复后通过 `[VR-DIAG]` 日志对比输入、目标位姿、求解关节、裁剪后命令、实测关节及电流，完成水平前伸、上伸和腕部控制的低速闭环确认，并与本轮小幅真机证据比较。

目前已获得当前机器的小幅复测日志；仍缺少当前标定下的参考姿态绑定，以及接入正确映射后的完整伸展验证。新实现尚未使用当前机器重新采集的 Home 做全行程验证，不将历史 offset 或离线结果表述为实机已验证修复。


## 后续实现：移植 ROS2 流程，不依赖 ROS

按用户要求，已将电机行程标定、Home 采集与 JointMapper 移植到 `src/lerobot/vr_gateway/calibration/`，移除 ROS 包发现依赖。默认直接读取双臂串口，不启动整机连接/回零；独立验证命令输出参考及实测运动学图。完整操作步骤见 [VR 双臂标定与零点确认](vr_calibration.md)。

生产 VR 入口现在要求本机 Home 映射，校验标定指纹；使用 ROS2 的标准基座和 Fixed_Jaw TCP；左右臂真实限位同时写入 Placo 与输出保护；posture 默认权重降为 `1e-6`。新映射路径不使用旧的平移反向补偿。

本地针对映射、串口只读、过期标定拒绝、可达伸展路径及原 VR/机器人控制的 83 项测试通过。数值伸展回归包含左右臂水平前伸及上伸，末端位置误差要求小于 1 mm；它们使用历史成套标定作为离线夹具，不是当前实机精度结果。测试退出时现有 `multiprocess` 环境有 ResourceTracker 析构警告，pytest 返回码为 0。

待实机完成：人工按参考图摆放并确认 Home、采集当前编码器参考、核对真实连杆方向，再运行新标定的低速伸展验证。没有把旧 YAML 中的 tick 或本轮任意静止读数写成当前机器的已确认零点。


## 树莓派部署与用户确认（2026-09-15）

移植文件已同步，原文件备份于树莓派 `/tmp/vr-calibration-backup-20260915T085941Z`；保留了远端独立的上线文档内容。树莓派没有安装 `rclpy`，三个 CLI、全行程映射往返、Placo 限位加载和参考图生成均通过。补装 Matplotlib 时将 NumPy 固定为已有的 2.2.6。

第一次电机握手未得到响应，检查串口无人占用后再次采集成功：双臂 14 个电机均可读取。只读采集前后扭矩、速度、加速度和 EEPROM 标定字段一致，14 个电机扭矩均为关闭。本次移植验证没有发送运动目标；报告位于树莓派 `/tmp/vr-calibration-port-verification.json`。

用户明确要求保留出厂行程标定，因此后续主流程仅为：参考姿态摆放 → 只读 Home 采集 → FK 对照 → VR。用户提供的折叠照片可用于对照大体形态，但尚未据此确认完整关节参考角度或夹爪闭合状态，未生成当前机器的正式 Home 映射。
