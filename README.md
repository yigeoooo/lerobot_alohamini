## Updates
- **[2025-4-10]** Compatible with LeRobot 0.5.2 Release


## Introduction

Compared to the original lerobot, lerobot_alohamini significantly enhances debugging capabilities and is adapted for AlohaMini wheeled dual-arm robot hardware (based on Lekiwi extension).

For newly added debugging commands, please refer to:
[Debug Command Summary](examples/debug/README.md)

AlohaMini Hardware 
![alohamini concept](examples/alohamini/media/alohamini3a.png)  

## System Architecture

AlohaMini runs as a **two-machine setup**:

```
┌─────────────────────────────┐        LAN        ┌──────────────────────────────────┐
│          PC (Client)        │ ◄───────────────► │     Raspberry Pi (Host)          │
│                             │                   │                                  │
│  • Leader arms (USB)        │                   │  • Follower arms (USB)           │
│  • teleoperate_bi.py        │                   │  • Base wheels + lift axis (USB) │
│  • record_bi.py             │                   │  • Cameras (USB)                 │
│  • Training / Evaluation    │                   │  • lekiwi_host.py                │
└─────────────────────────────┘                   └──────────────────────────────────┘
```

Both machines must be on the same LAN. Install the full environment on both.


## Getting Started (Ubuntu System)

*** Highly recommended to follow the sequence ***

### 1. Preparation

#### Network Environment Test
```
curl https://www.google.com
curl https://huggingface.co
```
First ensure network connectivity

#### CUDA Environment Test
```
nvidia-smi
```
After entering in terminal, you should be able to see the CUDA version number


### 2. Clone lerobot_alohamini Repository

```
cd ~
git clone https://github.com/liyiteng/lerobot_alohamini.git
```

### 3. Serial Port Authorization
By default, serial ports cannot be accessed. We need to authorize the ports. The lerobot official documentation example modifies serial port permissions to 666, but in practice, this needs to be reset after each computer restart, which is very troublesome. It's recommended to directly add the current user to the device user group for a permanent solution.
1. Enter `whoami` in terminal  — check current username
2. Enter `sudo usermod -a -G dialout username`  — permanently add username to device user group
3. Restart computer to make permissions effective

### 4. Install conda3 and Environment Dependencies

Install conda3 
```
mkdir -p ~/miniconda3
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O ~/miniconda3/miniconda.sh
bash ~/miniconda3/miniconda.sh -b -u -p ~/miniconda3
rm ~/miniconda3/miniconda.sh
~/miniconda3/bin/conda init bash
source ~/.bashrc
```



Initialize conda3
```
conda create -y -n lerobot_alohamini python=3.12
conda activate lerobot_alohamini
```

Install environment dependencies
```
cd ~/lerobot_alohamini
pip install -e .[all]
pip install pyzmq
pip install feetech-servo-sdk
conda install ffmpeg=7.1.1 -c conda-forge
```


Note:If installing on Raspberry Pi, make sure to use an ARM-specific conda distribution.

（Optional）conda3 ARM build
```
wget https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-aarch64.sh \
-O ~/miniforge3/miniforge.sh
```
### 5. Configure Robot Arm Port Numbers


AlohaMini has 4 robot arms in total: 2 leader arms connected to the PC, 2 follower arms connected to Raspberry Pi, totaling 4 ports.

Since port numbers change every time you reconnect, you must master the operation of finding port numbers. After becoming proficient, you can use hard links for port fixation.

If you purchased the complete AlohaMini machine, the Raspberry Pi that comes with it has already fixed the port numbers for the 2 follower arms, so no additional configuration is needed.


Connect the robot arms to power and to the computer via USB, then find the robot arm port numbers.

Method 1:
Find ports through script:
```
cd ~/lerobot_alohamini

lerobot-find-port
```

Method 2:
You can directly enter commands in terminal and confirm the inserted port numbers by observing the different port numbers displayed after each insertion

```
ls /dev/ttyACM*
```

**After finding the correct ports, update the port fields in the following files:**

Follower arms — edit `src/lerobot/robots/alohamini/config_lekiwi.py`:
```python
@dataclass
class LeKiwiConfig(RobotConfig):
    left_port:  str = "/dev/ttyACM0"   # ← replace with your left-bus port
    right_port: str = "/dev/ttyACM1"   # ← replace with your right-bus port
```

Leader arms — edit `examples/alohamini/teleoperate_bi.py`:
```python
left_arm_config  = SOLeaderConfig(port="/dev/ttyACM2", ...)   # ← replace
right_arm_config = SOLeaderConfig(port="/dev/ttyACM3", ...)   # ← replace
```

Note: This operation must be performed every time you reconnect the robot arms or restart the computer

### 6. Configure Camera Port Numbers

