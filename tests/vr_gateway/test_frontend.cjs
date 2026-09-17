// Run with node --test tests/vr_gateway/test_frontend.cjs. Exercise the actual
// browser input loop with WebXR/DOM transport doubles, without a robot or headset.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function browser() {
  const packets = [];
  const elements = new Map();
  const listeners = {};
  const timers = [];
  const drawings = [];
  const ctx = new Proxy({}, { get: (_, method) => (...args) => drawings.push({ method, args }) });
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      textContent: '', dataset: {}, style: {}, value: '', attributes: {}, width: 640, height: 480,
      getContext: () => ctx, getObject3D: () => null,
      setAttribute(name, value) { this.attributes[name] = value; },
      querySelector: (name) => element(id + name),
      object3D: { position: { fromArray() {} }, quaternion: { fromArray() {} } },
      addEventListener: (name, fn) => { listeners[name] = fn; },
      showModal() {}, close() {},
    });
    return elements.get(id);
  }
  let now = 1000;
  let tick;
  const sources = ['left', 'right'].map((handedness) => ({
    handedness, gripSpace: handedness,
    gamepad: { axes: [0, 0, 0, 0], buttons: Array.from({ length: 6 }, () => ({ value: 0, pressed: false })) },
  }));
  const session = { inputSources: sources, addEventListener() {} };
  const transform = { position: { x: 0.1, y: 0.2, z: -0.3 }, orientation: { x: 0, y: 0, z: 0, w: 1 } };
  const frame = { getViewerPose: () => ({ transform }), getPose: () => ({ transform }) };
  const scene = element('scene');
  scene.renderer = { xr: { getSession: () => session, getFrame: () => frame, getReferenceSpace: () => ({ addEventListener() {} }) } };
  class Socket {
    static OPEN = 1;
    constructor() { this.readyState = 1; Socket.instance = this; }
    send(raw) { packets.push(JSON.parse(raw)); }
  }
  const context = {
    document: { getElementById: element, querySelector: () => scene, body: { classList: { add() {}, remove() {} } } },
    window: {}, WebSocket: Socket, location: { protocol: 'http:', host: 'localhost' },
    navigator: {}, performance: { now: () => now, timeOrigin: 1700000000000 },
    console: { info() {} }, setInterval(fn) { timers.push(fn); }, setTimeout() {},
    AFRAME: { registerComponent: (_, component) => { tick = component.tick.bind({ el: scene }); } },
  };
  context.window.AFRAME = context.AFRAME;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../src/lerobot/vr_gateway/static/app.js'), 'utf8'), context);
  Socket.instance.onopen();
  Socket.instance.onmessage({ data: JSON.stringify({ type: 'status', robot_connected: true, feedback_fresh: true,
    feedback_age_ms: 0, arms: {}, arm_mapping_loaded: true }) });
  listeners['enter-vr']();
  return {
    packets, sources, context, frame, element, drawings,
    receive(message) { Socket.instance.onmessage({ data: JSON.stringify(message) }); },
    loadCamera(name, width = 640, height = 480) {
      const image = element(`${name}-view`);
      image.naturalWidth = width; image.naturalHeight = height; image.onload();
    },
    elapse(dt) { now += dt; timers.forEach((fn) => fn()); },
    reconnect() { Socket.instance.onclose({ code: 1000 }); Socket.instance.onopen(); },
    status(message) { Socket.instance.onmessage({ data: JSON.stringify({ type: 'status', feedback_fresh: true, ...message }) }); },
    step(dt = 41) { now += dt; tick(); },
    button(side, index, value) {
      const button = sources[side === 'left' ? 0 : 1].gamepad.buttons[index];
      button.value = value; button.pressed = value > 0.5;
    },
    last(type, side) { return packets.filter((packet) => packet.type === type && (!side || packet.side === side)).at(-1); },
  };
}

test('Legacy reports loaded Home without changing the displayed control mode', () => {
  const ui = browser();
  ui.status({ arm_ik_mode: 'legacy', arm_mapping_loaded: true });
  assert.equal(ui.element('mapping-state').textContent, 'Legacy · Home 零位已加载');
  ui.status({ arm_ik_mode: 'legacy', arm_mapping_loaded: false });
  assert.equal(ui.element('mapping-state').textContent, 'Legacy · 缺少 Home 零位');
});

