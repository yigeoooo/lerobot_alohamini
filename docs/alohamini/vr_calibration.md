# VR 双臂标定与零点确认（无需 ROS）

这套流程移植自 `alohamini_ros2` 的 `calibrate_arms`、`sync_arm_mapping` 和 `JointMapper`，直接在 LeRobot Python 环境运行。默认只访问左右臂串口，不需要 ROS、`ros2`、RViz、MoveIt 或启动 LeRobot Host。

**默认 legacy 现在也执行本页的 Home 流程**，复用采集文件而不切换遥操模式。运行总流程见 [VR 上线与操作记录](vr_gateway.md)。

电机标定确定编码器零偏和行程；Home 确认将真实机械姿态绑定到 URDF。两者缺一不可。Quest 的 Y 键只对齐操作者身体方向，不能代替机械零点确认。

## 环境与文件

树莓派使用已有环境：

```bash
cd ~/lerobot_alohamini
conda activate lerobot_alohamini
```

新环境按仓库安装 LeRobot，并安装硬件、IK 和可视化依赖：

```bash
uv pip install -e '.[feetech,pyzmq-dep,kinematics,matplotlib-dep]' fastapi 'uvicorn[standard]' pyyaml
```

默认串口为 `/dev/am_arm_follower_left`、`/dev/am_arm_follower_right`，所有硬件命令都支持 `--left-port`、`--right-port`。采集前停止占用串口的 VR 网关、Host 和遥操作程序。

## 1. 沿用出厂电机标定

本机已有出厂电机行程标定，本次不重新标定行程，也不改 EEPROM。继续使用机器人当前加载的 `AlohaMiniRobot.json`；后面的只读采集会核对它与 EEPROM 是否一致。

出厂行程描述编码器的零偏和可用范围，未包含“这台实物处于 CAD 参考姿态时各电机读多少”。下一步只补充这一组对应关系。若以后更换电机、重装舵盘或改动电机零偏，再重新采集 Home。

完整移植中保留了 `calibration.calibrate_arms` 作为维护工具，但它不属于本次操作流程。

## 2. 查看并摆放折叠 Home

先生成参考姿态图，此命令不打开串口：

```bash
python -m lerobot.vr_gateway.calibration.verify_arm_mapping \
  --arm-ik-mode legacy --show-home --output-dir /tmp/alohamini_home
```

打开 `/tmp/alohamini_home/arm_reference.svg`，在扭矩关闭时，按原 ROS2 流程手动摆放左右臂到对应的折叠 Home，并闭合夹爪。图中使用机身前/左/上坐标，展示 legacy 原 CAD 的两侧肩、肘、腕、Moving_Jaw 末端的侧视、正视和俯视位置；终端同时列出 CAD 参考角度。图是连杆关节位置示意，不是碰撞模型。需要确认实物上臂、前臂和腕部方向与图一致，不能把任意静止姿态或者电机行程中点当成 Home。

从侧面看，这套参考姿态的上臂朝后、略向上，前臂折回来大致水平朝前，腕部与夹爪朝下；两臂分别位于机身两侧。它不是上臂与前臂并拢贴在机身上的任意“收纳姿态”。以参考图中的关节位置为准。

沿用 ROS2 的参考定义：肩旋转、肩升降、肘、腕偏航、腕滚转均为 0 rad；左腕俯仰约 1.435806 rad，右腕俯仰 1.5 rad。这些是 CAD 角度，不是要直接发送给电机的 LeRobot 度数。

## 3. 采集本机 Home 映射

```bash
python -m lerobot.vr_gateway.calibration.sync_arm_mapping
```

确认姿态后按提示输入 `CAPTURE FOLDED HOME`。脚本只读双臂串口，对照 EEPROM 与当前 JSON，采集 10 组位置并拒绝抖动超限的结果。它不会改变扭矩或 EEPROM。输出目录默认为：

```text
~/.config/lerobot/alohamini/arm_mapping/
  AlohaMiniRobot.json
  hardware_joint_map_left.yaml
  hardware_joint_map_right.yaml
```

已有且几何已确认的本机 Home 文件，若电机标定和机械安装未改变，可直接复用。需要重采时，如果目录已存在，使用新的 `--output-dir`，避免覆盖先前记录。网关启动时通过 `--arm-mapping-dir` 选择新目录。`--calibration-json` 可指定其他电机 JSON；运行时该 JSON 必须与机器人实际加载的标定一致。

保留了可选的 `--host` / `--ssh-target` 读取现有 LeRobot Host 的功能；它只依赖 Python ZMQ，也不依赖 ROS。默认串口流程不需要 Host。

## 4. 只读核对零点与运动学

保持 Home，再读取一次并生成对照图：

```bash
python -m lerobot.vr_gateway.calibration.verify_arm_mapping \
  --arm-ik-mode legacy --read-hardware --expect-home --output-dir /tmp/alohamini_home_check
```

检查 `/tmp/alohamini_home_check/arm_reference.svg` 和 `report.json`。命令检查完整行程的编码器/URDF 双向转换，并要求实测姿态距离本次 Home 参考不超过 2°。

随后可在扭矩关闭时手动小幅改变单个关节，去掉 `--expect-home` 再运行同一命令。对照实物与图中的上臂、前臂和腕部方向，逐侧确认变化方向一致。串口读数和数值测试只能验证转换一致性，不能自动确认实物几何或碰撞间隙。

## 5. 启动 VR

```bash
python -m lerobot.vr_gateway.server \
  --robot-model alohamini2pro --arm-ik-mode legacy --host 0.0.0.0 --port 8000 \
  --diagnostics true
```

启动会验证 Home 文件是否与当前电机标定匹配，连接硬件时也会检查 EEPROM；不匹配时拒绝继续，不会自动回写旧标定。握持手柄时从当前实测姿态开始跟随，不会自动回到折叠 Home。

首次使用新映射时分别低速确认前移、上移和腕部旋转，再逐步增加伸展幅度。现有的速度、状态领先量和电流保护仍然有效。

## 接入 VR 的变化

- 左右臂分别使用 `reference_tick`、`reference_q_rad`、`sign` 和编码器传动比，保留 4095/4096 的单位区别及周期分支处理。
- 当前电机行程转换为 URDF 限位，同时进入 Placo 模型和输出保护。
- legacy 保留原 CAD 基准、Moving_Jaw 末端和 swing/twist 手势；正确零位下取消旧的平移前后反向补偿。
- legacy 保留 0.5 位移倍率、原速度与 IK 权重。本次仅接入机械参考及必要的方向修正；剩余伸展误差见 [离线验证记录](vr_legacy_home.md)。
- `verify_arm_mapping --arm-ik-mode legacy` 默认显示实际使用的 legacy 模型；显式传入另一模式仍可检查对应的标准基座/TCP。

URDF 连杆尺寸和轴线仍来自 ROS2 的 CAD 导出，原项目标记为 `cad_export_unverified`。移植完成不等于已完成当前实机的几何精度与完整工作空间验证。