Use `lerobot-find-cameras` to discover available cameras.
This identifier may change after rebooting your computer or re-plugging the camera, depending largely on your operating system.

Then, fill the detected camera port index into `lerobot/robots/alohamini/config_lekiwi.py`.

Note:
- Multiple cameras cannot be plugged into one USB Hub; 1 USB Hub only supports 1 camera


### 7. Teleoperation Calibration and Testing


#### 7.1 Set Robot Arm to Middle Position

Host-side calibration:
SSH into the Raspberry Pi, install the conda environment, then perform the following operations:

> `--robot_model` is the single parameter that drives everything on the host side — arm DOF, all motor models, lift motor, and lead-screw pitch. Choose the one that matches your hardware:
>
> | `--robot_model`  | Arm           | Arm motors          | Base wheels | Lift motor | Lead screw  |
> |------------------|---------------|---------------------|-------------|------------|-------------|
> | `alohamini1`     | SO-ARM 5-DoF  | all sts3215         | sts3215 ×3  | sts3215    | 84 mm/rev   |
> | `alohamini2`     | AM-ARM 6-DoF  | sts3215 + sts3095   | sts3215 ×3  | sts3095    | 131 mm/rev  |
> | `alohamini2pro`  | AM-ARM 6-DoF  | sts3250 + sts3095   | sts3250 ×3  | sts3095    | 131 mm/rev  |

##### AlohaMini 1 (SO‑ARM 5‑DoF)

``` bash
python -m lerobot.robots.alohamini.lekiwi_host \
  --robot_model alohamini1
```

##### AlohaMini 2 (AM‑ARM 6‑DoF)

``` bash
python -m lerobot.robots.alohamini.lekiwi_host \
  --robot_model alohamini2
```

##### AlohaMini 2 Pro (AM‑ARM 6‑DoF, sts3250 upgrade)

``` bash
python -m lerobot.robots.alohamini.lekiwi_host \
  --robot_model alohamini2pro
```

If executing for the first time, the system will prompt you to calibrate the robot arm. Follow the on-screen instructions: position the arm to its middle pose, press Enter, rotate each joint 90° left, press Enter, rotate 90° right, press Enter.

**SO-ARM 5-DoF** — reference middle position:
![Calibration SO-ARM](examples/alohamini/media/mid_position_so100.png)

**AM-ARM 6-DoF** — same procedure applies; position each joint at its mechanical midpoint before starting.


Client-side calibration (calibrates the **leader arms** on the PC):
Replace the IP with the actual IP of your Raspberry Pi, then repeat the calibration steps above for each leader arm.

> `--arm_profile` here refers to your **leader arm** hardware (not the follower robot).  
> Use `so-arm-5dof` if your leader arms are SO-ARM 5-DoF; use `am-arm-6dof` if they are AM-ARM 6-DoF.

SO-ARM leader (5-DoF):
```bash
python examples/alohamini/teleoperate_bi.py \
  --remote_ip <Pi_IP> \
  --leader_id so101_leader_bi \
  --arm_profile so-arm-5dof
```

AM-ARM leader (6-DoF):
```bash
python examples/alohamini/teleoperate_bi.py \
  --remote_ip <Pi_IP> \
  --leader_id so101_leader_bi \
  --arm_profile am-arm-6dof
```

Note: After calibration, you need to power off the robotic arm once for the changes to take effect, for both the leader arms and the follower arms.

#### 7.2 Teleoperation Command Summary

Raspberry Pi side (pick the command that matches your robot):

``` bash
# AlohaMini 1 (SO-ARM 5-DoF)
python -m lerobot.robots.alohamini.lekiwi_host --robot_model alohamini1

# AlohaMini 2 (AM-ARM 6-DoF)
python -m lerobot.robots.alohamini.lekiwi_host --robot_model alohamini2

# AlohaMini 2 Pro (AM-ARM 6-DoF, sts3250 upgrade)
python -m lerobot.robots.alohamini.lekiwi_host --robot_model alohamini2pro
```

PC side (`--arm_profile` here refers to the **leader arm** hardware, not the follower robot):

##### SO‑ARM leader (5‑DoF)

``` 
python examples/alohamini/teleoperate_bi.py \
  --remote_ip 192.168.50.43 \
  --leader_id so101_leader_bi \
  --arm_profile so-arm-5dof
```

##### AM‑ARM leader (6‑DoF)

``` 
python examples/alohamini/teleoperate_bi.py \
  --remote_ip 192.168.50.43 \
  --leader_id so101_leader_bi \
  --arm_profile am-arm-6dof
```

### 8. Record Dataset

#### 1 Register on HuggingFace, Obtain and Configure Key

1. Go to HuggingFace website (huggingface.co), apply for {Key}, remember to include read and write permissions

2. Add API token to Git credentials

```
git config --global credential.helper store

huggingface-cli login --token {key} --add-to-git-credential

```

