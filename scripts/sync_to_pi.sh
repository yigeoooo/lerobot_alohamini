#!/usr/bin/env bash
# 把本地 lerobot_alohamini 仓库的指定路径同步到树莓派上的同名路径（用 rsync over ssh）。
#
# 用法:
#   ./scripts/sync_to_pi.sh                          # 只同步下面 DEFAULT_PATHS 里列出的 VR gateway 相关文件
#   ./scripts/sync_to_pi.sh <path> [<path> ...]      # 同步指定的文件/目录（相对仓库根目录）
#   ./scripts/sync_to_pi.sh --dry-run                # 预览会同步哪些文件，不真的传输
#
# 例子:
#   ./scripts/sync_to_pi.sh src/lerobot/vr_gateway tests/vr_gateway
#   PI_SSH_PASS=your_password ./scripts/sync_to_pi.sh --dry-run
#
# 环境变量（都可以不设，用默认值）:
#   PI_HOST      树莓派 IP，默认 192.168.10.101
#   PI_USER      SSH 用户名，默认 nkn83e
#   PI_PATH      树莓派上仓库根目录，默认 ~/lerobot_alohamini
#   PI_SSH_PASS  可选：SSH 密码。设置后用 sshpass 免交互登录（需要本机装了 sshpass）。
#                不设置时 ssh/rsync 会照常交互式提示输入密码 —— 更安全，配好 SSH key 后可完全免密。
#
# 说明:
#   - 默认不加 --delete，只会新增/覆盖文件，不会删除树莓派上多出来的文件，避免误删对方本地的
#     调试文件或未提交的改动。需要镜像删除时显式加 --delete。
#   - 树莓派上的仓库可能有它自己的未提交修改（比如硬件相关配置），所以默认只同步 VR gateway
#     相关路径，而不是整个仓库；要同步别的路径显式传进来即可。

set -euo pipefail

PI_HOST="${PI_HOST:-192.168.10.101}"
PI_USER="${PI_USER:-pi5}"
PI_PATH="${PI_PATH:-~/lerobot_alohamini}"

# 没传路径参数时，默认同步这次 VR 摇操坐标系修复涉及的文件。
DEFAULT_PATHS=(
  "vr_gateway"
  "src/lerobot/vr_gateway"
  "tests/vr_gateway"
  "tests/test_vr_gateway.py"
  "docs/alohamini/vr_gateway.md"
  "docs/alohamini/vr_ik_development.md"
)

LOCAL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

DRY_RUN=()
DELETE=()
paths=()
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=(-n) ;;
    --delete) DELETE=(--delete) ;;
    *) paths+=("$arg") ;;
  esac
done
if [ ${#paths[@]} -eq 0 ]; then
  paths=("${DEFAULT_PATHS[@]}")
fi

SSH_CMD="ssh -o StrictHostKeyChecking=accept-new"
if [ -n "${PI_SSH_PASS:-}" ]; then
  if ! command -v sshpass >/dev/null 2>&1; then
    echo "错误: 设置了 PI_SSH_PASS 但本机没装 sshpass。brew install sshpass 或者不设 PI_SSH_PASS 走交互式密码输入。" >&2
    exit 1
  fi
  export SSHPASS="$PI_SSH_PASS"
  SSH_CMD="sshpass -e $SSH_CMD"
fi

echo "同步目标: ${PI_USER}@${PI_HOST}:${PI_PATH}"

for rel in "${paths[@]}"; do
  src="$LOCAL_ROOT/$rel"
  if [ ! -e "$src" ]; then
    echo "跳过: $rel（本地不存在）" >&2
    continue
  fi

  remote_parent="$PI_PATH/$(dirname "$rel")"
  # dirname("foo") -> "." 时，目标父目录就是仓库根目录本身。
  [ "$(dirname "$rel")" = "." ] && remote_parent="$PI_PATH"

  echo "==> ${rel}"
  # 远端父目录不存在时先建好，rsync 不会自动帮你 mkdir -p。
  $SSH_CMD "${PI_USER}@${PI_HOST}" "mkdir -p '${remote_parent}'"

  if [ -d "$src" ]; then
    src="${src}/"
    remote_dst="${remote_parent}/$(basename "$rel")/"
  else
    remote_dst="${remote_parent}/"
  fi

  rsync -avz "${DRY_RUN[@]}" "${DELETE[@]}" \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    -e "$SSH_CMD" \
    "$src" "${PI_USER}@${PI_HOST}:${remote_dst}"
done

echo "完成。"
