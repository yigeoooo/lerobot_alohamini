"""Offline GPU regression: run with uv run python tests/vr_gateway/check_video_render.py.

Requires Chrome/Chromium and websockets. Serves only the real static UI; no robot
gateway, camera or headset is opened. Pixel readback exercises A-Frame's complete
scene after camera resolution changes, including the optional 180-degree view.
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
  const image = document.getElementById('view');
  scene.pause();
  const renderer = scene.renderer;
  const target = new AFRAME.THREE.WebGLRenderTarget(400, 300);
  const camera = scene.camera;
  camera.aspect = 400 / 300;
  camera.updateProjectionMatrix();
  const results = [];
  try {
    for (const [width, height, rotation] of [
      [640, 480, 0], [1280, 720, 0], [480, 360, 0], [1280, 720, 0],
      [1280, 720, 180], [1280, 720, 0]
    ]) {
      const source = document.createElement('canvas');
      source.width = width; source.height = height;
      const ctx = source.getContext('2d');
      for (const [color, x, y] of [
        ['red', 0, 0], ['lime', width / 2, 0],
        ['blue', 0, height / 2], ['yellow', width / 2, height / 2]
      ]) {
        ctx.fillStyle = color; ctx.fillRect(x, y, width / 2, height / 2);
      }
      await new Promise((resolve, reject) => {
        image.addEventListener('load', resolve, {once: true});
        image.addEventListener('error', reject, {once: true});
        image.src = source.toDataURL();
      });
      document.getElementById('video-rotation').value = String(rotation);
      document.getElementById('settings-form').dispatchEvent(new Event('submit', {cancelable: true}));
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      scene.object3D.updateMatrixWorld(true);
      renderer.setRenderTarget(target);
      renderer.setViewport(0, 0, 400, 300);
      renderer.render(scene.object3D, camera);
      const pixels = new Uint8Array(400 * 300 * 4);
      renderer.readRenderTargetPixels(target, 0, 0, 400, 300, pixels);
      const at = (x, y) => Array.from(pixels.slice((y * 400 + x) * 4, (y * 400 + x) * 4 + 3));
      results.push({width, height, rotation, error: renderer.getContext().getError(),
        corners: [at(155, 180), at(245, 180), at(155, 120), at(245, 120)]});
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

        await call("Page.navigate", url=page_url)
        for _ in range(100):
            ready = await call(
                "Runtime.evaluate",
                expression="!!document.querySelector('a-scene')?.renderer && !!document.getElementById('view')?.onload",
                returnByValue=True,
            )
            if ready["result"].get("value"):
                break
            await asyncio.sleep(0.05)
        else:
            raise AssertionError("A-Frame/application did not load")
        result = await call("Runtime.evaluate", expression=PIXEL_CHECK, awaitPromise=True, returnByValue=True)
        rows = result["result"].get("value")
        assert isinstance(rows, list) and len(rows) == 6, result
        colors = [[255, 0, 0], [0, 255, 0], [0, 0, 255], [255, 255, 0]]
        for row in rows:
            expected = colors if row["rotation"] == 0 else colors[::-1]
            assert row["error"] == 0 and row["corners"] == expected, row
            print(f"PASS {row['width']}x{row['height']} rotation={row['rotation']}: four correct corners")


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
