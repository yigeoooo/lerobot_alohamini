"""Offline GPU regression: run with uv run python tests/vr_gateway/check_video_render.py.

Requires Chrome/Chromium and websockets. Serves only the real static UI; no robot
gateway, camera or headset is opened. Pixel readback exercises A-Frame's complete
scene for every camera selection after resolution changes and 180-degree rotation.
"""

import asyncio
import functools
import json
import shutil
import subprocess
import tempfile
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

import websockets

STATIC = Path(__file__).resolve().parents[2] / "src/lerobot/vr_gateway/static"
PIXEL_CHECK = """(async () => {
  const scene = document.querySelector('a-scene');
  const names = ['forward', 'wrist_left', 'wrist_right'];
  const palettes = [
    ['red', 'lime', 'blue', 'yellow'], ['cyan', 'magenta', 'white', 'red'],
    ['blue', 'white', 'red', 'lime']
  ];
  scene.pause();
  const renderer = scene.renderer;
  const size = 900;
  const target = new AFRAME.THREE.WebGLRenderTarget(size, size);
  const camera = scene.camera;
  camera.aspect = 1;
  camera.updateProjectionMatrix();
  const results = [];
  try {
    for (let mask = 0; mask < 8; mask++) {
      const selected = names.filter((_, index) => mask & (1 << index));
      window.testSocket.onmessage({data: JSON.stringify({type: 'hello', cameras: selected})});
      for (const [width, height, rotation] of [
        [640, 480, 0], [1280, 720, 0], [480, 360, 0], [1280, 720, 0],
        [1280, 720, 180], [1280, 720, 0]
      ]) {
        await Promise.all(selected.map(async (name) => {
          const source = document.createElement('canvas');
          const w = name === 'forward' ? width : Math.min(width, 640);
          const h = name === 'forward' ? height : w * 3 / 4;
          source.width = w; source.height = h;
          const ctx = source.getContext('2d');
          palettes[names.indexOf(name)].forEach((color, index) => {
            ctx.fillStyle = color;
            ctx.fillRect((index % 2) * w / 2, Math.floor(index / 2) * h / 2, w / 2, h / 2);
          });
          const image = document.getElementById(`${name}-view`);
          await new Promise((resolve, reject) => {
            image.addEventListener('load', resolve, {once: true});
            image.addEventListener('error', reject, {once: true});
            // PNG pixels are lossless; the same image load/texture path handles JPEG.
            image.src = source.toDataURL();
          });
        }));
        document.getElementById('video-rotation').value = String(rotation);
        document.getElementById('settings-form').dispatchEvent(new Event('submit', {cancelable: true}));
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        scene.object3D.updateMatrixWorld(true);
        renderer.setRenderTarget(target);
        renderer.setViewport(0, 0, size, size);
        renderer.render(scene.object3D, camera);
        const pixels = new Uint8Array(size * size * 4);
        renderer.readRenderTargetPixels(target, 0, 0, size, size, pixels);
        const samples = selected.map((name) => {
          const plane = document.getElementById(`${name}-plane`);
          const corners = [[-1, 1], [1, 1], [-1, -1], [1, -1]].map(([x, y]) => {
            const point = new AFRAME.THREE.Vector3(
              x * plane.getAttribute('width') / 4, y * plane.getAttribute('height') / 4, 0);
            plane.object3D.localToWorld(point); point.project(camera);
            const px = Math.floor((point.x + 1) * size / 2);
            const py = Math.floor((point.y + 1) * size / 2);
            if (px < 0 || px >= size || py < 0 || py >= size) throw Error(`offscreen: ${name}`);
            const offset = (py * size + px) * 4;
            return Array.from(pixels.slice(offset, offset + 3));
          });
          return {name, corners};
        });
        results.push({width, height, rotation, error: renderer.getContext().getError(),
          mask, samples, visible: names.filter(name => document.getElementById(`${name}-plane`).object3D.visible)});
      }
    }
  } finally {
    renderer.setRenderTarget(null); target.dispose();
  }
  return results;
})()"""


class StaticHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/static/"):
            self.path = self.path[len("/static") :]
        super().do_GET()

    def log_message(self, *_args):
        pass


async def check_pixels(port, page_url):
    with urlopen(f"http://127.0.0.1:{port}/json", timeout=5) as response:  # nosec B310
        tab = next(tab for tab in json.load(response) if tab["type"] == "page")
    async with websockets.connect(tab["webSocketDebuggerUrl"]) as ws:
        sequence = 0

        async def call(method, **params):
            nonlocal sequence
            sequence += 1
            await ws.send(json.dumps({"id": sequence, "method": method, "params": params}))
            while True:
                result = json.loads(await ws.recv())
                if result.get("id") == sequence:
                    assert "error" not in result, result
                    result = result["result"]
                    assert "exceptionDetails" not in result, result
                    return result

        await call("Page.enable")
        await call(
            "Page.addScriptToEvaluateOnNewDocument",
            source="""
            window.WebSocket = class {
              static OPEN = 1;
              constructor() {
                this.readyState = 1; window.testSocket = this;
                setTimeout(() => this.onopen?.(), 0);
              }
              send() {}
            };
        """,
        )
        await call("Page.navigate", url=page_url)
        for _ in range(100):
            ready = await call(
                "Runtime.evaluate",
                expression="!!document.querySelector('a-scene')?.renderer && !!window.testSocket?.onmessage",
                returnByValue=True,
            )
            if ready["result"].get("value"):
                break
            await asyncio.sleep(0.05)
        else:
            raise AssertionError("A-Frame/application did not load")
        result = await call("Runtime.evaluate", expression=PIXEL_CHECK, awaitPromise=True, returnByValue=True)
        rows = result["result"].get("value")
        assert isinstance(rows, list) and len(rows) == 48, result
        colors = {
            "forward": [[255, 0, 0], [0, 255, 0], [0, 0, 255], [255, 255, 0]],
            "wrist_left": [[0, 255, 255], [255, 0, 255], [255, 255, 255], [255, 0, 0]],
            "wrist_right": [[0, 0, 255], [255, 255, 255], [255, 0, 0], [0, 255, 0]],
        }
        for row in rows:
            selected = [name for i, name in enumerate(colors) if row["mask"] & (1 << i)]
            assert row["visible"] == selected, row
            assert row["error"] == 0, row
            for sample in row["samples"]:
                expected = colors[sample["name"]]
                if row["rotation"] == 180:
                    expected = expected[::-1]
                # Shader output dithering can move an 8-bit channel by one level.
                assert all(
                    abs(actual - wanted) <= 2
                    for pixel, reference in zip(sample["corners"], expected, strict=True)
                    for actual, wanted in zip(pixel, reference, strict=True)
                ), row
        print("PASS: all 8 camera selections × 6 resolution/rotation cases, correct pixels and no GPU errors")


def main():
    chrome = shutil.which("google-chrome") or shutil.which("chromium")
    if chrome is None:
        raise SystemExit("Chrome/Chromium is required for the GPU regression check")
    handler = functools.partial(StaticHandler, directory=str(STATIC))
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server, tempfile.TemporaryDirectory() as profile:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        command = [
            chrome,
            "--headless=new",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--use-angle=swiftshader",
            "--enable-unsafe-swiftshader",
            "--remote-debugging-port=0",
            f"--user-data-dir={profile}",
            "about:blank",
        ]
        with subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as browser:
            try:
                port_file = Path(profile) / "DevToolsActivePort"
                for _ in range(100):
                    if port_file.exists() and port_file.read_text().splitlines():
                        break
                    if browser.poll() is not None:
                        raise RuntimeError("Chrome exited before its debugger was ready")
                    time.sleep(0.05)
                port = int(port_file.read_text().splitlines()[0])
                page_url = f"http://127.0.0.1:{server.server_port}/"
                asyncio.run(asyncio.wait_for(check_pixels(port, page_url), timeout=20))
            finally:
                browser.terminate()
                try:
                    browser.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    browser.kill()
                server.shutdown()


if __name__ == "__main__":
    main()
