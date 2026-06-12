#!/usr/bin/env python

# Copyright 2026 The HuggingFace Inc. team. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Local browser tool for reviewing, trimming, and deleting LeRobot episodes."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import torch
from PIL import Image

from lerobot.datasets import LeRobotDataset, delete_episodes, trim_episodes
from lerobot.utils.utils import init_logging

logger = logging.getLogger(__name__)


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LeRobot Dataset Curator</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #101214;
      --panel: #171a1d;
      --panel-2: #20252a;
      --border: #30363d;
      --text: #e8edf2;
      --muted: #9aa7b3;
      --accent: #4da3ff;
      --danger: #ef5b5b;
      --ok: #59c17a;
      --warn: #d7a74a;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.4 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      overflow: hidden;
    }

    button, input, select {
      font: inherit;
      color: inherit;
    }

    button, select, input[type="number"] {
      background: var(--panel-2);
      border: 1px solid var(--border);
      border-radius: 6px;
      min-height: 34px;
    }

    button {
      padding: 0 12px;
      cursor: pointer;
    }

    button.primary { background: var(--accent); border-color: var(--accent); color: #06111d; }
    button.danger { border-color: #7a2f34; color: #ffd7d7; }
    button:disabled { cursor: not-allowed; opacity: .5; }

    .app {
      display: grid;
      grid-template-columns: 300px 1fr;
      height: 100vh;
      height: 100dvh;
      min-height: 0;
      overflow: hidden;
    }

    aside {
      border-right: 1px solid var(--border);
      background: var(--panel);
      display: flex;
      flex-direction: column;
      min-width: 0;
      min-height: 0;
    }

    .topbar {
      padding: 14px;
      border-bottom: 1px solid var(--border);
      flex: 0 0 auto;
    }

    .title {
      font-size: 16px;
      font-weight: 700;
      margin-bottom: 8px;
    }

    .meta {
      color: var(--muted);
      font-size: 12px;
      word-break: break-word;
    }

    .episodes {
      flex: 1 1 auto;
      min-height: 0;
      overflow: auto;
      padding: 8px;
    }

    .episode {
      width: 100%;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 6px;
      text-align: left;
      padding: 9px 10px;
      margin-bottom: 6px;
      background: transparent;
      border: 1px solid transparent;
    }

    .episode.active {
      background: var(--panel-2);
      border-color: var(--accent);
    }

    .episode .small {
      color: var(--muted);
      font-size: 12px;
    }

    .badge {
      align-self: center;
      font-size: 11px;
      padding: 2px 6px;
      border-radius: 999px;
      border: 1px solid var(--border);
      color: var(--muted);
    }

    .badge.trimmed { color: #dbeeff; border-color: #275b8f; }
    .badge.deleted { color: #ffd7d7; border-color: #7a2f34; }

    main {
      display: grid;
      grid-template-rows: auto 1fr auto;
      min-width: 0;
      min-height: 0;
    }

    .toolbar, .statusbar {
      padding: 10px 14px;
      border-bottom: 1px solid var(--border);
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
    }

    .statusbar {
      border-top: 1px solid var(--border);
      border-bottom: 0;
      color: var(--muted);
      min-height: 42px;
    }

    .viewer {
      display: grid;
      grid-template-columns: minmax(0, 1fr) clamp(320px, 28vw, 480px);
      min-height: 0;
      overflow: hidden;
    }

    .frame-wrap {
      min-width: 0;
      min-height: 0;
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 12px;
      align-content: start;
      padding: 14px;
      background: #0b0d0f;
      overflow: auto;
    }

    .camera-card {
      min-width: 0;
      border: 1px solid var(--border);
      background: #050607;
    }

    .camera-title {
      padding: 7px 9px;
      border-bottom: 1px solid var(--border);
      color: var(--muted);
      font-size: 12px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .camera-card img,
    .camera-card canvas,
    .camera-card video {
      display: block;
      width: 100%;
      max-height: calc(100vh - 230px);
      height: auto;
      object-fit: contain;
      background: #050607;
    }

    .empty-view {
      color: var(--muted);
      align-self: center;
      justify-self: center;
      padding: 24px;
    }

    .side {
      border-left: 1px solid var(--border);
      padding: 14px;
      background: var(--panel);
      overflow: auto;
      min-width: 0;
      min-height: 0;
    }

    .group {
      margin-bottom: 18px;
    }

    .label {
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 6px;
    }

    .row {
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
      margin-bottom: 8px;
    }

    .row > * { flex: 1; }
    .row > button { flex: 0 0 auto; }

    input[type="range"] {
      width: 100%;
      accent-color: var(--accent);
    }

    input[type="number"] {
      width: 100%;
      padding: 0 8px;
    }

    .kv {
      display: grid;
      grid-template-columns: 88px 1fr;
      gap: 6px;
      color: var(--muted);
      font-size: 12px;
    }

    .kv strong {
      color: var(--text);
      font-weight: 500;
      min-width: 0;
      overflow-wrap: anywhere;
    }

    .frame-data {
      display: grid;
      gap: 10px;
      min-width: 0;
    }

    .frame-data-empty {
      color: var(--muted);
      font-size: 12px;
    }

    .frame-field {
      min-width: 0;
      border-top: 1px solid var(--border);
      padding-top: 8px;
    }

    .frame-field:first-child {
      border-top: 0;
      padding-top: 0;
    }

    .frame-field-title {
      margin-bottom: 6px;
      color: var(--text);
      font-size: 12px;
      font-weight: 600;
      overflow-wrap: anywhere;
    }

    .frame-values {
      display: grid;
      gap: 4px;
    }

    .frame-value {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      align-items: baseline;
      min-width: 0;
      font-size: 12px;
    }

    .frame-value span {
      min-width: 0;
      color: var(--muted);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .frame-value strong {
      color: var(--text);
      font: 500 12px/1.3 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      overflow-wrap: anywhere;
      text-align: right;
    }

    #status {
      min-width: 0;
      overflow-wrap: anywhere;
    }

    .progress {
      width: 180px;
      height: 8px;
      border: 1px solid var(--border);
      border-radius: 999px;
      overflow: hidden;
      background: #07090b;
      display: none;
    }

    .progress.visible {
      display: block;
    }

    .progress-bar {
      height: 100%;
      width: 0%;
      background: var(--accent);
      transition: width .2s ease;
    }

    .progress.indeterminate .progress-bar {
      width: 35%;
      animation: progress-slide 1.1s ease-in-out infinite;
    }

    @keyframes progress-slide {
      0% { transform: translateX(-120%); }
      100% { transform: translateX(300%); }
    }

    @media (max-width: 860px) {
      .app {
        grid-template-columns: 1fr;
        grid-template-rows: minmax(0, 260px) minmax(0, 1fr);
        height: 100vh;
        height: 100dvh;
        min-height: 0;
      }
      aside { max-height: none; border-right: 0; border-bottom: 1px solid var(--border); }
      .viewer {
        grid-template-columns: 1fr;
        grid-template-rows: minmax(220px, 1fr) minmax(220px, 38dvh);
      }
      .side {
        border-left: 0;
        border-top: 1px solid var(--border);
        display: grid;
        grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
        gap: 12px 14px;
        align-content: start;
        padding: 12px 14px;
      }
      .side .group { margin-bottom: 0; }
      .frame-data-group { grid-column: 1 / -1; }
      .camera-card img,
      .camera-card canvas,
      .camera-card video { max-height: 50vh; }
    }

    @media (max-width: 560px) {
      .side { grid-template-columns: 1fr; }
      .frame-data-group { grid-column: auto; }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside>
      <div class="topbar">
        <div class="title">Dataset Curator</div>
        <div id="datasetMeta" class="meta"></div>
      </div>
      <div id="episodes" class="episodes"></div>
    </aside>
    <main>
      <div class="toolbar">
        <button id="prev">Prev</button>
        <button id="play">Play</button>
        <button id="next">Next</button>
      </div>
      <div class="viewer">
        <div id="frames" class="frame-wrap"></div>
        <div class="side">
          <div class="group frame-controls-group">
            <span class="label">Frame</span>
            <input id="frameSlider" type="range" min="0" max="0" value="0">
            <div class="row">
              <input id="frameNumber" type="number" min="0" value="0">
              <button id="setStart">Start</button>
              <button id="setEnd">End</button>
            </div>
          </div>
          <div class="group keep-range-group">
            <span class="label">Keep Range</span>
            <div class="row">
              <input id="startFrame" type="number" min="0" value="0">
              <input id="endFrame" type="number" min="1" value="1">
            </div>
            <div class="row">
              <button id="saveRange" class="primary">Keep</button>
              <button id="deleteRange" class="danger">Delete Range</button>
              <button id="deleteEpisode" class="danger">Delete</button>
            </div>
          </div>
          <div class="group kv episode-info-group" id="episodeInfo"></div>
          <div class="group frame-data-group">
            <span class="label">Frame Data</span>
            <div id="frameData" class="frame-data"></div>
          </div>
        </div>
      </div>
      <div class="statusbar">
        <div id="progress" class="progress"><div id="progressBar" class="progress-bar"></div></div>
        <div id="status">开始处理：选择左侧 Episode，加载完成后可实时播放；修改会立即覆盖源数据。</div>
      </div>
    </main>
  </div>
<script>
let data = null;
let currentEpisode = 0;
let currentFrame = 0;
let playing = false;
let playRaf = null;
let playStartTime = 0;
let playStartFrame = 0;
let renderedCameraKey = "";
let episodeLoadToken = 0;
let datasetLoadVersion = 0;
let episodeCache = null;
let episodeCaches = new Map();
let frameDataCache = new Map();
let busy = false;
const PRELOAD_FRAME_WORKERS = 3;
const FRAME_DATA_SKIP_KEYS = new Set(["episode_index", "task_index"]);

const els = {
  datasetMeta: document.getElementById("datasetMeta"),
  episodes: document.getElementById("episodes"),
  frames: document.getElementById("frames"),
  frameSlider: document.getElementById("frameSlider"),
  frameNumber: document.getElementById("frameNumber"),
  startFrame: document.getElementById("startFrame"),
  endFrame: document.getElementById("endFrame"),
  episodeInfo: document.getElementById("episodeInfo"),
  frameData: document.getElementById("frameData"),
  status: document.getElementById("status"),
  progress: document.getElementById("progress"),
  progressBar: document.getElementById("progressBar"),
  prev: document.getElementById("prev"),
  play: document.getElementById("play"),
  next: document.getElementById("next"),
  setStart: document.getElementById("setStart"),
  setEnd: document.getElementById("setEnd"),
  saveRange: document.getElementById("saveRange"),
  deleteRange: document.getElementById("deleteRange"),
  deleteEpisode: document.getElementById("deleteEpisode"),
};

async function api(path, options) {
  const res = await fetch(path, options);
  const contentType = res.headers.get("content-type") || "";
  const body = contentType.includes("application/json") ? await res.json() : await res.text();
  if (!res.ok) {
    throw new Error(body.error || body || res.statusText);
  }
  return body;
}

async function loadData() {
  installDataset(await api("/api/dataset"));
  await loadSelectedEpisode(currentEpisode);
}

function installDataset(payload) {
  data = payload;
  datasetLoadVersion += 1;
  episodeCache = null;
  episodeCaches = new Map();
  frameDataCache = new Map();
  updateDatasetMeta();
  renderEpisodes();
}

function updateDatasetMeta() {
  els.datasetMeta.textContent =
    `${data.repo_id} | ${data.total_episodes} episodes | ${data.total_frames} frames | `
    + `${data.fps} fps | edit ${data.edit_version} | root: ${data.root}`;
}

function setProgress(visible, percent = 0, indeterminate = false) {
  if (visible) {
    els.progress.classList.add("visible");
  } else {
    els.progress.classList.remove("visible");
  }
  els.progress.classList.toggle("indeterminate", indeterminate);
  els.progressBar.style.width = `${Math.max(0, Math.min(100, percent))}%`;
}

function setEpisodeControlsDisabled(disabled) {
  const noEpisode = !currentMeta();
  const noVisualFrames = !data || previewCameraKeys().length === 0;
  els.prev.disabled = disabled || noEpisode || currentEpisode <= 0;
  els.next.disabled = disabled || noEpisode || currentEpisode >= data.episodes.length - 1;
  els.play.disabled = disabled || noEpisode || noVisualFrames;
  els.frameSlider.disabled = disabled || noEpisode;
  els.frameNumber.disabled = disabled || noEpisode;
  els.startFrame.disabled = disabled || noEpisode;
  els.endFrame.disabled = disabled || noEpisode;
  els.setStart.disabled = disabled || noEpisode;
  els.setEnd.disabled = disabled || noEpisode;
  els.saveRange.disabled = disabled || noEpisode;
  els.deleteRange.disabled = disabled || noEpisode;
  els.deleteEpisode.disabled = disabled || noEpisode || data.total_episodes <= 1;
}

function renderEmptyDataset(message) {
  stopPlayback();
  currentEpisode = 0;
  currentFrame = 0;
  renderedCameraKey = "";
  els.frames.innerHTML = `<div class="empty-view">${message}</div>`;
  els.episodeInfo.innerHTML = "";
  renderFrameData(null);
  els.frameSlider.max = 0;
  els.frameSlider.value = 0;
  els.frameNumber.max = 0;
  els.frameNumber.value = 0;
  setEpisodeControlsDisabled(true);
  setProgress(false, 0);
  els.status.textContent = message;
}

async function loadSelectedEpisode(preferredIndex, doneStatus = null) {
  if (!data || data.episodes.length === 0) {
    renderEmptyDataset("没有可处理的 Episode。");
    return;
  }
  const index = Math.max(0, Math.min(data.episodes.length - 1, Number(preferredIndex) || 0));
  await loadEpisode(index, doneStatus);
}

function renderEpisodes() {
  els.episodes.innerHTML = "";
  const deleted = data.deleted || [];
  const edits = data.edits || {};
  for (const ep of data.episodes) {
    const btn = document.createElement("button");
    btn.className = "episode" + (ep.index === currentEpisode ? " active" : "");
    btn.disabled = busy;
    const status = deleted.includes(ep.index) ? "deleted" : (edits[ep.index] ? "trimmed" : "");
    btn.innerHTML = `
      <div>
        <div>Episode ${ep.index}</div>
        <div class="small">${ep.length} frames | ${ep.duration_s.toFixed(2)} s</div>
      </div>
      <span class="badge ${status}">${status || "keep"}</span>
    `;
    btn.onclick = () => loadEpisode(ep.index);
    els.episodes.appendChild(btn);
  }
}

function currentMeta() {
  if (!data) return null;
  return data.episodes.find((ep) => ep.index === currentEpisode);
}

function useVideoPreview() {
  const ep = currentMeta();
  return Boolean(
    data?.video_keys?.length
    && data.video_keys.length === data.camera_keys.length
    && ep?.videos
  );
}

function previewCameraKeys() {
  if (!data) return [];
  return useVideoPreview() ? data.video_keys : data.camera_keys;
}

function getSavedRange(ep) {
  const edit = (data.edits || {})[ep.index];
  if (!edit || edit.length === 0) return [0, ep.length];
  return [edit[0][0], edit[edit.length - 1][1]];
}

function formatRanges(ranges) {
  if (!ranges || ranges.length === 0) return "deleted";
  return ranges.map((range) => `${range[0]}-${range[1]}`).join(", ");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function loadEpisode(index, doneStatus = null) {
  if (!data || data.episodes.length === 0) return;
  stopPlayback();
  const loadToken = ++episodeLoadToken;
  currentEpisode = index;
  const ep = currentMeta();
  currentFrame = 0;
  episodeCache = null;
  els.frameSlider.max = Math.max(0, ep.length - 1);
  els.frameSlider.value = currentFrame;
  els.frameNumber.max = Math.max(0, ep.length - 1);
  els.frameNumber.value = currentFrame;
  const [start, end] = getSavedRange(ep);
  els.startFrame.max = Math.max(0, ep.length - 1);
  els.endFrame.max = ep.length;
  els.startFrame.value = start;
  els.endFrame.value = end;
  renderEpisodeInfo(ep);
  renderFrameData(null);
  renderEpisodes();
  ensureCameraCards();
  loadFrameData(ep, loadToken).then((payload) => {
    if (loadToken !== episodeLoadToken || !payload) return;
    renderFrameDataForCurrentFrame();
  }).catch((err) => {
    if (loadToken !== episodeLoadToken) return;
    renderFrameDataError(err.message);
  });
  if (previewCameraKeys().length === 0) {
    setEpisodeControlsDisabled(false);
    renderFrame();
    return;
  }
  if (useVideoPreview()) {
    setEpisodeControlsDisabled(false);
    setProgress(false, 0);
    renderFrame();
    els.status.textContent = doneStatus || `Episode ${ep.index} 可直接播放视频，无需预加载。`;
    return;
  }

  setEpisodeControlsDisabled(true);
  setProgress(true, 0);
  els.status.textContent = `开始处理：正在一次性加载 Episode ${ep.index} 的 ${ep.length} 帧...`;
  try {
    episodeCache = await preloadEpisode(ep, loadToken);
    if (loadToken !== episodeLoadToken || !episodeCache) return;
    setEpisodeControlsDisabled(false);
    setProgress(false, 0);
    renderFrame();
    els.status.textContent = doneStatus || `Episode ${ep.index} 已加载完成，可以实时播放。`;
  } catch (err) {
    if (loadToken !== episodeLoadToken) return;
    setEpisodeControlsDisabled(false);
    setProgress(false, 0);
    els.status.textContent = err.message;
  }
}

function episodeCacheKey(index) {
  return `${datasetLoadVersion}:${index}`;
}

function frameUrl(episode, frame, camera) {
  return `/api/frame?episode=${episode}&frame=${frame}&camera=${encodeURIComponent(camera)}&v=${datasetLoadVersion}`;
}

function videoUrl(episode, camera) {
  return `/api/video?episode=${episode}&camera=${encodeURIComponent(camera)}&v=${datasetLoadVersion}`;
}

function frameDataUrl(episode) {
  return `/api/frame-data?episode=${episode}&v=${datasetLoadVersion}`;
}

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = async () => {
      try {
        if (image.decode) await image.decode();
      } catch (_) {
        // onload already guarantees the frame is available for drawing.
      }
      resolve(image);
    };
    image.onerror = () => reject(new Error(`无法加载画面：${url}`));
    image.src = url;
  });
}

async function preloadFrame(cache, ep, frame, loadToken) {
  const frameCache = cache.frames[frame];
  await Promise.all(data.camera_keys.map(async (camera) => {
    const image = await loadImage(frameUrl(ep.index, frame, camera));
    if (loadToken === episodeLoadToken) {
      frameCache.set(camera, image);
    }
  }));
}

async function preloadEpisode(ep, loadToken) {
  const key = episodeCacheKey(ep.index);
  const cached = episodeCaches.get(key);
  if (cached && cached.frameCount === ep.length) return cached;

  const cache = {
    key,
    episode: ep.index,
    frameCount: ep.length,
    frames: Array.from({length: ep.length}, () => new Map()),
  };

  if (ep.length === 0 || data.camera_keys.length === 0) {
    episodeCaches.set(key, cache);
    return cache;
  }

  let nextFrame = 0;
  let loadedFrames = 0;
  const workerCount = Math.min(PRELOAD_FRAME_WORKERS, ep.length);
  const updateLoadingStatus = () => {
    const percent = (loadedFrames / ep.length) * 100;
    setProgress(true, percent);
    els.status.textContent = `开始处理：正在加载 Episode ${ep.index}: ${loadedFrames}/${ep.length} 帧`;
  };
  updateLoadingStatus();

  async function worker() {
    while (loadToken === episodeLoadToken) {
      const frame = nextFrame;
      nextFrame += 1;
      if (frame >= ep.length) return;
      await preloadFrame(cache, ep, frame, loadToken);
      loadedFrames += 1;
      if (loadToken === episodeLoadToken) updateLoadingStatus();
    }
  }

  await Promise.all(Array.from({length: workerCount}, () => worker()));
  if (loadToken !== episodeLoadToken) return null;
  episodeCaches.set(key, cache);
  return cache;
}

function getCurrentEpisodeCache() {
  const key = episodeCacheKey(currentEpisode);
  if (episodeCache && episodeCache.key === key) return episodeCache;
  return episodeCaches.get(key) || null;
}

function getCurrentFrameDataCache() {
  return frameDataCache.get(episodeCacheKey(currentEpisode)) || null;
}

async function loadFrameData(ep, loadToken) {
  const key = episodeCacheKey(ep.index);
  const cached = frameDataCache.get(key);
  if (cached && cached.frameCount === ep.length) return cached;

  const payload = await api(frameDataUrl(ep.index));
  if (loadToken !== episodeLoadToken) return null;
  const cache = {
    key,
    episode: ep.index,
    frameCount: ep.length,
    fields: payload.fields || [],
    frames: payload.frames || [],
  };
  frameDataCache.set(key, cache);
  return cache;
}

function formatFrameValue(value) {
  if (Array.isArray(value)) return JSON.stringify(value);
  if (value && typeof value === "object") return JSON.stringify(value);
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return String(value);
    const abs = Math.abs(value);
    return abs !== 0 && (abs < 0.001 || abs >= 10000) ? value.toExponential(3) : value.toFixed(4);
  }
  if (typeof value === "boolean") return value ? "true" : "false";
  if (value === null || value === undefined) return "";
  return String(value);
}

function featureValueNames(field, value) {
  const names = field.names;
  if (Array.isArray(value)) {
    if (Array.isArray(names)) return names;
    if (names && typeof names === "object") {
      const ordered = Array(value.length).fill(null);
      for (const [name, idx] of Object.entries(names)) {
        if (Number.isInteger(idx) && idx >= 0 && idx < value.length) ordered[idx] = name;
      }
      return ordered.map((name, idx) => name || `[${idx}]`);
    }
    return value.map((_, idx) => `[${idx}]`);
  }
  return [field.key];
}

function renderFrameData(payload) {
  if (!payload) {
    els.frameData.innerHTML = `<div class="frame-data-empty">Loading frame data...</div>`;
    return;
  }
  const fields = payload.fields || [];
  const values = payload.values || {};
  if (fields.length === 0) {
    els.frameData.innerHTML = `<div class="frame-data-empty">No low-dimensional fields.</div>`;
    return;
  }

  els.frameData.innerHTML = fields.map((field) => {
    const rawValue = values[field.key];
    const valueList = Array.isArray(rawValue) ? rawValue : [rawValue];
    const names = featureValueNames(field, rawValue);
    const rows = valueList.map((value, idx) => `
      <div class="frame-value">
        <span title="${escapeHtml(names[idx] || `[${idx}]`)}">${escapeHtml(names[idx] || `[${idx}]`)}</span>
        <strong>${escapeHtml(formatFrameValue(value))}</strong>
      </div>
    `).join("");
    return `
      <div class="frame-field">
        <div class="frame-field-title">${escapeHtml(field.key)}</div>
        <div class="frame-values">${rows}</div>
      </div>
    `;
  }).join("");
}

function renderFrameDataError(message) {
  els.frameData.innerHTML = `<div class="frame-data-empty">${escapeHtml(message)}</div>`;
}

function renderFrameDataForCurrentFrame() {
  const cache = getCurrentFrameDataCache();
  if (!cache) {
    renderFrameData(null);
    return;
  }
  renderFrameData({
    fields: cache.fields,
    values: cache.frames[currentFrame] || {},
  });
}

function drawImageToCanvas(canvas, image) {
  const width = image.naturalWidth || image.width;
  const height = image.naturalHeight || image.height;
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  const ctx = canvas.getContext("2d");
  ctx.drawImage(image, 0, 0, width, height);
}

function updateFrameControls(frame) {
  els.frameSlider.value = frame;
  els.frameNumber.value = frame;
  renderFrameDataForCurrentFrame();
}

function renderEpisodeInfo(ep) {
  const edits = data.edits || {};
  const deleted = (data.deleted || []).includes(ep.index);
  const ranges = edits[ep.index] || [[0, ep.length]];
  els.episodeInfo.innerHTML = `
    <span>Status</span><strong>${deleted ? "deleted" : (edits[ep.index] ? "trimmed" : "current")}</strong>
    <span>Length</span><strong>${ep.length}</strong>
    <span>Keep</span><strong>${formatRanges(ranges)}</strong>
    <span>Task</span><strong>${escapeHtml(ep.tasks.join("; "))}</strong>
  `;
}

function ensureCameraCards() {
  const mode = useVideoPreview() ? "video" : "frames";
  const cameras = previewCameraKeys();
  const cameraKey = `${mode}:${cameras.join("|")}`;
  const selector = mode === "video" ? "video[data-camera]" : "canvas[data-camera]";
  if (renderedCameraKey === cameraKey && els.frames.querySelectorAll(selector).length > 0) {
    return;
  }
  renderedCameraKey = cameraKey;
  if (mode === "video") {
    els.frames.innerHTML = cameras.map((camera) => `
    <div class="camera-card">
      <div class="camera-title">${escapeHtml(camera)}</div>
      <video data-camera="${escapeHtml(camera)}" muted playsinline preload="metadata"></video>
    </div>
  `).join("");
    return;
  }
  els.frames.innerHTML = cameras.map((camera) => `
    <div class="camera-card">
      <div class="camera-title">${escapeHtml(camera)}</div>
      <canvas data-camera="${escapeHtml(camera)}"></canvas>
    </div>
  `).join("");
}

function renderFrame() {
  const episode = currentEpisode;
  const frame = currentFrame;
  const ep = currentMeta();
  if (!ep) {
    els.frames.innerHTML = `<div class="empty-view">No camera frames in this dataset.</div>`;
    renderedCameraKey = "";
    return;
  }
  if (previewCameraKeys().length === 0) {
    els.frames.innerHTML = `<div class="empty-view">No camera frames in this dataset.</div>`;
    renderedCameraKey = "";
    updateFrameControls(frame);
    els.status.textContent = `Episode ${episode}, frame ${frame}`;
    return;
  }
  if (useVideoPreview()) {
    renderVideoFrame(ep, frame);
    return;
  }
  ensureCameraCards();
  const cache = getCurrentEpisodeCache();
  if (!cache) {
    updateFrameControls(frame);
    els.status.textContent = `Episode ${episode} 正在加载，加载完成后再播放。`;
    return;
  }
  const frameCache = cache.frames[frame];
  for (const canvas of els.frames.querySelectorAll("canvas[data-camera]")) {
    const image = frameCache.get(canvas.dataset.camera);
    if (image) drawImageToCanvas(canvas, image);
  }
  updateFrameControls(frame);
  els.status.textContent = `Episode ${episode}, frame ${frame}`;
}

function setVideoElementFrame(video, ep, frame) {
  const camera = video.dataset.camera;
  const meta = ep.videos[camera];
  if (!meta) return null;
  const src = videoUrl(ep.index, camera);
  if (video.dataset.src !== src) {
    video.src = src;
    video.dataset.src = src;
  }
  const fps = Math.max(1, Number(data.fps) || 1);
  const targetTime = Math.min(meta.to_timestamp, meta.from_timestamp + frame / fps);
  const seek = () => {
    if (Number.isFinite(targetTime) && Math.abs(video.currentTime - targetTime) > 0.001) {
      video.currentTime = targetTime;
    }
  };
  if (video.readyState >= 1) {
    seek();
  } else {
    video.addEventListener("loadedmetadata", seek, {once: true});
  }
  return targetTime;
}

function renderVideoFrame(ep, frame) {
  ensureCameraCards();
  for (const video of els.frames.querySelectorAll("video[data-camera]")) {
    if (!playing) video.pause();
    setVideoElementFrame(video, ep, frame);
  }
  updateFrameControls(frame);
  els.status.textContent = `Episode ${ep.index}, frame ${frame}`;
}

function waitForVideoMetadata(video) {
  if (video.readyState >= 1) return Promise.resolve();
  return new Promise((resolve, reject) => {
    video.addEventListener("loadedmetadata", resolve, {once: true});
    video.addEventListener("error", () => reject(new Error(`无法加载视频：${video.dataset.camera}`)), {once: true});
  });
}

function waitForVideoSeek(video, targetTime) {
  if (!Number.isFinite(targetTime)) return Promise.resolve();
  if (Math.abs(video.currentTime - targetTime) <= 0.001) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      video.removeEventListener("seeked", onSeeked);
      video.removeEventListener("canplay", onCanPlay);
      video.removeEventListener("error", onError);
    };
    const done = () => {
      cleanup();
      resolve();
    };
    const onSeeked = () => done();
    const onCanPlay = () => {
      if (Math.abs(video.currentTime - targetTime) <= 0.02) done();
    };
    const onError = () => {
      cleanup();
      reject(new Error(`无法定位视频：${video.dataset.camera}`));
    };
    video.addEventListener("seeked", onSeeked, {once: true});
    video.addEventListener("canplay", onCanPlay);
    video.addEventListener("error", onError, {once: true});
  });
}