test('camera selection handles all subsets and routes three feeds to their own VR textures', () => {
  const ui = browser();
  const names = ['forward', 'wrist_left', 'wrist_right'];
  for (let mask = 0; mask < 8; mask++) {
    const selected = names.filter((_, index) => mask & (1 << index));
    ui.receive({ type: 'hello', cameras: selected });
    assert.equal(ui.element('camera-empty').hidden, selected.length > 0);
    for (const name of names) {
      assert.equal(ui.element(`${name}-tile`).hidden, !selected.includes(name));
      assert.equal(ui.element(`${name}-plane`).attributes.visible, selected.includes(name));
    }
  }
  ui.receive({ type: 'observation', cameras: names, frames: {
    forward: { jpeg_b64: 'head' }, wrist_left: { jpeg_b64: 'left' }, wrist_right: { jpeg_b64: 'right' },
  } });
  names.forEach((name, index) => {
    assert.equal(ui.element(`${name}-view`).src, `data:image/jpeg;base64,${['head', 'left', 'right'][index]}`);
    ui.loadCamera(name, index === 0 ? 1280 : 640, index === 0 ? 720 : 480);
    assert.equal(ui.element(`${name}-view`).hidden, false);
    assert.equal(ui.element(`${name}-texture`).width, index === 0 ? 1280 : 640);
    assert.ok(ui.drawings.some(({ method, args }) => method === 'drawImage' && args[0] === ui.element(`${name}-view`)));
  });
  const positions = names.map((name) => ui.element(`${name}-plane`).attributes.position.split(' ').map(Number));
  assert.ok(positions[0][1] > positions[1][1]);
  assert.ok(positions[1][0] < positions[2][0]);
  assert.equal(positions[1][1], positions[2][1]);
  ui.receive({ cameras: ['wrist_right'], frames: { forward: { jpeg_b64: 'ignored' } } });
  assert.equal(ui.element('forward-view').src, 'data:image/jpeg;base64,head');
  assert.equal(ui.element('wrist_right-plane').attributes.position, '0 0 -1.5');
});

test('each camera independently expires, recovers and keeps only the newest pending JPEG', () => {
  const ui = browser();
  const cameras = ['forward', 'wrist_left'];
  ui.receive({ cameras, frames: { forward: { jpeg_b64: 'head' }, wrist_left: { jpeg_b64: 'first' } } });
  ui.receive({ frames: { wrist_left: { jpeg_b64: 'skipped' } } });
  ui.receive({ frames: { wrist_left: { jpeg_b64: 'latest' } } });
  assert.equal(ui.element('wrist_left-view').src, 'data:image/jpeg;base64,first');
  ui.loadCamera('wrist_left');
  assert.equal(ui.element('wrist_left-view').src, 'data:image/jpeg;base64,latest');
  ui.loadCamera('wrist_left'); ui.loadCamera('forward');
  ui.elapse(1000);
  ui.receive({ frames: { forward: { jpeg_b64: 'fresh' } } }); ui.loadCamera('forward');
  ui.elapse(600);
  assert.equal(ui.element('wrist_left-state').textContent, '画面已过期');
  assert.equal(ui.element('wrist_left-view').hidden, true);
  assert.match(ui.element('forward-state').textContent, /实时/);
  assert.ok(ui.drawings.some(({ method, args }) => method === 'fillText' && /左腕.*画面已过期/.test(args[0])));
  ui.receive({ frames: { wrist_left: { jpeg_b64: 'recovered' } } }); ui.loadCamera('wrist_left');
  assert.equal(ui.element('wrist_left-view').hidden, false);
  ui.receive({ frames: { wrist_left: { jpeg_b64: 'bad' } } }); ui.element('wrist_left-view').onerror();
  assert.equal(ui.element('wrist_left-state').textContent, '画面解码失败');
  ui.reconnect();
  assert.equal(ui.element('forward-view').hidden, true);
});

