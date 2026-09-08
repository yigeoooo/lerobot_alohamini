(() => {
  'use strict';

  // ---------------------------------------------------------------- constants

  // The browser must not out-run the robot's serial buses. The gateway coalesces
  // whatever arrives, but sending faster than it can flush only adds queueing delay.
  const CONTROL_PERIOD_MS = 40;   // 25 Hz arm/base cadence
  const HEAD_POSE_PERIOD_MS = 100;
  // Base packets are sent on change only; this keepalive keeps the server watchdog
  // (1 s by default) fed while the joystick sits at rest.
  const BASE_KEEPALIVE_MS = 400;
  // Diagnostics only: rate-limit so button probing cannot flood the control path.
  const CONTROLLER_DIAG_MS = 250;
  const AXIS_DEAD_ZONE = 0.15;
  const BASE_LINEAR_SCALE = 0.30;   // m/s at full stick
  const BASE_ANGULAR_SCALE = 60;    // deg/s at full stick
  const LIFT_JOG_VELOCITY = 1300;

  // ------------------------------------------------------------------- helpers

  const $ = (id) => document.getElementById(id);
  const status = $('status');
  const image = $('view');
  const inputLog = $('input-log');

  const inputHistory = [];

  function logInput(message) {
    const line = `${new Date().toLocaleTimeString()} ${message}`;
    console.info(`[VR] ${message}`);
    inputHistory.push(line);
    if (inputHistory.length > 8) inputHistory.shift();
    if (inputLog) inputLog.textContent = inputHistory.join('\n');
  }

  // --------------------------------------------------------------- connection

  let ws;
  const wsUrl = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`;

  function send(message) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(message));
  }

  function onServerMessage(event) {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch (_) {
      return;
    }
    if (message.jpeg_b64) image.src = 'data:image/jpeg;base64,' + message.jpeg_b64;
    if (message.type === 'error') {
      status.textContent = message.error;
      logInput(`服务器错误：${message.error}`);
      return;
    }
    // The server no longer acks every packet; an ack that does arrive means something
    // was refused or degraded, so it is worth showing to the operator.
    if (message.type === 'ack' && message.for) {
      const detail = message.ignored ? `ignored:${message.ignored}` : (message.status || '');
      status.textContent = `connected · ${message.for}${detail ? ' · ' + detail : ''}`;
      if (message.ignored || message.status === 'rejected' || message.status === 'stale') {
        logInput(`指令被拒绝：${message.for} ${detail}`);
      } else if (message.status === 'reanchored') {
        logInput('重锚定完成：当前姿态已作为起点');
      }
    }
    if (message.type === 'status') reportStatus(message);
  }

  let lastReportedRejects = 0;
  let lastReportedStale = 0;

  function reportStatus(message) {
    const parts = [];
    if (message.estop) parts.push('急停中');
    if (message.arm_frozen) parts.push('手臂保持');
    if (message.calibrated) parts.push('校准标志');
    if (message.arm_pending_reanchor) parts.push('等待重锚定');
    if (message.arm_homing) {
      const error = Number(message.arm_home_max_error_deg);
      parts.push(Number.isFinite(error) ? `机械臂归位中 ${error.toFixed(1)}°` : '机械臂归位中');
    } else if (message.arm_ik_active) {
      parts.push('机械臂跟随中');
    } else if (message.arm_engage_reason) {
      parts.push(`原因:${message.arm_engage_reason}`);
    }
    if (!message.ik_available) parts.push('IK 不可用');
    status.textContent = `connected${parts.length ? ' · ' + parts.join(' · ') : ''}`;
    // Surface IK rejections: previously the arm just stopped tracking in silence.
    if (message.ik_rejected > lastReportedRejects) {
      logInput(`IK 拒绝了 ${message.ik_rejected - lastReportedRejects} 个手臂姿态（累计 ${message.ik_rejected}）`);
      lastReportedRejects = message.ik_rejected;
    }
    if (message.poses_stale > lastReportedStale) {
      logInput(`丢弃了 ${message.poses_stale - lastReportedStale} 个过期姿态（网络延迟）`);
      lastReportedStale = message.poses_stale;
    }
  }

  function connect() {
    ws = new WebSocket(wsUrl);
    ws.onopen = () => {
      status.textContent = 'connected';
      send({ type: 'hello', client: 'webxr' });
    };
    ws.onclose = () => {
      status.textContent = 'disconnected';
      setTimeout(connect, 1000);
    };
    ws.onerror = () => {
      status.textContent = 'connection error';
    };
    ws.onmessage = onServerMessage;
  }

  connect();

  // -------------------------------------------------------------- base packets

  let lastBaseSent = null;
  let lastBaseSentAt = 0;

  // Send base velocity only when it changes, plus a slow keepalive. A packet every
  // frame costs the gateway a full send_action over the motor buses for no new
  // information, which is bus time the arms need.
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

  // ------------------------------------------------------------- 2D UI bindings

  $('estop').onclick = () => send({ type: 'estop', enabled: true });
  $('reset-estop').onclick = () => send({ type: 'estop', enabled: false });
  $('calibrate').onclick = () => send({ type: 'calibrate', enabled: true });

  $('reanchor').onclick = () => {
    armReanchorRequested = true;
    logInput('请求重锚定：下一次双手 grip 会以当前姿态作为起点');
    status.textContent = 'waiting re-anchor';
  };

  // "Clutch" is now an explicit arm freeze: off (the default) means the arms follow the
  // controller grips, on means arm poses are ignored while the base still drives.
  let armFrozen = false;
  const clutchButton = $('clutch');
  clutchButton.textContent = 'Hold arms: off';
  clutchButton.onclick = () => {
    armFrozen = !armFrozen;
    clutchButton.textContent = `Hold arms: ${armFrozen ? 'on' : 'off'}`;
    send({ type: 'clutch', enabled: armFrozen });
    logInput(armFrozen ? '手臂保持中（忽略手柄姿态）' : '手臂恢复跟随');
  };

  $('lift').oninput = (e) => {
    $('lift-value').textContent = `${e.target.value} mm`;
    send({ type: 'lift', height_mm: Number(e.target.value) });
  };

  $('gripper').oninput = (e) => {
    $('gripper-value').textContent = `${Math.round(Number(e.target.value) * 100)}%`;
    send({ type: 'gripper', value: Number(e.target.value) });
  };

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

  joy.onpointerdown = (e) => {
    joyActive = true;
    joy.setPointerCapture(e.pointerId);
    joyMove(e);
  };
  joy.onpointermove = joyMove;
  joy.onpointerup = () => {
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

  // ------------------------------------------------------------- XR renderer

  let xrSession, xrRefSpace, xrGl, xrProgram, xrTexture, xrPosBuffer, xrUvBuffer;
  let frameCanvas, frameCtx;

  function initXRRenderer() {
    const canvas = $('xr-canvas');
    xrGl = canvas.getContext('webgl', { xrCompatible: true }) || canvas.getContext('webgl2', { xrCompatible: true });
    if (!xrGl) throw new Error('WebGL XR unavailable');
    const gl = xrGl;

    const vs = gl.createShader(gl.VERTEX_SHADER);
    gl.shaderSource(vs, 'attribute vec2 p; attribute vec2 uv; varying vec2 v; void main(){gl_Position=vec4(p,0.,1.);v=uv;}');
    gl.compileShader(vs);

    const fs = gl.createShader(gl.FRAGMENT_SHADER);
    gl.shaderSource(fs, 'precision mediump float; varying vec2 v; uniform sampler2D tex; void main(){gl_FragColor=texture2D(tex,v);}');
    gl.compileShader(fs);

    xrProgram = gl.createProgram();
    gl.attachShader(xrProgram, vs);
    gl.attachShader(xrProgram, fs);
    gl.linkProgram(xrProgram);

    xrPosBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, xrPosBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);

    xrUvBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, xrUvBuffer);
    // The forward camera is mounted upside-down relative to the Quest headset.
    // Invert both texture axes so the immersive view is rotated clockwise by 180 degrees.
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([1, 0, 0, 0, 1, 1, 0, 1]), gl.STATIC_DRAW);

    xrTexture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, xrTexture);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

    frameCanvas = document.createElement('canvas');
    frameCanvas.width = 640;
    frameCanvas.height = 480;
    frameCtx = frameCanvas.getContext('2d');
  }

  function drawXR(frame, pose) {
    const gl = xrGl;
    const layer = xrSession?.renderState?.baseLayer;
    if (!gl || !layer || !pose) return;

    if (image.complete && image.naturalWidth) {
      frameCtx.drawImage(image, 0, 0, frameCanvas.width, frameCanvas.height);
      gl.bindTexture(gl.TEXTURE_2D, xrTexture);
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, frameCanvas);
    }

    gl.bindFramebuffer(gl.FRAMEBUFFER, layer.framebuffer);
    gl.useProgram(xrProgram);

    const p = gl.getAttribLocation(xrProgram, 'p');
    const u = gl.getAttribLocation(xrProgram, 'uv');
    const tex = gl.getUniformLocation(xrProgram, 'tex');

    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, xrTexture);
    gl.uniform1i(tex, 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, xrPosBuffer);
    gl.enableVertexAttribArray(p);
    gl.vertexAttribPointer(p, 2, gl.FLOAT, false, 0, 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, xrUvBuffer);
    gl.enableVertexAttribArray(u);
    gl.vertexAttribPointer(u, 2, gl.FLOAT, false, 0, 0);

    // Preserve the camera aspect ratio in each eye viewport. Rendering the
    // 4:3 camera frame into the full (usually wider) eye rectangle stretches
    // it on Quest; letterbox instead and clear the unused area to black.
    const iw = image.naturalWidth || 4;
    const ih = image.naturalHeight || 3;
    const imageAspect = iw / ih;

    for (const view of pose.views) {
      const vp = layer.getViewport(view);
      const viewportAspect = vp.width / vp.height;
      let w = vp.width;
      let h = vp.height;
      if (viewportAspect > imageAspect) w = Math.round(vp.height * imageAspect);
      else h = Math.round(vp.width / imageAspect);
      const x = vp.x + Math.floor((vp.width - w) / 2);
      const y = vp.y + Math.floor((vp.height - h) / 2);
      gl.enable(gl.SCISSOR_TEST);
      gl.scissor(vp.x, vp.y, vp.width, vp.height);
      gl.clearColor(0, 0, 0, 1);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.disable(gl.SCISSOR_TEST);
      gl.viewport(x, y, w, h);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    }
  }

  // -------------------------------------------------------------- XR input loop

  let leftGripPose = null;
  let rightGripPose = null;
  let leftGripPoseAt = 0;
  let rightGripPoseAt = 0;
  let lastPoseSend = 0;
  let lastControlSend = 0;
  let lastDiagSend = 0;
  let armWasActive = false;
  let armReanchorRequested = false;
  let buttonSignature = '';
  let joystickWasActive = false;
  let lastJoystickLog = 0;
  let prevA = false;
  let prevB = false;
  let liftCommand = 0;
  let lastLiftSend = 0;

  function poseArray(p) {
    if (!p) return null;
    return {
      position: [p.position.x, p.position.y, p.position.z],
      orientation: [p.orientation.x, p.orientation.y, p.orientation.z, p.orientation.w],
    };
  }

  function readGripPoses(frame) {
    let left = null;
    let right = null;
    let nextLeftPose = null;
    let nextRightPose = null;
    for (const src of xrSession.inputSources) {
      if (src.handedness === 'left') left = src;
      if (src.handedness === 'right') right = src;
      if (!src.gripSpace) continue;
      const sp = frame.getPose(src.gripSpace, xrRefSpace);
      if (!sp) continue;
      const pose = poseArray(sp.transform);
      if (src.handedness === 'left') nextLeftPose = pose;
      if (src.handedness === 'right') nextRightPose = pose;
    }
    // Never keep a pose from an earlier frame when WebXR temporarily cannot
    // resolve gripSpace; otherwise it gets a fresh packet timestamp and looks
    // like a valid new command to the gateway.
    const now = performance.now();
    leftGripPose = nextLeftPose;
    rightGripPose = nextRightPose;
    leftGripPoseAt = nextLeftPose ? now : 0;
    rightGripPoseAt = nextRightPose ? now : 0;
    return { left, right };
  }

  function sendBaseFromSticks(left, right) {
    const la = left?.gamepad?.axes || [];
    const ra = right?.gamepad?.axes || [];
    const dz = (v) => (Math.abs(v) < AXIS_DEAD_ZONE ? 0 : v);
    // xr-standard puts the thumbstick on axes 2/3; older mappings use 0/1.
    const lx = la.length >= 4 ? la[2] : la[0];
    const ly = la.length >= 4 ? la[3] : la[1];
    const rx = ra.length >= 4 ? ra[2] : ra[0];
    const xVel = -dz(ly || 0) * BASE_LINEAR_SCALE;
    const yVel = -dz(lx || 0) * BASE_LINEAR_SCALE;
    const thetaVel = -dz(rx || 0) * BASE_ANGULAR_SCALE;
    sendBase(xVel, yVel, thetaVel);
    return { lx: lx || 0, ly: ly || 0, rx: rx || 0, xVel, yVel, thetaVel };
  }

  function sendArmPose(left, right, t) {
    const lb = left?.gamepad?.buttons || [];
    const rb = right?.gamepad?.buttons || [];
    const gripPressed = (g) => !!g && (g.pressed || g.value > 0.5);
    const poseFresh = (t - leftGripPoseAt) <= 120 && (t - rightGripPoseAt) <= 120;
    const active = gripPressed(lb[1]) && gripPressed(rb[1]) && !!leftGripPose && !!rightGripPose && poseFresh;
    const reanchor = armReanchorRequested && active;
    // Idle poses are pure overhead once the IK has been released, so send them only
    // while the clutch is squeezed plus one final packet to release it.
    if (!active && !armWasActive && !armReanchorRequested) return;
    if (active !== armWasActive) {
      const leftGrip = Number(lb[1]?.value || 0).toFixed(2);
      const rightGrip = Number(rb[1]?.value || 0).toFixed(2);
      logInput(active
        ? `双 grip 已激活（左=${leftGrip} 右=${rightGrip}），开始归位/跟随`
        : `双 grip 已释放（左=${leftGrip} 右=${rightGrip}），机械臂保持`);
    }
    armWasActive = active;
    if (reanchor) armReanchorRequested = false;
    send({
      type: 'arm_pose',
      // Client-sampled timestamp: the server measures relative delay from it and
      // discards poses released in a burst after a network stall.
      client_time_ms: t + performance.timeOrigin,
      active,
      left: leftGripPose,
      right: rightGripPose,
      left_gripper: Number(lb[0]?.value || 0),
      right_gripper: Number(rb[0]?.value || 0),
      reanchor,
    });
    if (reanchor) logInput('已发送重锚定：把当前双手姿态作为摇操起点');
  }

  function faceButtonIndices(rb) {
    // Oculus Touch layouts vary: xr-standard commonly exposes A/B at 4/5,
    // while some Quest browsers expose a compact 5-button array at 3/4.
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
    // Diagnostics only: send on change and no faster than CONTROLLER_DIAG_MS so button
    // probing never competes with arm poses for bus time. Leaving buttonSignature stale
    // when the rate limit blocks means the next frame retries.
    if (signature !== buttonSignature && t - lastDiagSend > CONTROLLER_DIAG_MS) {
      buttonSignature = signature;
      lastDiagSend = t;
      logInput(`右手柄按钮 ${signature || '(none)'} | A=${aIndex} B=${bIndex}`);
      if (right?.gamepad) {
        send({ type: 'controller_pose', hand: 'right', buttons: Array.from(rb, (button) => button.value) });
      }
    }

    // The lift servo latches its goal velocity, so send only on change instead of
    // re-issuing the same jog command at the frame rate.
    const desired = a && !b ? -LIFT_JOG_VELOCITY : (b && !a ? LIFT_JOG_VELOCITY : 0);
    // Refresh a held jog periodically: the lift driver treats velocity as a
    // watchdog-style command on some firmware, so a one-shot packet can stop
    // before the operator releases the button.
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

  function logJoystick(sticks, t) {
    const moving = Math.abs(sticks.xVel) > 0.001 || Math.abs(sticks.yVel) > 0.001 || Math.abs(sticks.thetaVel) > 0.001;
    if (moving && (!joystickWasActive || t - lastJoystickLog > 500)) {
      logInput(`摇杆 L(${sticks.lx.toFixed(2)},${sticks.ly.toFixed(2)}) R(${sticks.rx.toFixed(2)}) → base ` +
        `x=${sticks.xVel.toFixed(2)} y=${sticks.yVel.toFixed(2)} θ=${sticks.thetaVel.toFixed(1)}`);
      lastJoystickLog = t;
    } else if (!moving && joystickWasActive) {
      logInput('摇杆释放 → 底盘停止');
    }
    joystickWasActive = moving;
  }

  function onXRFrame(t, frame) {
    if (!xrSession) return;
    xrSession.requestAnimationFrame(onXRFrame);

    const pose = frame.getViewerPose(xrRefSpace);
    if (pose) drawXR(frame, pose);

    const { left, right } = readGripPoses(frame);

    if (pose && t - lastPoseSend > HEAD_POSE_PERIOD_MS) {
      send({ type: 'head_pose', pose: poseArray(pose.transform) });
      lastPoseSend = t;
    }

    if (t - lastControlSend <= CONTROL_PERIOD_MS) return;
    lastControlSend = t;

    const sticks = sendBaseFromSticks(left, right);
    sendArmPose(left, right, t);
    handleLiftButtons(right, t);
    logJoystick(sticks, t);
  }

  // ------------------------------------------------------------ session control

  $('vr').onclick = async () => {
    if (!navigator.xr) {
      status.textContent = 'WebXR unavailable';
      return;
    }
    try {
      if (navigator.xr.isSessionSupported && !(await navigator.xr.isSessionSupported('immersive-vr'))) {
        status.textContent = 'immersive-vr unsupported';
        return;
      }
      xrSession = await navigator.xr.requestSession('immersive-vr', {
        optionalFeatures: ['local-floor', 'bounded-floor'],
      });
      initXRRenderer();
      if (xrGl.makeXRCompatible) await xrGl.makeXRCompatible();
      if (typeof XRWebGLLayer !== 'undefined') {
        xrSession.updateRenderState({ baseLayer: new XRWebGLLayer(xrSession, xrGl) });
      }
      xrSession.onend = () => {
        xrSession = null;
        xrGl = null;
        leftGripPose = null;
        rightGripPose = null;
        leftGripPoseAt = 0;
        rightGripPoseAt = 0;
        armReanchorRequested = false;
        // Release the arm clutch and stop the base: the frame loop is gone and can no
        // longer do it, and the server would otherwise hold the last commanded values
        // until the watchdog expires.
        if (armWasActive) {
          send({ type: 'arm_pose', active: false, left: null, right: null });
          armWasActive = false;
        }
        sendBase(0, 0, 0, true);
        status.textContent = 'VR ended';
      };
      xrRefSpace = await xrSession.requestReferenceSpace('local-floor')
        .catch(() => xrSession.requestReferenceSpace('local'));
      status.textContent = 'VR active';
      xrSession.requestAnimationFrame(onXRFrame);
    } catch (e) {
      status.textContent = `VR failed: ${e.message}`;
      try {
        if (xrSession) await xrSession.end();
      } catch (_) { /* session already gone */ }
      xrSession = null;
    }
  };
})();