function videoElements() {
  return Array.from(els.frames.querySelectorAll("video[data-camera]"));
}

async function prepareVideosForPlayback(ep, frame) {
  ensureCameraCards();
  const videos = videoElements();
  for (const video of videos) {
    setVideoElementFrame(video, ep, frame);
  }
  await Promise.all(videos.map(waitForVideoMetadata));
  const targets = videos.map((video) => setVideoElementFrame(video, ep, frame));
  await Promise.all(videos.map((video, idx) => waitForVideoSeek(video, targets[idx])));
  return videos;
}

function frameFromVideoTime(video, ep) {
  const meta = ep.videos[video.dataset.camera];
  if (!meta) return currentFrame;
  const fps = Math.max(1, Number(data.fps) || 1);
  return clampFrame(Math.floor((video.currentTime - meta.from_timestamp) * fps + 1e-6));
}

function syncVideosToFrame(ep, frame) {
  const fps = Math.max(1, Number(data.fps) || 1);
  const tolerance = Math.max(0.08, 2 / fps);
  for (const video of videoElements()) {
    const meta = ep.videos[video.dataset.camera];
    if (!meta) continue;
    const targetTime = Math.min(meta.to_timestamp, meta.from_timestamp + frame / fps);
    if (Math.abs(video.currentTime - targetTime) > tolerance) {
      video.currentTime = targetTime;
    }
  }
}

