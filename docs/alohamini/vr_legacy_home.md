# Legacy 接入 Folded Home：修改与离线验证

日期：2026-09-17。操作步骤见 [VR 上线与操作记录](vr_gateway.md#首次使用folded-home-零位流程)，采集工具详见 [零点确认](vr_calibration.md)。

## 修改后的行为

默认 `--arm-ik-mode legacy` 现在读取本机 Folded Home 文件，通过已有 `ArmMapping` 把电机位置转换到原 CAD 关节角度；相同转换用于反向命令和左右臂的关节上下限。缺失或与当前标定不匹配的映射会在硬件连接前报错，不会静默退回行程中点零位。

仍使用 `LegacyArmIK`、原 `alohamini2pro.urdf`、Moving_Jaw 末端和 swing/twist 手势。保留 0.5 位移倍率、Goal_Velocity=2000、位置/朝向权重 1/1、posture_weight=5e-4、现有速度与实测领先保护。握住 Grip 从当前位置锚定，不自动回 Home。夹爪继续使用原 RANGE_0_100 开合端点；加载 Home 不会改变模式识别或夹爪端点。

零位修正后，原先针对错误模型增加的前后反向补偿会把前伸送往 CAD +Y，即机身后方。因此同步去掉该补偿，保留原 CAD 基准，前移手柄对应 CAD −Y；三个头部对齐角度（0°、45°、−90°）下的前/右/上及旋转目标都有回归。

Home 参考图工具增加 `--arm-ik-mode legacy`（默认），直接检查运行中的原 CAD 链和 Moving_Jaw，图形统一转到机身前/左/上坐标便于实物对照。参考姿态、只读采集、复用条件、全行程转换核验、启动命令和新版页面标记 `home6` 已写入运行文档。

## 对照方法

`tests/vr_gateway/benchmark_legacy_home.py` 完全离线，不创建机器人或串口对象：

1. `before_home` 在探针内重建修改前的行程中点映射与限位，调用相同的 LegacyArmIK 手势和求解逻辑。
2. `home_only` 通过生产工厂加载 Home，暂时保留旧前后补偿，隔离零位变化。
3. `legacy_home` 使用最终生产默认，即 Home 加正确平移方向。

每组使用相同的电机标定、对应 Home 模型及合成起点，25 Hz、150 帧渐进、50 帧保持。被测侧起始 CAD 角度为 `[0, -95, 95, 0, 0, 0]°`，经映射后才成为电机命令；这是合成姿态，不是本次现场读数。反馈按命令理想执行，所有输出都检查原电机编码器行程。

对于已知可达伸展路径，由独立 FK 模型生成肩、肘协同的完整末端位姿，再反算手柄输入，经过真实工厂和 `update()` 求解。起终点均在对应映射的关节范围内。三种方案的末端误差都用同一个 Home 绑定的 FK 模型计算，避免用错误零位的模型给自己评分。该模型仍来自 CAD，结果不是实物精度测量。

对于只平移手柄的测试，固定手柄朝向，分别上移或前移 0.4 m，对应目标移动 0.2 m；水平转柄测试为原地 ±90°。这些位姿要求不预先保证可达，用来观察剩余约束与限位。

## 已知可达路径的结果

先使用仓库内成套归档标定/Home 夹具：

| 目标 | 修改前左/右误差 | 接入后左/右误差 |
| --- | ---: | ---: |
| 前伸完整位姿 | 319.15 / 314.66 mm | 12.73 / 12.72 mm |
| 上伸完整位姿 | 48.18 / 45.66 mm | 6.49 / 6.54 mm |

随后只读下载树莓派已有的 `~/.config/lerobot/alohamini/arm_mapping/`，与本轮下载的当前 `AlohaMiniRobot.json` 校验一致，并通过 101 个全行程采样点的双向转换检查。使用该组文件重新回放：

| 目标 | 修改前左/右误差 | 接入后左/右误差 |
| --- | ---: | ---: |
| 前伸完整位姿 | 310.14 / 320.78 mm | 12.73 / 12.72 mm |
| 上伸完整位姿 | 36.78 / 59.44 mm | 6.49 / 6.54 mm |

这四条接入后路径没有触发关节限位，末端朝向误差小于 0.06°。零位改动显著降低模型跟踪误差，但默认肩肘偏好仍使前伸终点大小臂折角约 **32.29°**、上伸约 **22.98°**（0°表示两段伸直），不能宣称已完全伸直。

树莓派文件采集于 `2026-09-15T09:24:51.711744+00:00`，仍标记 `home_captured_requires_physical_geometry_check`。它与电机文件匹配不等于真实摆放姿态已经确认；没有据此修改其状态或宣称实机零位正确。

## 用户手势与剩余问题

- 只上移手柄 0.4 m、保持朝向：Pi 文件回放末端位置误差从左右约 135/144 mm 降到 74 mm；最终未触发关节限位，但仍不能满足全部位姿目标。
- 只前移手柄 0.4 m、保持朝向：补齐 Home 但保留旧反向补偿时，目标朝后、误差约 391 mm；去掉补偿后误差约 133 mm。该测试没有保证位置与固定朝向的组合可达，不能用此数值作为机器人标定精度。
- 原地水平转柄 ±90°：仍然生成末端朝向目标；Pi 文件下肩部相对变化约 −1.23°～+4.22°，部分路径触发 wrist_yaw 限位。**本次没有实现“转柄角度直接对应肩部角度”。**

只在额外离线实例中把 posture_weight 从 `5e-4` 改成 `1e-6`，其余与最终 legacy 相同：已知前伸/上伸路径的误差降到 **0.281–0.336 mm**，大小臂折角缩小到约 **3.73–4.70°**。这说明剩余伸展误差受姿态偏好影响；该参数没有写入默认运行配置，也没有通过实机分支连续性/负载验证。

下一步可独立处理姿态优先级和肩部转柄语义。Home 接入解决了模型参考与限位的问题，不承诺单独解决所有手势下的可达性。

## 验证命令与结果

开发环境优先使用 `uv run`；当前已有 Conda 环境含 Placo，实际执行使用：

```bash
PYTHONPATH=src UV_CACHE_DIR=/tmp/lerobot-vr-read-cache \
uv run --no-project --python /home/yigeoooo/miniconda3/envs/lerobot_alohamini/bin/python \
  python -m pytest tests/vr_gateway --ignore=tests/vr_gateway/test -q -k 'not websocket'
```

结果：122 项通过。另单独运行 WebSocket 重连测试通过（沙箱外使用假机器人），共 123 项 Python 回归。嵌套 `tests/vr_gateway/test/` 为已有旧版测试副本，不纳入本轮现行套件。

```bash
node tests/vr_gateway/test_frontend.cjs
```

结果：10 项通过。修改文件的 Ruff 与 `git diff --check` 通过。测试环境退出时已有 `multiprocess.ResourceTracker` 析构警告，pytest 返回 0；未修改环境包来掩盖该警告。

运行离线对照：

```bash
# 标准项目环境
uv run python tests/vr_gateway/benchmark_legacy_home.py \
  --output /tmp/legacy_home_replay.json

# 使用本机已采集文件，同样不访问硬件
uv run python tests/vr_gateway/benchmark_legacy_home.py \
  --arm-mapping-dir ~/.config/lerobot/alohamini/arm_mapping \
  --calibration-json ~/.cache/huggingface/lerobot/calibration/robots/alohamini/AlohaMiniRobot.json \
  --output /tmp/legacy_home_machine_replay.json
```

本轮原始结果在开发机 `/tmp/lerobot_legacy_home/`：`replay.json` 为归档夹具，`pi_replay.json` 为 Pi 文件回放，`weak_posture_probe.json` 为额外权重对照，`reference/` 为 legacy Home 图，`pi_check/` 为文件数值核验报告。

实现与离线验证阶段未启动硬件网关、未发送运动命令，也未重采/覆盖机器标定文件。

## 树莓派同步与本机文件复核（2026-09-17）

按用户要求，代码、测试和操作文档共 18 个文件已同步到 `pi5@192.168.10.89:~/lerobot_alohamini`。原文件备份在 `/home/pi5/lerobot_vr_before_home6_7viwm49w/before.tar.gz`，备份目录包含原先不存在的新文件清单。同步后逐文件校验 SHA-256；保留树莓派已有的 Home 和电机标定文件。

树莓派环境缺少 SciPy，离线回放脚本已去除该依赖，使用 NumPy 和现有几何函数；本机重新通过 9 项 Home 回归。树莓派使用其当前 Python/Placo 环境完成 36 组对照回放，前述 Pi 文件的误差结果在显示的 0.01 mm 精度内一致。

零位检查结果：

- `~/.config/lerobot/alohamini/arm_mapping/` 下左右 YAML 及 `AlohaMiniRobot.json` 均存在，并与当前机器人标定 JSON 匹配；新版 legacy 加载成功。
- 双臂 Home 编码器值转换到模型参考角的误差均为 0°。
- 101 个全行程采样点的最大往返转换误差均约 0.043945°，为半个编码器刻度的数值取整误差，不能视作实物零位精度。
- 文件仍标记 `home_captured_requires_physical_geometry_check`。没有把数值检查结果写成实物已验证。
- 串口设备存在且没有进程占用，但两次只读查询均未收到左臂 ID 1–7 的响应，流程在左臂握手时退出。因此本次没有读到实时 EEPROM/姿态，也没有验证右臂硬件；不能据此确认当前硬件与文件一致或评价实物 Home 误差。需检查电机供电/急停状态和总线连接后，再执行运行文档中的只读核对。

远端报告位于 `/tmp/lerobot_home_deploy/zero_check.json`、`pi_replay.json`、`numerical_check/report.json`。本次未启动网关或执行运动。