test('resizing each camera releases its own GPU texture before upload', () => {
  const ui = browser();
  const cameras = ['forward', 'wrist_left', 'wrist_right'];
  ui.receive({ cameras });
  for (const name of cameras) {
    let disposed = 0;
    const map = { dispose() { disposed++; }, needsUpdate: false };
    ui.element(`${name}-plane`).getObject3D = () => ({ material: { map } });
    ui.receive({ frames: { [name]: { jpeg_b64: name } } });
    ui.loadCamera(name, 1280, 720);
    assert.equal(disposed, 1);
    assert.equal(map.needsUpdate, true);
    ui.loadCamera(name, 1280, 720);
    assert.equal(disposed, 1);
  }
});

test('Trigger defaults closed, opens while pressed, closes on release; Grip stays independent', () => {
  const ui = browser();
  ui.step();
  assert.equal(ui.last('gripper').value, 1); // idle means closed, never auto-open
  ui.button('left', 0, 1);
  ui.step();
  assert.equal(ui.last('arm_pose').active, false);
  assert.equal(ui.last('gripper', 'left').value, 0);
  assert.ok(ui.last('gripper').client_time_ms > 0);
  ui.button('left', 0, 0);
  ui.step();
  assert.equal(ui.packets.filter((p) => p.type === 'gripper' && p.side === 'left').at(-1).value, 1);
  ui.button('left', 1, 1);
  ui.step();
  assert.equal(ui.last('arm_pose').left_active, true);
  assert.equal(ui.last('arm_pose').right_active, false);
  assert.deepEqual(ui.last('arm_pose').left.position, [0.1, 0.2, -0.3]);
  assert.equal(ui.last('arm_pose').body_basis, undefined);
  assert.equal(ui.last('arm_pose').auto_align, true);
  assert.deepEqual(ui.last('arm_pose').head.orientation, [0, 0, 0, 1]);
  const epoch = ui.last('arm_pose').left_epoch;
  ui.button('left', 1, 0); ui.step(5);
  assert.equal(ui.last('arm_pose').left_active, false);
  ui.button('left', 1, 1); ui.step(5);
  assert.ok(ui.last('arm_pose').left_epoch > epoch);
});

test('both triggers independently open proportionally and repeat targets until released', () => {
  const ui = browser();
  ui.step();
  for (const side of ['left', 'right']) assert.equal(ui.last('gripper', side).value, 1);
  ui.button('left', 0, 0.4); ui.button('right', 0, 1); ui.step();
  assert.equal(ui.last('gripper', 'left').value, 0.6);
  assert.equal(ui.last('gripper', 'right').value, 0);
  const count = ui.packets.length;
  ui.step();
  assert.equal(ui.packets.slice(count).filter((p) => p.type === 'gripper').length, 2);
  ui.button('left', 0, 0); ui.step();
  assert.equal(ui.last('gripper', 'left').value, 1);
  assert.equal(ui.last('gripper', 'right').value, 0);
});

test('gripper gates block stale, paused, estopped or untracked input and resume from current trigger', () => {
  const ui = browser();
  for (const gate of [{ feedback_fresh: false }, { arm_frozen: true }, { estop: true }]) {
    ui.button('left', 0, 1); ui.step();
    ui.status(gate);
    const count = ui.packets.filter((p) => p.type === 'gripper').length;
    ui.button('left', 0, 0); ui.step();
    assert.equal(ui.packets.filter((p) => p.type === 'gripper').length, count);
    ui.status({}); ui.step();
    assert.equal(ui.last('gripper', 'left').value, 1);
  }
  const getPose = ui.frame.getPose;
  ui.button('left', 0, 1); ui.step();
  ui.frame.getPose = () => null;
  const count = ui.packets.filter((p) => p.type === 'gripper').length;
  ui.button('left', 0, 0); ui.step();
  assert.equal(ui.packets.filter((p) => p.type === 'gripper').length, count);
  ui.frame.getPose = getPose; ui.step();
  assert.equal(ui.last('gripper', 'left').value, 1);
  ui.button('left', 0, 1); ui.step();
  ui.reconnect();
  const beforeFeedback = ui.packets.filter((p) => p.type === 'gripper').length;
  ui.button('left', 0, 0); ui.step();
  assert.equal(ui.packets.filter((p) => p.type === 'gripper').length, beforeFeedback);
  ui.status({}); ui.step();
  assert.equal(ui.last('gripper', 'left').value, 1);
});