async function postEdit(payload, doneStatus) {
  const selectedBefore = currentEpisode;
  stopPlayback();
  episodeLoadToken++;
  busy = true;
  renderEpisodes();
  setEpisodeControlsDisabled(true);
  setProgress(true, 35, true);
  els.status.textContent = "开始处理：正在覆盖源数据集...";
  try {
    const result = await api("/api/edit", {
      method: "POST",
      headers: {"content-type": "application/json"},
      body: JSON.stringify(payload),
    });
    installDataset(result);
    const selected = Number.isInteger(result.selected_episode)
      ? result.selected_episode
      : Math.min(selectedBefore, data.episodes.length - 1);
    busy = false;
    await loadSelectedEpisode(selected, `${doneStatus}，已覆盖：${data.root}`);
  } catch (err) {
    busy = false;
    renderEpisodes();
    setEpisodeControlsDisabled(false);
    setProgress(false, 0);
    els.status.textContent = err.message;
  }
}

function clampFrame(value) {
  const ep = currentMeta();
  if (!ep || ep.length <= 0) return 0;
  return Math.max(0, Math.min(ep.length - 1, Number(value) || 0));
}

function seekFrame(value) {
  stopPlayback();
  currentFrame = clampFrame(value);
  renderFrame();
}

els.frameSlider.oninput = (e) => { seekFrame(e.target.value); };
els.frameNumber.onchange = (e) => { seekFrame(e.target.value); };
els.prev.onclick = () => loadEpisode(Math.max(0, currentEpisode - 1));
els.next.onclick = () => loadEpisode(Math.min(data.episodes.length - 1, currentEpisode + 1));
els.setStart.onclick = () => { els.startFrame.value = currentFrame; };
els.setEnd.onclick = () => { els.endFrame.value = Math.min(currentMeta().length, currentFrame + 1); };