#### 2 Run Script

Modify the repo-id parameter, then execute:

```
HF_USER=$(huggingface-cli whoami | head -n 1)
echo $HF_USER

```

> **Before recording**, make sure the Raspberry Pi host is already running with the correct `--robot_model` (see §7.2).  
> The `--arm_profile` below refers to your **leader arm** hardware, not the follower robot.  
> Replace `<Pi_IP>` with your Raspberry Pi's IP address (use `127.0.0.1` only if the Pi and PC are the same machine).

##### AlohaMini 1 — SO-ARM leader (5-DoF):

Create New Dataset:
```bash
python examples/alohamini/record_bi.py \
  --dataset $HF_USER/so100_bi_test \
  --num_episodes 1 \
  --fps 30 \
  --episode_time 45 \
  --reset_time 8 \
  --task_description "pickup1" \
  --remote_ip <Pi_IP> \
  --leader_id so101_leader_bi \
  --arm_profile so-arm-5dof
```

Resume Dataset:
```bash
python examples/alohamini/record_bi.py \
  --dataset $HF_USER/so100_bi_test \
  --num_episodes 1 \
  --fps 30 \
  --episode_time 45 \
  --reset_time 8 \
  --task_description "pickup1" \
  --remote_ip <Pi_IP> \
  --leader_id so101_leader_bi \
  --arm_profile so-arm-5dof \
  --resume
```

##### AlohaMini 2 / 2 Pro — AM-ARM leader (6-DoF):

Create New Dataset:
```bash
python examples/alohamini/record_bi.py \
  --dataset $HF_USER/so100_bi_test \
  --num_episodes 1 \
  --fps 30 \
  --episode_time 45 \
  --reset_time 8 \
  --task_description "pickup1" \
  --remote_ip <Pi_IP> \
  --leader_id so101_leader_bi \
  --arm_profile am-arm-6dof
```

Resume Dataset:
```bash
python examples/alohamini/record_bi.py \
  --dataset $HF_USER/so100_bi_test \
  --num_episodes 1 \
  --fps 30 \
  --episode_time 45 \
  --reset_time 8 \
  --task_description "pickup1" \
  --remote_ip <Pi_IP> \
  --leader_id so101_leader_bi \
  --arm_profile am-arm-6dof \
  --resume
```


### 9. Replay Dataset
```bash
python examples/alohamini/replay_bi.py \
  --dataset $HF_USER/so100_bi_test \
  --episode 0 \
  --remote_ip <Pi_IP>
```

### 10. Dataset Visualization
```
  lerobot-dataset-viz \
  --repo-id $HF_USER/so100_bi_test \
  --episode-index 0 \
  --display-compressed-images

```

### 11. Local Training

ACT policy:
```bash
lerobot-train \
  --dataset.repo_id=$HF_USER/so100_bi_test \
  --policy.type=act \
  --output_dir=outputs/train/act_your_dataset1 \
  --job_name=act_your_dataset \
  --policy.device=cuda \
  --wandb.enable=false \
  --policy.repo_id=$HF_USER/act_policy
```


### 12. Remote Training
Using AutoDL as an example:
Apply for an RTX 4070 GPU, select Python 3.12 (Ubuntu 22.04) CUDA 11.8 or above as container image, and log in via terminal

```bash
# Initialize conda (first login only)
conda init
# Restart terminal, then create environment
conda create -y -n lerobot_alohamini python=3.12
conda activate lerobot_alohamini

# Academic acceleration (AutoDL-specific)
source /etc/network_turbo

# Get lerobot
git clone https://github.com/liyiteng/lerobot_alohamini.git

# Install dependencies
cd ~/lerobot_alohamini
pip install -e ".[all]"
conda install ffmpeg=7.1.1 -c conda-forge
```

Run training (same command as local training, GPU is used by default):

```bash
lerobot-train \
  --dataset.repo_id=$HF_USER/so100_bi_test \
  --policy.type=act \
  --output_dir=outputs/train/act_your_dataset1 \
  --job_name=act_your_dataset \
  --policy.device=cuda \
  --wandb.enable=false \
  --policy.repo_id=$HF_USER/act_policy
```

Finally install FileZilla to retrieve the trained files:
```bash
sudo apt install filezilla -y
```

### 13. Evaluate Training Set

Use FileZilla to copy the trained model to local machine, then run the following command:

```bash
python examples/alohamini/evaluate_bi.py \
  --num_episodes 3 \
  --fps 20 \
  --episode_time 45 \
  --task_description "Pick and place task" \
  --hf_model_id ./outputs/train/act_your_dataset1/checkpoints/020000/pretrained_model \
  --hf_dataset_id $HF_USER/eval_dataset \
  --remote_ip <Pi_IP> \
  --robot_id my_alohamini
```