test('Quest sticks keep existing signs, scales and dead zone', () => {
  const ui = browser();
  ui.sources[0].gamepad.axes = [0, 0, 1, -1];
  ui.sources[1].gamepad.axes = [0, 0, -1, 0];
  ui.step();
  assert.deepEqual(ui.last('base'), { type: 'base', 'x.vel': 0.3, 'y.vel': -0.3, 'theta.vel': 60 });
  ui.sources[0].gamepad.axes = [0, 0, 0.1, 0.1];
  ui.sources[1].gamepad.axes = [0, 0, 0.1, 0];
  ui.step();
  assert.equal(Math.abs(ui.last('base')['x.vel']), 0);
  assert.equal(Math.abs(ui.last('base')['y.vel']), 0);
  assert.equal(Math.abs(ui.last('base')['theta.vel']), 0);
});

test('A/B lift directions, held refresh and release are unchanged', () => {
  const ui = browser();
  ui.button('right', 4, 1); ui.step();
  assert.deepEqual(ui.last('lift'), { type: 'lift', velocity: -1300, button: 'A' });
  const count = ui.packets.length;
  ui.step(201);
  assert.ok(ui.packets.slice(count).some((p) => p.type === 'lift' && p.velocity === -1300));
  ui.button('right', 4, 0); ui.button('right', 5, 1); ui.step();
  assert.equal(ui.last('lift').velocity, 1300);
  ui.button('right', 5, 0); ui.step();
  assert.equal(ui.last('lift').velocity, 0);
});

test('Y sends an explicit alignment; looking around alone does not align', () => {
  const ui = browser();
  ui.step();
  assert.equal(ui.last('align'), undefined);
  ui.button('left', 5, 1); ui.step();
  assert.deepEqual(ui.last('align').head.orientation, [0, 0, 0, 1]);
  ui.step();
  assert.equal(ui.packets.filter((p) => p.type === 'align').length, 1);
});

test('WASD still drives the base and key release stops it', () => {
  const ui = browser();
  for (const [key, values] of Object.entries({ w: [0.2, 0, 0], s: [-0.2, 0, 0], a: [0, 0, 0.8], d: [0, 0, -0.8] })) {
    ui.context.window.onkeydown({ key, repeat: false });
    assert.deepEqual(['x.vel', 'y.vel', 'theta.vel'].map((name) => ui.last('base')[name]), values);
    ui.context.window.onkeyup({ key });
    assert.deepEqual(['x.vel', 'y.vel', 'theta.vel'].map((name) => ui.last('base')[name]), [0, 0, 0]);
  }
});

test('tracking loss releases a held arm without reusing the previous pose', () => {
  const ui = browser();
  ui.button('left', 1, 1); ui.step();
  ui.frame.getPose = () => null;
  ui.step(5);
  assert.equal(ui.last('arm_pose').left, null);
  // Preserve physical Grip to distinguish tracking loss from deliberate release.
  assert.equal(ui.last('arm_pose').left_active, true);
});

test('joint limit warning appears once, clears on recovery and on stale feedback', () => {
  const ui = browser();
  const message = { joint_limit_warnings: [{ side: 'right', joint: 'wrist_roll', bound: 'upper' }] };
  ui.status(message);
  assert.equal(ui.element('limit-warning').hidden, false);
  assert.match(ui.element('limit-warning').textContent, /限位警告.*右臂.*腕滚转/);
  const log = ui.element('input-log').textContent;
  ui.status(message);
  assert.equal(ui.element('input-log').textContent, log);
  ui.status({ joint_limit_warnings: [] });
  assert.equal(ui.element('limit-warning').hidden, true);
  ui.status(message);
  ui.status({ ...message, feedback_fresh: false });
  assert.equal(ui.element('limit-warning').hidden, true);
});