els.saveRange.onclick = async () => {
  const ep = currentMeta();
  const start = Number(els.startFrame.value);
  const end = Number(els.endFrame.value);
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end > ep.length || start >= end) {
    els.status.textContent = `Invalid range for episode ${ep.index}`;
    return;
  }
  await postEdit({episode: ep.index, start, end}, `Episode ${ep.index} 已保留 ${start} - ${end}`);
};

els.deleteRange.onclick = async () => {
  const ep = currentMeta();
  const start = Number(els.startFrame.value);
  const end = Number(els.endFrame.value);
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end > ep.length || start >= end) {
    els.status.textContent = `Invalid delete range for episode ${ep.index}`;
    return;
  }
  await postEdit(
    {episode: ep.index, delete_start: start, delete_end: end},
    `Episode ${ep.index} 已删除 ${start} - ${end}，前后画面已拼接`
  );
};

els.deleteEpisode.onclick = async () => {
  const ep = currentMeta();
  await postEdit({episode: ep.index, delete: true}, `Episode ${ep.index} 已删除`);
};

function stopPlayback() {
  if (playRaf !== null) {
    cancelAnimationFrame(playRaf);
    playRaf = null;
  }
  for (const video of videoElements()) {
    video.pause();
  }
  playing = false;
  els.play.textContent = "Play";
}

