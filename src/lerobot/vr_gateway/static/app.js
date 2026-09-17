(() => {
  'use strict';

  const CONTROL_PERIOD_MS = 40;
  const BASE_KEEPALIVE_MS = 400;
  const CONTROLLER_DIAG_MS = 250;
  const AXIS_DEAD_ZONE = 0.15;
  const BASE_LINEAR_SCALE = 0.30;
  const BASE_ANGULAR_SCALE = 60;
  const LIFT_JOG_VELOCITY = 1300;
  const $ = (id) => document.getElementById(id);
  const status = $('status');
  const image = $('view');
  const scene = document.querySelector('a-scene');
  const inputHistory = [];
  let ws;
  let health = null;
  let healthAt = 0;
  let cameraAt = 0;
  let videoRotation = 0;
  let limitWarning = '';
  let xrSession = null;
  let headPose = null;
  let headPoseAt = 0;
  let lastControlSend = 0;
  let lastBaseSent = null;
  let lastBaseSentAt = 0;
  let lastDiagSend = 0;
  let buttonSignature = '';
  let prevA = false;
  let prevB = false;
  let prevY = false;
  let liftCommand = 0;
  let lastLiftSend = 0;
  const hands = Object.fromEntries(['left', 'right'].map((side) => [side, {
    pose: null, active: false, grip: false, epoch: 0, trigger: null, triggerArmed: false, source: null,
  }]));

  function logInput(message) {
    console.info(`[VR] ${message}`);
    inputHistory.push(`${new Date().toLocaleTimeString()} ${message}`);
    if (inputHistory.length > 8) inputHistory.shift();
    $('input-log').textContent = inputHistory.join('\n');
  }

  function send(message) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify(message));
    return true;
  }

  function showDisconnected(text) {
    health = null;
    showLimitWarnings([]);
    status.textContent = text;
    for (const side of ['left', 'right']) {
      $(`${side}-state`).textContent = '状态未知';
      $(`${side}-state`).dataset.following = 'false';
      $(`${side}-detail`).textContent = '连接未知 · 力矩未知';
    }
    $('feedback-state').textContent = '反馈不可用';
    $('mapping-state').textContent = '标定待检查';
    drawHUD();
  }

  function showLimitWarnings(warnings) {
    const names = { shoulder_pan: '肩部转向', shoulder_lift: '肩部抬升', elbow_flex: '肘关节',
      wrist_flex: '腕俯仰', wrist_yaw: '腕偏航', wrist_roll: '腕滚转' };
    const groups = ['left', 'right'].map((side) => {
      const joints = warnings.filter((warning) => warning.side === side).map((warning) => names[warning.joint] || warning.joint);
      return joints.length ? `${side === 'left' ? '左臂' : '右臂'} ${joints.join('、')}` : '';
    }).filter(Boolean);
    const next = groups.length ? `限位警告：${groups.join('；')}` : '';
    if (next && next !== limitWarning) logInput(next);
    limitWarning = next;
    $('limit-warning').textContent = next;
    $('limit-warning').hidden = !next;
    $('limit-plane').setAttribute('visible', !!next);
    const canvas = $('limit-texture');
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (next) {
      ctx.fillStyle = '#713f12';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = '#fff7d6';
      ctx.font = 'bold 36px sans-serif';
      ctx.fillText('限位警告', 24, 42);
      ctx.font = '28px sans-serif';
      groups.forEach((text, index) => ctx.fillText(text, 24, 86 + index * 38, 976));
    }
    dirtyTexture('limit-plane');
  }

  function reportStatus(message) {
    health = message;
    healthAt = performance.now();
    showLimitWarnings(message.feedback_fresh ? message.joint_limit_warnings || [] : []);
    const torque = { enabled: '力矩已使能', disabled: '力矩未使能', mixed: '部分力矩使能', unknown: '力矩未知' };
    const reason = {
      tracking_lost: '追踪丢失，请松开再握持', stale_pose: '输入过期，请松开再握持',
      stale_feedback: '反馈过期，请松开再握持', input_or_feedback_timeout: '输入或反馈超时，请松开再握持',
      new_connection: '请松开 Grip 后开始', disconnected: '请松开再握持',
      watchdog: '通信超时，请松开再握持', paused: '已暂停，请松开再握持', estop: '急停后请松开再握持',
    };
    status.textContent = message.estop ? '急停中' : message.arm_frozen ? '跟随已暂停' :
      message.robot_connected ? '机器人已连接' : '机器人未连接';
    $('clutch').textContent = message.arm_frozen ? '恢复跟随' : '暂停跟随';
    for (const side of ['left', 'right']) {
      const arm = message.arms?.[side];
      const following = arm?.state === 'following' && !message.estop && !message.arm_frozen;
      $(`${side}-state`).textContent = following ? '跟随中' : '保持';
      $(`${side}-state`).dataset.following = String(following);
      $(`${side}-detail`).textContent = `${arm?.connected ? '已连接' : '未连接'} · ${torque[arm?.torque] || torque.unknown}` +
        (arm?.reason ? ` · ${reason[arm.reason] || arm.reason}` : '');
    }
    $('mapping-state').textContent = message.arm_ik_mode === 'legacy'
      ? (message.arm_mapping_loaded ? 'Legacy · Home 零位已加载' : 'Legacy · 缺少 Home 零位')
      : (message.arm_mapping_loaded ? '机械标定已加载' : '机械标定不可用');
    $('feedback-state').textContent = message.feedback_fresh ? `反馈 ${Math.round(message.feedback_age_ms)} ms` : '反馈过期';
    $('diagnostics').textContent = `IK ${message.ik_available ? '可用' : '不可用'} · 已发送 ${message.actions_sent} · ` +
      `拒绝 ${message.ik_rejected} · 过期 ${message.poses_stale} · 总线 ${message.action_ms} ms · 控制 ${message.control_hz_actual ?? '—'} Hz · 页面 home6`;
    $('tcp-info').textContent = `TCP: ${Object.values(message.tcp_frames || {}).join(' / ') || '未知'}`;
    drawHUD();
  }

  function connect() {
    ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
    ws.onopen = () => {
      lastBaseSent = null;
      for (const hand of Object.values(hands)) { hand.epoch++; hand.trigger = null; hand.triggerArmed = false; }
      status.textContent = '网关已连接，等待机器人状态';
      send({ type: 'hello', client: 'webxr', protocol: 3 });
    };
    ws.onclose = (event) => {
      showDisconnected(event.code === 1008 ? '已有其他操作员连接' : '网关连接已断开');
      if (event.code !== 1008) setTimeout(connect, 1000);
    };
    ws.onerror = () => showDisconnected('网关连接错误');
    ws.onmessage = (event) => {
      let message;
      try { message = JSON.parse(event.data); } catch (_) { return; }
      if (message.jpeg_b64) image.src = 'data:image/jpeg;base64,' + message.jpeg_b64;
      if (message.type === 'status') reportStatus(message);
      if (message.type === 'error') { status.textContent = message.error; logInput(message.error); }
      if (message.type === 'ack' && (message.ignored || ['rejected', 'stale', 'ik_unavailable', 'unbound'].includes(message.status))) {
        const reason = message.reason === 'head_tracking_required' ? '请保持头部追踪并面向前方后握持' :
          message.ignored || message.reason || message.status;
        logInput(`指令未执行：${message.for} · ${reason}`);
      }
    };
  }

  // Base and lift mappings, units, dead zone and cadence match the existing gateway.
  function sendBase(xVel, yVel, thetaVel, force) {
    const now = performance.now();
    const changed = !lastBaseSent
      || Math.abs(lastBaseSent[0] - xVel) > 1e-4
      || Math.abs(lastBaseSent[1] - yVel) > 1e-4
      || Math.abs(lastBaseSent[2] - thetaVel) > 1e-4;
    if (!force && !changed && now - lastBaseSentAt < BASE_KEEPALIVE_MS) return;
    lastBaseSent = [xVel, yVel, thetaVel];
    lastBaseSentAt = now;
    send({ type: 'base', 'x.vel': xVel, 'y.vel': yVel, 'theta.vel': thetaVel });
  }

  const joy = $('joystick');
  const stick = joy.querySelector('.stick');
  let joyActive = false;
  function joyMove(ev) {
    if (!joyActive) return;
    const rect = joy.getBoundingClientRect();
    const x = Math.max(-1, Math.min(1, (ev.clientX - (rect.left + rect.width / 2)) / (rect.width / 2)));
    const y = Math.max(-1, Math.min(1, (ev.clientY - (rect.top + rect.height / 2)) / (rect.height / 2)));
    stick.style.transform = `translate(${x * 35}px,${y * 35}px)`;
    sendBase(-y * BASE_LINEAR_SCALE, -x * BASE_LINEAR_SCALE, 0);
  }
  joy.onpointerdown = (e) => { joyActive = true; joy.setPointerCapture(e.pointerId); joyMove(e); };
  joy.onpointermove = joyMove;
  joy.onpointerup = joy.onpointercancel = () => {
    joyActive = false;
    stick.style.transform = '';
    sendBase(0, 0, 0, true);
  };
  window.onkeydown = (e) => {
    const velocity = { w: [0.2, 0, 0], s: [-0.2, 0, 0], a: [0, 0, 0.8], d: [0, 0, -0.8] }[e.key.toLowerCase()];
    if (velocity && !e.repeat) sendBase(velocity[0], velocity[1], velocity[2], true);
  };
  window.onkeyup = (e) => {
    if ('wasd'.includes(e.key.toLowerCase())) sendBase(0, 0, 0, true);
  };
  $('lift').oninput = (e) => {
    $('lift-value').textContent = `${e.target.value} mm`;
    send({ type: 'lift', height_mm: Number(e.target.value) });
  };
  for (const side of ['left', 'right']) {
    $(`${side}-gripper`).oninput = (e) => send({ type: 'gripper', side, value: Number(e.target.value) });
  }
  $('estop').onclick = () => send({ type: 'estop', enabled: true });
  $('reset-estop').onclick = () => send({ type: 'estop', enabled: false });
  $('clutch').onclick = () => {
    if (health) send({ type: 'clutch', enabled: !health.arm_frozen });
  };
  $('reanchor').onclick = () => { send({ type: 'reanchor' }); logInput('已请求重建当前锚点'); };
  function align() {
    if (!headPose || performance.now() - headPoseAt > 120) {
      logInput('请在 VR 中面向操作方向后按 Y 对齐');
      return;
    }
    send({ type: 'align', head: headPose, client_time_ms: performance.timeOrigin + performance.now() });
    logInput('已请求朝向对齐并重建锚点');
  }
  $('align').onclick = align;
  $('settings').onclick = () => {
    $('position-scale').value = health?.arm_settings?.position_scale ?? 0.5;
    $('joint-speed').value = health?.arm_settings?.max_joint_speed_deg_s ?? 90;
    $('video-rotation').value = String(videoRotation);
    $('settings-dialog').showModal();
  };
  $('settings-close').onclick = () => $('settings-dialog').close();
  $('settings-form').onsubmit = (event) => {
    event.preventDefault();
    videoRotation = Number($('video-rotation').value) === 180 ? 180 : 0;
    drawVideo();
    if (send({ type: 'arm_settings', position_scale: Number($('position-scale').value),
      max_joint_speed_deg_s: Number($('joint-speed').value) })) $('settings-dialog').close();
  };

  function poseArray(p) {
    return { position: [p.position.x, p.position.y, p.position.z],
      orientation: [p.orientation.x, p.orientation.y, p.orientation.z, p.orientation.w] };
  }
  const pressed = (button, threshold = 0.2) => !!button && (button.pressed || Number(button.value || 0) >= threshold);
  function readHands(frame, refSpace) {
    for (const hand of Object.values(hands)) { hand.source = null; hand.pose = null; }
    for (const src of xrSession.inputSources) {
      const hand = hands[src.handedness];
      if (!hand) continue;
      hand.source = src;
      const pose = src.gripSpace && frame.getPose(src.gripSpace, refSpace);
      if (pose && !pose.emulatedPosition) hand.pose = poseArray(pose.transform);
    }
    let changed = false;
    for (const [side, hand] of Object.entries(hands)) {
      // A disconnected controller cannot prove that Grip was released.
      const grip = hand.source ? pressed(hand.source.gamepad?.buttons[1]) : hand.grip;
      const active = grip && !!hand.pose;
      if (hand.active !== active || hand.grip !== grip) { hand.epoch++; changed = true; }
      hand.grip = grip;
      hand.active = active;
      const model = $(`${side}-model`);
      model.object3D.visible = !!hand.pose;
      if (hand.pose) {
        model.object3D.position.fromArray(hand.pose.position);
        model.object3D.quaternion.fromArray(hand.pose.orientation);
      }
      model.querySelector('.grip-indicator').setAttribute('color', active ? '#49d1b0' : '#73849e');
      model.querySelector('.trigger-indicator').setAttribute('color', pressed(hand.source?.gamepad?.buttons[0]) ? '#f6b858' : '#73849e');
    }
    return changed;
  }
  function sendArmPose(t) {
    send({ type: 'arm_pose', client_time_ms: t + performance.timeOrigin,
      auto_align: true, head: headPose && t - headPoseAt <= 120 ? headPose : null,
      active: hands.left.grip || hands.right.grip,
      left_active: hands.left.grip, right_active: hands.right.grip,
      left_epoch: hands.left.epoch, right_epoch: hands.right.epoch,
      left: hands.left.pose, right: hands.right.pose });
    for (const [side, hand] of Object.entries(hands)) {
      const value = Number(hand.source?.gamepad?.buttons[0]?.value || 0);
      if (!hand.pose || !health?.feedback_fresh || health?.arm_frozen || health?.estop) {
        hand.trigger = null; hand.triggerArmed = false; continue;
      }
      // A tracked, released trigger means closed. Pressure opens the gripper;
      // transport values remain closure fractions for desktop/calibrated clients.
      if (hand.trigger !== null && Math.abs(value - hand.trigger) >= 0.01) {
        hand.triggerArmed = true;
        hand.trigger = value;
      } else if (hand.trigger === null) {
        hand.trigger = value;
        hand.triggerArmed = true;
      }
      // Repeat an intentional target while tracked: the driver may accept only
      // one bounded step per tick. Do not latch an unclipped target on the server.
      if (hand.triggerArmed) send({ type: 'gripper', side, value: 1 - hand.trigger,
        client_time_ms: t + performance.timeOrigin });
    }
  }
  function sendBaseFromSticks(left, right) {
    const la = left?.gamepad?.axes || [];
    const ra = right?.gamepad?.axes || [];
    const dz = (v) => (Math.abs(v) < AXIS_DEAD_ZONE ? 0 : v);
    const lx = la.length >= 4 ? la[2] : la[0];
    const ly = la.length >= 4 ? la[3] : la[1];
    const rx = ra.length >= 4 ? ra[2] : ra[0];
    const xVel = -dz(ly || 0) * BASE_LINEAR_SCALE;
    const yVel = -dz(lx || 0) * BASE_LINEAR_SCALE;
    const thetaVel = -dz(rx || 0) * BASE_ANGULAR_SCALE;
    sendBase(xVel, yVel, thetaVel);
  }
  function faceButtonIndices(rb) {
    if (rb.length >= 6) return [4, 5];
    if (rb.length >= 5) return [3, 4];
    return [0, 1];
  }
  function handleLiftButtons(right, t) {
    const rb = right?.gamepad?.buttons || [];
    const pressed = (button) => !!button && (button.pressed || button.value > 0.5);
    const [aIndex, bIndex] = faceButtonIndices(rb);
    const a = pressed(rb[aIndex]);
    const b = pressed(rb[bIndex]);
    const signature = Array.from(rb, (button, index) =>
      `${index}:${button.pressed ? 'down' : 'up'}:${Number(button.value || 0).toFixed(2)}`).join(' ');
    if (signature !== buttonSignature && t - lastDiagSend > CONTROLLER_DIAG_MS) {
      buttonSignature = signature;
      lastDiagSend = t;
      if (right?.gamepad) send({ type: 'controller_pose', hand: 'right', buttons: Array.from(rb, (button) => button.value) });
    }
    const desired = a && !b ? -LIFT_JOG_VELOCITY : (b && !a ? LIFT_JOG_VELOCITY : 0);
    if (desired !== liftCommand || (desired !== 0 && t - lastLiftSend >= 200)) {
      liftCommand = desired;
      lastLiftSend = t;
      send({ type: 'lift', velocity: desired, button: desired < 0 ? 'A' : (desired > 0 ? 'B' : 'release') });
    }
    if (a !== prevA) logInput(`右手柄 A ${a ? '按下' : '释放'}（下降）`);
    if (b !== prevB) logInput(`右手柄 B ${b ? '按下' : '释放'}（上升）`);
    prevA = a;
    prevB = b;
  }

  // A-Frame owns the XR session and render loop. Input remains raw WebXR data;
  // model rendering never contributes a second coordinate transform.
  function onXRFrame(t, frame, refSpace) {
    if (xrSession.visibilityState && xrSession.visibilityState !== 'visible') return;
    const viewer = frame.getViewerPose(refSpace);
    headPose = viewer ? poseArray(viewer.transform) : null;
    headPoseAt = viewer ? t : 0;
    const edge = readHands(frame, refSpace);
    if (t - lastControlSend <= CONTROL_PERIOD_MS && !edge) return;
    lastControlSend = t;
    const left = hands.left.source;
    const right = hands.right.source;
    sendBaseFromSticks(left, right);
    const lb = left?.gamepad?.buttons || [];
    const y = pressed(lb[faceButtonIndices(lb)[1]], 0.5);
    if (y && !prevY) align();
    prevY = y;
    sendArmPose(t);
    handleLiftButtons(right, t);
  }

  function dirtyTexture(id) {
    const map = $(id).getObject3D('mesh')?.material?.map;
    if (map) map.needsUpdate = true;
  }
  function drawVideo() {
    if (!image.naturalWidth || !image.naturalHeight) return;
    const canvas = $('video-texture');
    // Rotate pixels in one place. The plane itself stays upright, avoiding
    // accumulated canvas/mesh rotations; the desktop source image is unchanged.
    if (canvas.width !== image.naturalWidth || canvas.height !== image.naturalHeight) {
      // Three.js allocates GPU storage for the texture's original dimensions.
      // needsUpdate alone does not resize that storage. Quest then rejects the
      // canvas upload (glCopySubTextureCHROMIUM: destination bad dimensions).
      // Release it before resizing so the next render allocates the new size.
      $('video-plane').getObject3D('mesh')?.material?.map?.dispose();
      canvas.width = image.naturalWidth;
      canvas.height = image.naturalHeight;
    }
    const ctx = canvas.getContext('2d');
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (videoRotation === 180) {
      ctx.translate(canvas.width, canvas.height);
      ctx.rotate(Math.PI);
    }
    ctx.drawImage(image, 0, 0);
    ctx.restore();
    const height = 1.6 * canvas.height / canvas.width;
    $('video-plane').setAttribute('height', height);
    $('hud-plane').setAttribute('position', `0 ${-height / 2 - 0.17} -1.5`);
    $('limit-plane').setAttribute('position', `0 ${height / 2 - 0.14} -1.49`);
    dirtyTexture('video-plane');
  }
  image.onload = () => {
    cameraAt = performance.now();
    $('camera-state').textContent = `实时画面 ${image.naturalWidth} × ${image.naturalHeight}`;
    drawVideo();
  };
  function drawHUD() {
    const canvas = $('hud-texture');
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#14223bed';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = health?.estop ? '#ff8c97' : '#e4edf7';
    ctx.font = '28px sans-serif';
    ctx.fillText(status.textContent, 24, 45);
    ctx.font = '24px sans-serif';
    ctx.fillText(`左臂 ${$('left-state').textContent}    右臂 ${$('right-state').textContent}    ${$('feedback-state').textContent}`, 24, 90);
    ctx.fillStyle = '#a9bdd4';
    ctx.font = '21px sans-serif';
    ctx.fillStyle = limitWarning ? '#fbbf24' : '#a9bdd4';
    ctx.fillText(limitWarning || 'Grip 自动对齐并跟随 · Trigger 夹爪 · A 下降 / B 上升', 24, 140, 976);
    dirtyTexture('hud-plane');
  }
  if (window.AFRAME) {
    AFRAME.registerComponent('teleop-input', {
      tick() {
        const xr = this.el.renderer?.xr;
        const frame = xr?.getFrame();
        if (xrSession && frame) onXRFrame(performance.now(), frame, xr.getReferenceSpace());
      },
    });
  }
  function releaseXRArms() {
    for (const hand of Object.values(hands)) {
      hand.pose = null; hand.active = false; hand.grip = false;
      hand.trigger = null; hand.triggerArmed = false; hand.epoch++;
    }
    sendArmPose(performance.now());
  }
  scene.addEventListener('enter-vr', () => {
    xrSession = scene.renderer.xr.getSession();
    document.body.classList.add('vr-active');
    $('vr-state').textContent = 'VR 已进入';
    $('vr').textContent = '退出 VR';
    xrSession?.addEventListener('visibilitychange', () => {
      if (xrSession.visibilityState !== 'visible') releaseXRArms();
    });
    scene.renderer.xr.getReferenceSpace()?.addEventListener('reset', () => {
      send({ type: 'reanchor' });
    });
  });
  scene.addEventListener('exit-vr', () => {
    xrSession = null;
    headPose = null;
    releaseXRArms();
    sendBase(0, 0, 0, true);
    document.body.classList.remove('vr-active');
    $('vr-state').textContent = 'VR 已退出';
    $('vr').textContent = '进入 VR';
  });
  $('vr').onclick = async () => {
    try {
      if (xrSession) { await scene.exitVR(); return; }
      if (!navigator.xr || !await navigator.xr.isSessionSupported('immersive-vr')) {
        throw new Error('当前浏览器不支持 immersive-vr');
      }
      await scene.enterVR();
    } catch (error) { status.textContent = `VR 无法进入：${error.message}`; }
  };
  setInterval(() => {
    if (health && performance.now() - healthAt > 2500) showDisconnected('网关状态已过期');
    if (cameraAt && performance.now() - cameraAt > 1500) $('camera-state').textContent = '画面已过期';
  }, 500);
  drawHUD();
  connect();
})();