function playbackStep(now) {
  if (!playing) return;
  const ep = currentMeta();
  if (!ep || ep.length === 0) {
    stopPlayback();
    return;
  }
  if (useVideoPreview()) {
    const primary = videoElements()[0];
    const primaryMeta = primary ? ep.videos[primary.dataset.camera] : null;
    if (!primary || !primaryMeta) {
      stopPlayback();
      return;
    }
    const fps = Math.max(1, Number(data.fps) || 1);
    if (primary.currentTime >= primaryMeta.to_timestamp - 0.5 / fps || primary.ended) {
      currentFrame = 0;
      syncVideosToFrame(ep, currentFrame);
      for (const video of videoElements()) {
        video.play().catch(() => {});
      }
    } else {
      currentFrame = frameFromVideoTime(primary, ep);
      syncVideosToFrame(ep, currentFrame);
    }
    updateFrameControls(currentFrame);
    els.status.textContent = `Episode ${ep.index}, frame ${currentFrame}`;
    playRaf = requestAnimationFrame(playbackStep);
    return;
  }
  const fps = Math.max(1, Number(data.fps) || 1);
  const elapsedFrames = Math.floor(((now - playStartTime) / 1000) * fps);
  const nextFrame = (playStartFrame + elapsedFrames) % ep.length;
  if (nextFrame !== currentFrame) {
    currentFrame = nextFrame;
    renderFrame();
  }
  playRaf = requestAnimationFrame(playbackStep);
}

els.play.onclick = async () => {
  if (playing) {
    stopPlayback();
    return;
  }
  const ep = currentMeta();
  if (useVideoPreview()) {
    try {
      const videos = await prepareVideosForPlayback(ep, currentFrame);
      playing = true;
      els.play.textContent = "Pause";
      await Promise.all(videos.map((video) => video.play()));
      playRaf = requestAnimationFrame(playbackStep);
    } catch (err) {
      stopPlayback();
      els.status.textContent = err.message;
    }
    return;
  }
  if (!getCurrentEpisodeCache()) {
    els.status.textContent = `Episode ${currentEpisode} 还没有加载完成。`;
    return;
  }
  const fps = Math.max(1, Number(data.fps) || 1);
  playStartFrame = currentFrame;
  playStartTime = performance.now() - 1000 / fps;
  playing = true;
  els.play.textContent = "Pause";
  renderFrame();
  playRaf = requestAnimationFrame(playbackStep);
};

loadData().catch((err) => {
  els.status.textContent = err.message;
});
</script>
</body>
</html>
"""


class CuratorState:
    def __init__(
        self,
        dataset: LeRobotDataset,
        repo_id: str,
        video_backend: str | None,
    ) -> None:
        self.dataset = dataset
        self.repo_id = repo_id
        self.root = dataset.root
        self.video_backend = video_backend
        self.edit_version = 0
        self.lock = threading.RLock()

    def dataset_payload(self) -> dict:
        with self.lock:
            self.dataset.meta.ensure_readable()
            episodes = []
            for idx in range(self.dataset.meta.total_episodes):
                ep = self.dataset.meta.episodes[idx]
                videos = {}
                for video_key in self.dataset.meta.video_keys:
                    videos[video_key] = {
                        "from_timestamp": float(ep[f"videos/{video_key}/from_timestamp"]),
                        "to_timestamp": float(ep[f"videos/{video_key}/to_timestamp"]),
                    }
                episodes.append(
                    {
                        "index": idx,
                        "length": int(ep["length"]),
                        "duration_s": int(ep["length"]) / self.dataset.meta.fps,
                        "tasks": list(ep["tasks"]),
                        "videos": videos,
                    }
                )

            return {
                "repo_id": self.dataset.repo_id,
                "root": str(self.dataset.root),
                "fps": self.dataset.meta.fps,
                "total_episodes": self.dataset.meta.total_episodes,
                "total_frames": self.dataset.meta.total_frames,
                "camera_keys": list(self.dataset.meta.camera_keys),
                "video_keys": list(self.dataset.meta.video_keys),
                "episodes": episodes,
                "edits": {},
                "deleted": [],
                "mode": "in_place",
                "edit_version": self.edit_version,
            }

    def update_edit(self, payload: dict) -> dict:
        with self.lock:
            self.dataset.meta.ensure_readable()
            episode = int(payload["episode"])
            self._validate_episode(episode)

            if payload.get("reset"):
                return self.dataset_payload()

            if payload.get("delete"):
                self._validate_can_delete_episode()
                selected_episode = min(episode, self.dataset.meta.total_episodes - 2)
                return self._rewrite_source(
                    delete_episode_indices=[episode],
                    selected_episode=selected_episode,
                )

            if "delete_start" in payload or "delete_end" in payload:
                start = int(payload["delete_start"])
                end = int(payload["delete_end"])
                self._validate_range(episode, start, end)
                if start == 0 and end == int(self.dataset.meta.episodes[episode]["length"]):
                    self._validate_can_delete_episode()
                    selected_episode = min(episode, self.dataset.meta.total_episodes - 2)
                    return self._rewrite_source(
                        delete_episode_indices=[episode],
                        selected_episode=selected_episode,
                    )
                return self._rewrite_source(
                    episode_delete_ranges={episode: (start, end)},
                    selected_episode=episode,
                )

            start = int(payload["start"])
            end = int(payload["end"])
            self._validate_range(episode, start, end)

            if start == 0 and end == int(self.dataset.meta.episodes[episode]["length"]):
                payload = self.dataset_payload()
                payload["selected_episode"] = episode
                return payload

            return self._rewrite_source(
                episode_ranges={episode: (start, end)},
                selected_episode=episode,
            )

    def frame_jpeg(self, episode: int, frame: int, camera: str) -> bytes:
        with self.lock:
            self.dataset.meta.ensure_readable()
            self._validate_episode(episode)
            if camera not in self.dataset.meta.camera_keys:
                raise ValueError(f"Camera '{camera}' not found")
            length = int(self.dataset.meta.episodes[episode]["length"])
            if frame < 0 or frame >= length:
                raise ValueError(f"Frame {frame} out of range for episode {episode}")

            dataset_index = int(self.dataset.meta.episodes[episode]["dataset_from_index"]) + frame
            item = self.dataset[dataset_index]
            image = _to_pil_image(item[camera])
            buf = BytesIO()
            image.save(buf, format="JPEG", quality=85)
            return buf.getvalue()

    def video_file_path(self, episode: int, camera: str) -> Path:
        with self.lock:
            self.dataset.meta.ensure_readable()
            self._validate_episode(episode)
            if camera not in self.dataset.meta.video_keys:
                raise ValueError(f"Video camera '{camera}' not found")

            video_path = self.dataset.root / self.dataset.meta.get_video_file_path(episode, camera)
            video_path = video_path.resolve()
            root = self.dataset.root.resolve()
            if not video_path.is_relative_to(root):
                raise ValueError(f"Video path escapes dataset root: {video_path}")
            if not video_path.exists():
                raise ValueError(f"Video file not found: {video_path}")
            return video_path

    def frame_data(self, episode: int) -> dict:
        with self.lock:
            self.dataset.meta.ensure_readable()
            self._validate_episode(episode)

            ep = self.dataset.meta.episodes[episode]
            start = int(ep["dataset_from_index"])
            length = int(ep["length"])
            fields = self._low_dimensional_fields()
            frames = []

            if length > 0 and fields:
                rows = self.dataset.hf_dataset.select(range(start, start + length))
                for row in rows:
                    frames.append({field["key"]: _jsonable_frame_value(row[field["key"]]) for field in fields})
            else:
                frames = [{} for _ in range(length)]

            return {
                "episode": episode,
                "frame_count": length,
                "fields": fields,
                "frames": frames,
            }

    def _low_dimensional_fields(self) -> list[dict]:
        fields = []
        for key, feature in self.dataset.meta.features.items():
            dtype = feature.get("dtype")
            if dtype in {"image", "video", "string", "language"} or key in _FRAME_DATA_SKIP_KEYS:
                continue
            fields.append(
                {
                    "key": key,
                    "dtype": dtype,
                    "shape": _jsonable_metadata_value(feature.get("shape")),
                    "names": _jsonable_metadata_value(feature.get("names")),
                }
            )
        return fields

    def _validate_episode(self, episode: int) -> None:
        if episode < 0 or episode >= self.dataset.meta.total_episodes:
            raise ValueError(f"Episode {episode} out of range")

    def _validate_range(self, episode: int, start: int, end: int) -> None:
        length = int(self.dataset.meta.episodes[episode]["length"])
        if start < 0 or end > length or start >= end:
            raise ValueError(f"Invalid range [{start}, {end}) for episode {episode} with length {length}")

    def _validate_can_delete_episode(self) -> None:
        if self.dataset.meta.total_episodes <= 1:
            raise ValueError("Cannot delete the only remaining episode")

    def _rewrite_source(
        self,
        selected_episode: int,
        episode_ranges: dict[int, tuple[int, int] | list[tuple[int, int]]] | None = None,
        episode_delete_ranges: dict[int, tuple[int, int] | list[tuple[int, int]]] | None = None,
        delete_episode_indices: list[int] | None = None,
    ) -> dict:
        source_dataset = self.dataset
        source_root = source_dataset.root
        tmp_root = self._unique_sibling_path(source_root, "curate-tmp")
        backup_root = self._unique_sibling_path(source_root, "curate-backup")
        source_moved = False

        try:
            self._rewrite_source_with_tool(
                source_dataset,
                tmp_root,
                episode_ranges=episode_ranges,
                episode_delete_ranges=episode_delete_ranges,
                delete_episode_indices=delete_episode_indices,
            )
            shutil.move(source_root, backup_root)
            source_moved = True
            shutil.move(tmp_root, source_root)
            self.dataset = self._open_dataset()
            self.root = self.dataset.root
            self.edit_version += 1
            shutil.rmtree(backup_root)
        except Exception:
            if source_moved and source_root.exists():
                failed_root = self._unique_sibling_path(source_root, "curate-failed")
                shutil.move(source_root, failed_root)
            if source_moved and backup_root.exists():
                shutil.move(backup_root, source_root)
                self.dataset = self._open_dataset()
                self.root = self.dataset.root
            raise
        finally:
            if tmp_root.exists():
                shutil.rmtree(tmp_root)

        payload = self.dataset_payload()
        if payload["total_episodes"] > 0:
            payload["selected_episode"] = max(0, min(selected_episode, payload["total_episodes"] - 1))
        return payload

    def _rewrite_source_with_tool(
        self,
        source_dataset: LeRobotDataset,
        output_dir: Path,
        episode_ranges: dict[int, tuple[int, int] | list[tuple[int, int]]] | None = None,
        episode_delete_ranges: dict[int, tuple[int, int] | list[tuple[int, int]]] | None = None,
        delete_episode_indices: list[int] | None = None,
    ) -> None:
        if self._can_use_delete_episodes(
            episode_ranges=episode_ranges,
            episode_delete_ranges=episode_delete_ranges,
            delete_episode_indices=delete_episode_indices,
        ):
            delete_episodes(
                source_dataset,
                episode_indices=delete_episode_indices or [],
                output_dir=output_dir,
                repo_id=source_dataset.repo_id,
            )
            return

        trim_episodes(
            source_dataset,
            episode_ranges=episode_ranges,
            episode_delete_ranges=episode_delete_ranges,
            delete_episode_indices=delete_episode_indices,
            output_dir=output_dir,
            repo_id=source_dataset.repo_id,
        )

    @staticmethod
    def _can_use_delete_episodes(
        episode_ranges: dict[int, tuple[int, int] | list[tuple[int, int]]] | None = None,
        episode_delete_ranges: dict[int, tuple[int, int] | list[tuple[int, int]]] | None = None,
        delete_episode_indices: list[int] | None = None,
    ) -> bool:
        return bool(delete_episode_indices) and not episode_ranges and not episode_delete_ranges

    def _open_dataset(self) -> LeRobotDataset:
        return LeRobotDataset(
            repo_id=self.repo_id,
            root=self.root,
            video_backend=self.video_backend,
            return_uint8=True,
        )

    @staticmethod
    def _unique_sibling_path(root: Path, suffix: str) -> Path:
        index = 0
        while True:
            candidate = root.with_name(f".{root.name}.{suffix}-{index:03d}")
            if not candidate.exists():
                return candidate
            index += 1


_FRAME_DATA_SKIP_KEYS = {"episode_index", "task_index"}


def _jsonable_metadata_value(value):
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, list):
        return [_jsonable_metadata_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable_metadata_value(item) for key, item in value.items()}
    if isinstance(value, np.generic):
        return value.item()
    return value


def _jsonable_frame_value(value):
    if isinstance(value, torch.Tensor):
        value = value.detach().cpu().numpy()
    elif isinstance(value, np.ndarray):
        value = value
    elif hasattr(value, "as_py"):
        value = value.as_py()

    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, list | tuple):
        return [_jsonable_frame_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable_frame_value(item) for key, item in value.items()}
    return value


def _to_pil_image(value) -> Image.Image:
    if isinstance(value, Image.Image):
        return value.convert("RGB")

    if isinstance(value, torch.Tensor):
        array = value.detach().cpu().numpy()
    else:
        array = np.asarray(value)

    if array.ndim == 4:
        array = array[0]
    if array.ndim == 3 and array.shape[0] in (1, 3, 4):
        array = np.transpose(array, (1, 2, 0))
    if array.dtype != np.uint8:
        max_value = float(np.nanmax(array)) if array.size else 1.0
        if max_value <= 1.0:
            array = array * 255.0
        array = np.clip(array, 0, 255).astype(np.uint8)
    if array.ndim == 2:
        return Image.fromarray(array, mode="L").convert("RGB")
    if array.shape[-1] == 1:
        array = array[..., 0]
        return Image.fromarray(array, mode="L").convert("RGB")
    return Image.fromarray(array[..., :3]).convert("RGB")


class CuratorHandler(BaseHTTPRequestHandler):
    state: CuratorState

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/":
                self._send_bytes(INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
            elif parsed.path == "/api/dataset":
                self._send_json(self.state.dataset_payload())
            elif parsed.path == "/api/frame-data":
                query = parse_qs(parsed.query)
                episode = int(_single(query, "episode"))
                self._send_json(self.state.frame_data(episode))
            elif parsed.path == "/api/frame":
                query = parse_qs(parsed.query)
                episode = int(_single(query, "episode"))
                frame = int(_single(query, "frame"))
                camera = _single(query, "camera")
                jpeg = self.state.frame_jpeg(episode, frame, camera)
                self._send_bytes(jpeg, "image/jpeg")
            elif parsed.path == "/api/video":
                query = parse_qs(parsed.query)
                episode = int(_single(query, "episode"))
                camera = _single(query, "camera")
                with self.state.lock:
                    self._send_file(self.state.video_file_path(episode, camera), "video/mp4")
            else:
                self._send_error(HTTPStatus.NOT_FOUND, "Not found")
        except Exception as exc:  # noqa: BLE001
            logger.exception("GET %s failed", self.path)
            self._send_error(HTTPStatus.BAD_REQUEST, str(exc))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/edit":
                payload = self._read_json()
                self._send_json(self.state.update_edit(payload))
            else:
                self._send_error(HTTPStatus.NOT_FOUND, "Not found")
        except Exception as exc:  # noqa: BLE001
            logger.exception("POST %s failed", self.path)
            self._send_error(HTTPStatus.BAD_REQUEST, str(exc))

    def log_message(self, fmt: str, *args) -> None:
        logger.debug(fmt, *args)

    def _read_json(self) -> dict:
        length = int(self.headers.get("content-length", "0"))
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8")) if raw else {}

    def _send_json(self, payload: dict) -> None:
        self._send_bytes(json.dumps(payload).encode("utf-8"), "application/json")

    def _send_error(self, status: HTTPStatus, message: str) -> None:
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": message}).encode("utf-8"))

    def _send_bytes(self, payload: bytes, content_type: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_file(self, path: Path, content_type: str) -> None:
        size = path.stat().st_size
        start = 0
        end = size - 1
        status = HTTPStatus.OK

        range_header = self.headers.get("Range")
        if range_header:
            parsed = _parse_range_header(range_header, size)
            if parsed is None:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("content-range", f"bytes */{size}")
                self.end_headers()
                return
            start, end = parsed
            status = HTTPStatus.PARTIAL_CONTENT

        length = end - start + 1
        self.send_response(status)
        self.send_header("content-type", content_type)
        self.send_header("accept-ranges", "bytes")
        self.send_header("content-length", str(length))
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("content-range", f"bytes {start}-{end}/{size}")
        self.end_headers()

        with path.open("rb") as file:
            file.seek(start)
            remaining = length
            while remaining > 0:
                chunk = file.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                remaining -= len(chunk)


def _single(query: dict[str, list[str]], name: str) -> str:
    values = query.get(name)
    if not values:
        raise ValueError(f"Missing query parameter: {name}")
    return values[0]


def _parse_range_header(range_header: str, size: int) -> tuple[int, int] | None:
    if not range_header.startswith("bytes=") or size <= 0:
        return None

    spec = range_header.removeprefix("bytes=").split(",", 1)[0].strip()
    if "-" not in spec:
        return None

    start_s, end_s = spec.split("-", 1)
    try:
        if start_s == "":
            suffix_length = int(end_s)
            if suffix_length <= 0:
                return None
            start = max(0, size - suffix_length)
            end = size - 1
        else:
            start = int(start_s)
            end = int(end_s) if end_s else size - 1
    except ValueError:
        return None

    if start < 0 or end < start or start >= size:
        return None
    return start, min(end, size - 1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Review, trim, and delete LeRobot dataset episodes.")
    parser.add_argument("--repo-id", help="Dataset repo id. Defaults to the dataset folder name.")
    parser.add_argument(
        "--root",
        type=Path,
        required=True,
        help="Local dataset root containing meta/, data/, and videos/. Edits overwrite this source.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP host.")
    parser.add_argument("--port", type=int, default=8765, help="HTTP port.")
    parser.add_argument("--video-backend", help="Video backend passed to LeRobotDataset.")
    parser.add_argument("--open", action="store_true", help="Open the browser automatically.")
    return parser.parse_args()


def _resolve_dataset(args: argparse.Namespace) -> tuple[str, Path]:
    repo_id = args.repo_id or args.root.name
    return repo_id, args.root


def main() -> None:
    init_logging()
    args = parse_args()
    repo_id, root = _resolve_dataset(args)

    dataset = LeRobotDataset(
        repo_id=repo_id,
        root=root,
        video_backend=args.video_backend,
        return_uint8=True,
    )
    state = CuratorState(
        dataset=dataset,
        repo_id=repo_id,
        video_backend=args.video_backend,
    )

    CuratorHandler.state = state
    server = ThreadingHTTPServer((args.host, args.port), CuratorHandler)
    url = f"http://{args.host}:{server.server_port}"
    logger.info("Dataset curator listening at %s", url)
    logger.info("Input: %s", dataset.root)
    logger.info("Edits overwrite the input dataset after each operation")
    print(url, flush=True)

    if args.open:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Stopping dataset curator")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
