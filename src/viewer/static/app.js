// 画面はIDだけを送る。Checkpointや音源のパス解決はサーバー側で行う。
const state = {models: [], tracks: [], selections: [], results: [], upload: null,
  source: null, scale: 14, duration: 1, overlaySelection: new Set()};
const $ = (id) => document.getElementById(id);
const colors = ['#0969da', '#b45309', '#7c3aed', '#0f766e', '#be185d', '#607300', '#17649b', '#8b5e34'];
const metricGroups = [
  ['Frame', 'metric/frame'],
  ['Note', 'metric/note'],
  ['Note + offset', 'metric/note-with-offsets'],
];

async function requestJson(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function setStatus(message, isError = false) {
  $('jobStatus').textContent = message;
  $('jobStatus').style.color = isError ? '#b42318' : '';
}

function chosenModelIds() {
  return [...state.selections];
}

function renderModels() {
  const container = $('modelRows');
  container.replaceChildren();
  state.selections.forEach((modelId, index) => {
    const card = document.createElement('div'); card.className = 'model-card';
    const top = document.createElement('div'); top.className = 'card-top';
    const label = document.createElement('strong'); label.textContent = `モデル ${index + 1}`;
    top.append(label);
    if (state.selections.length > 1) {
      const remove = document.createElement('button'); remove.type = 'button';
      remove.textContent = '外す'; remove.onclick = () => {state.selections.splice(index, 1); renderModels();};
      top.append(remove);
    }
    const select = document.createElement('select');
    for (const model of [...state.models].reverse()) {
      const option = document.createElement('option');
      option.value = model.id; option.textContent = `${model.run} · step ${model.step.toLocaleString()}`;
      select.append(option);
    }
    select.value = modelId;
    select.onchange = () => {state.selections[index] = select.value; renderModels();};
    const model = state.models.find((item) => item.id === modelId);
    const details = document.createElement('small');
    const config = model?.config || {};
    details.textContent = `batch ${config.batch_size ?? '?'} · ${config.sequence_length ?? '?'} samples · LR ${config.learning_rate ?? '?'} · complexity ${config.model_complexity ?? '?'} · ${config.train_on ?? '?'}`;
    const configDetails = document.createElement('details');
    const summary = document.createElement('summary'); summary.textContent = '学習条件をすべて表示';
    const configText = document.createElement('pre'); configText.textContent = JSON.stringify(config, null, 2);
    configDetails.append(summary, configText);
    card.append(top, select, details, configDetails); container.append(card);
  });
  $('addModel').disabled = state.selections.length >= 8 || state.selections.length >= state.models.length;
}

function renderTracks() {
  const query = $('trackSearch').value.trim().toLowerCase();
  const select = $('trackSelect'); const previous = select.value;
  select.replaceChildren();
  for (const track of state.tracks) {
    if (!`${track.id} ${track.composer} ${track.title}`.toLowerCase().includes(query)) continue;
    const option = document.createElement('option'); option.value = track.id;
    option.textContent = `${track.id} · ${track.composer} — ${track.title}`;
    select.append(option);
  }
  if ([...select.options].some((option) => option.value === previous)) select.value = previous;
  showTrackInfo();
}

function showTrackInfo() {
  const track = state.tracks.find((item) => item.id === $('trackSelect').value);
  $('trackInfo').textContent = track ? `${track.year} · ${Math.round(track.duration)}秒 · test split` : '該当する曲がありません';
}

function selectedSource() {
  const kind = document.querySelector('input[name=sourceType]:checked').value;
  if (kind === 'maestro') {
    if (!$('trackSelect').value) throw new Error('MAESTROの曲を選択してください');
    return {kind, id: $('trackSelect').value};
  }
  if (!state.upload) throw new Error('先にWAVをアップロードしてください');
  return {kind: 'upload', id: state.upload.id};
}

async function uploadFiles() {
  const audio = $('uploadAudio').files[0];
  if (!audio) throw new Error('WAVを選択してください');
  const data = new FormData(); data.append('audio', audio);
  const gt = $('uploadGt').files[0]; if (gt) data.append('gt', gt);
  $('uploadButton').disabled = true; setStatus('アップロード中…');
  try {
    state.upload = await requestJson('/api/upload', {method: 'POST', body: data});
    $('uploadInfo').textContent = `${state.upload.name} · ${Math.round(state.upload.duration)}秒${state.upload.has_gt ? ' · GTあり' : ''}`;
    setStatus('アップロード完了');
  } finally { $('uploadButton').disabled = false; }
}

async function startComparison() {
  const modelIds = chosenModelIds();
  if (new Set(modelIds).size !== modelIds.length) throw new Error('同じCheckpointが選ばれています');
  state.source = selectedSource();
  $('compareButton').disabled = true;
  $('jobProgress').hidden = false; $('jobProgress').max = modelIds.length; $('jobProgress').value = 0;
  setStatus('ジョブを登録中…');
  try {
    const job = await requestJson('/api/jobs', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({model_ids: modelIds, source: state.source})});
    await pollJob(job.id);
  } finally { $('compareButton').disabled = false; }
}

async function pollJob(jobId) {
  while (true) {
    const job = await requestJson(`/api/job/${jobId}`);
    $('jobProgress').value = job.completed;
    if (job.state === 'done') {
      setStatus(`${job.completed}モデル完了${job.results.some((item) => item.cache_hit) ? ' · キャッシュ再利用あり' : ''}`);
      state.results = await Promise.all(job.results.map((item) => requestJson(`/api/result/${item.key}`)));
      await renderMetrics(); renderRoll();
      return;
    }
    if (job.state === 'error') throw new Error(job.error || '推論ジョブが失敗しました');
    setStatus(`${job.state === 'queued' ? '待機中' : '推論中'} · ${job.completed}/${job.total}${job.current_model ? ` · ${job.current_model}` : ''}`);
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
}

function metricTable(title, rows, showCount = false) {
  const wrapper = document.createElement('div');
  const heading = document.createElement('h3'); heading.textContent = title; wrapper.append(heading);
  const table = document.createElement('table'); const thead = document.createElement('thead');
  const header = document.createElement('tr');
  for (const text of ['Checkpoint', ...metricGroups.flatMap(([name]) => [`${name} P`, `${name} R`, `${name} F1`])]) {
    const cell = document.createElement('th'); cell.textContent = text; header.append(cell);
  }
  thead.append(header); table.append(thead);
  const tbody = document.createElement('tbody');
  for (const row of rows) {
    const tr = document.createElement('tr'); const name = document.createElement('td');
    name.textContent = row.model_id + (showCount ? ` (${row.completed}/${row.total}曲)` : ''); tr.append(name);
    for (const [, prefix] of metricGroups) for (const key of ['precision', 'recall', 'f1']) {
      const cell = document.createElement('td'); const value = row.metrics?.[`${prefix}/${key}`];
      cell.textContent = value == null ? '—' : (value * 100).toFixed(2); tr.append(cell);
    }
    tbody.append(tr);
  }
  table.append(tbody); wrapper.append(table); return wrapper;
}

async function renderMetrics() {
  $('metrics').replaceChildren(metricTable('選択曲（%）', state.results));
  if (state.source?.kind !== 'maestro') { $('aggregates').replaceChildren(); return; }
  const aggregates = await Promise.all(state.results.map((result) =>
    requestJson(`/api/aggregate?model_id=${encodeURIComponent(result.model_id)}`)));
  $('aggregates').replaceChildren(metricTable('MAESTRO v3 test 全体（評価済み曲の平均・%）', aggregates, true));
}

function renderRoll() {
  if (!state.results.length) return;
  const first = state.results[0];
  state.duration = first.duration || Math.max(1, ...first.prediction_notes.map((n) => n.end));
  const source = state.source; const audio = $('audioPlayer');
  audio.src = `/api/audio?kind=${encodeURIComponent(source.kind)}&id=${encodeURIComponent(source.id)}`;
  $('rollHint').textContent = first.source.title;
  // 新しい推論結果を表示するときは、GTと各モデルをすべて表示対象に戻す。
  state.overlaySelection = new Set(rollEntries().map((entry) => entry.name));
  renderLegend();
  const downloads = $('downloads'); downloads.replaceChildren();
  if (first.ground_truth_notes.length) addDownload(downloads, 'GT MIDI',
    `/api/midi?kind=${encodeURIComponent(source.kind)}&id=${encodeURIComponent(source.id)}`);
  for (const result of state.results) addDownload(downloads, `${result.model_id} · 予測MIDI`,
    `/api/artifact/${result.key}/prediction.mid`);
  drawRoll();
}

function rollEntries() {
  if (!state.results.length) return [];
  const entries = [];
  if (state.results[0].ground_truth_notes.length) {
    entries.push({name: 'GT', notes: state.results[0].ground_truth_notes, color: '#64748b'});
  }
  state.results.forEach((result, index) => entries.push({name: result.model_id,
    notes: result.prediction_notes, color: colors[index % colors.length]}));
  return entries;
}

function renderLegend() {
  const legend = $('legend'); legend.replaceChildren();
  const overlay = $('viewMode').value === 'overlay';
  if (overlay && state.results.length) {
    const hint = document.createElement('span'); hint.textContent = '重ね合わせるMIDI：';
    legend.append(hint);
  }
  for (const entry of rollEntries()) {
    const item = document.createElement(overlay ? 'label' : 'span');
    const mark = document.createElement('i'); mark.style.background = entry.color;
    if (overlay) {
      // チェック状態は描画対象だけに反映し、評価結果とMIDIのダウンロードは維持する。
      const checkbox = document.createElement('input'); checkbox.type = 'checkbox';
      checkbox.checked = state.overlaySelection.has(entry.name);
      item.style.opacity = checkbox.checked ? '1' : '0.55';
      checkbox.onchange = () => {
        if (checkbox.checked) state.overlaySelection.add(entry.name);
        else state.overlaySelection.delete(entry.name);
        item.style.opacity = checkbox.checked ? '1' : '0.55';
        drawRoll();
      };
      item.append(checkbox);
    }
    item.append(mark, document.createTextNode(entry.name)); legend.append(item);
  }
}

function addDownload(parent, label, url) {
  const link = document.createElement('a'); link.href = url; link.textContent = label; link.download = '';
  parent.append(link);
}

function drawRoll() {
  if (!state.results.length) return;
  const scroll = $('rollScroll'); const canvas = $('rollCanvas'); const ctx = canvas.getContext('2d');
  const scale = state.scale; const row = 8; const header = 40; const panelHeight = 88 * row + header;
  const overlay = $('viewMode').value === 'overlay';
  const hasGt = state.results[0].ground_truth_notes.length > 0;
  const panels = overlay ? 1 : state.results.length + (hasGt ? 1 : 0);
  const width = Math.max(300, scroll.clientWidth - 2);
  $('rollSpacer').style.width = `${Math.max(width, state.duration * scale + 120)}px`;
  $('rollSpacer').style.height = `${panelHeight * panels}px`;
  canvas.width = width; canvas.height = panelHeight * panels;
  canvas.style.width = `${width}px`; canvas.style.height = `${canvas.height}px`;
  const leftTime = scroll.scrollLeft / scale; const rightTime = leftTime + width / scale;
  // CanvasはCSS背景を透かさず白で塗り、保存後の描画もライトテーマで統一する。
  ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, width, canvas.height);

  const lists = rollEntries();
  for (let panel = 0; panel < panels; panel++) {
    const top = panel * panelHeight; const label = overlay ? '重ね合わせ' : lists[panel].name;
    ctx.fillStyle = '#f6f8fa'; ctx.fillRect(0, top, width, header);
    ctx.fillStyle = '#24292f'; ctx.font = '12px system-ui'; ctx.fillText(label, 12, top + 15, width - 24);
    const tick = scale >= 15 ? 5 : 10;
    for (let second = Math.ceil(leftTime / tick) * tick; second < rightTime; second += tick) {
      const x = (second - leftTime) * scale;
      ctx.strokeStyle = '#e6ebf0'; ctx.beginPath(); ctx.moveTo(x, top + header);
      ctx.lineTo(x, top + panelHeight); ctx.stroke();
      ctx.fillStyle = '#57606a'; ctx.fillText(`${second}s`, x + 3, top + 33);
    }
    for (let pitch = 21; pitch <= 108; pitch += 12) {
      const y = top + header + (108 - pitch) * row;
      ctx.strokeStyle = '#eaeef2'; ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke();
    }
    const renderLists = overlay ? lists.filter((item) => state.overlaySelection.has(item.name)) : [lists[panel]];
    for (const item of renderLists) {
      ctx.fillStyle = item.color; ctx.globalAlpha = overlay ? 0.72 : 0.9;
      for (const note of item.notes) {
        if (note.end < leftTime || note.start > rightTime || note.pitch < 21 || note.pitch > 108) continue;
        const x = (note.start - leftTime) * scale;
        const y = top + header + (108 - note.pitch) * row;
        ctx.fillRect(x, y + 1, Math.max(2, (note.end - note.start) * scale), row - 2);
      }
    }
    ctx.globalAlpha = 1;
  }
  const playhead = (Number($('audioPlayer').currentTime || 0) - leftTime) * scale;
  if (playhead >= 0 && playhead <= width) {
    ctx.strokeStyle = '#cf222e'; ctx.lineWidth = 2; ctx.beginPath();
    ctx.moveTo(playhead, 0); ctx.lineTo(playhead, canvas.height); ctx.stroke(); ctx.lineWidth = 1;
  }
}

async function initialize() {
  try {
    const catalog = await requestJson('/api/catalog');
    state.models = catalog.models; state.tracks = catalog.tracks;
    const uniqueRuns = [];
    for (const model of [...state.models].reverse()) {
      if (!uniqueRuns.some((item) => item.run === model.run)) uniqueRuns.push(model);
      if (uniqueRuns.length === 2) break;
    }
    state.selections = uniqueRuns.map((model) => model.id);
    for (const model of [...state.models].reverse()) {
      if (state.selections.length >= 2) break;
      if (!state.selections.includes(model.id)) state.selections.push(model.id);
    }
    renderModels(); renderTracks();
    setStatus(`${state.models.length} Checkpoint · ${state.tracks.length} test曲を読み込みました`);
  } catch (error) { setStatus(error.message, true); }
}

$('addModel').onclick = () => {
  const candidate = [...state.models].reverse().find((model) => !state.selections.includes(model.id));
  if (candidate) {state.selections.push(candidate.id); renderModels();}
};
$('trackSearch').oninput = renderTracks;
$('trackSelect').onchange = showTrackInfo;
for (const radio of document.querySelectorAll('input[name=sourceType]')) radio.onchange = () => {
  const uploaded = radio.value === 'upload' && radio.checked;
  $('uploadSource').hidden = !uploaded; $('maestroSource').hidden = uploaded;
};
$('uploadButton').onclick = () => uploadFiles().catch((error) => setStatus(error.message, true));
$('compareButton').onclick = () => startComparison().catch((error) => setStatus(error.message, true));
$('viewMode').onchange = () => {renderLegend(); drawRoll();};
$('rollScroll').onscroll = () => requestAnimationFrame(drawRoll);
$('zoom').oninput = () => {
  const scroll = $('rollScroll'); const oldScale = state.scale;
  const center = (scroll.scrollLeft + scroll.clientWidth / 2) / oldScale;
  state.scale = Number($('zoom').value); $('zoomValue').textContent = `${state.scale} px/s`;
  drawRoll(); scroll.scrollLeft = Math.max(0, center * state.scale - scroll.clientWidth / 2);
};
$('rollCanvas').onclick = (event) => {
  $('audioPlayer').currentTime = Math.max(0, Math.min(state.duration,
    ($('rollScroll').scrollLeft + event.offsetX) / state.scale));
  drawRoll();
};
$('audioPlayer').ontimeupdate = () => {
  const scroll = $('rollScroll'); const position = $('audioPlayer').currentTime * state.scale;
  if (position > scroll.scrollLeft + scroll.clientWidth - 45 || position < scroll.scrollLeft) {
    scroll.scrollLeft = Math.max(0, position - 45);
  }
  drawRoll();
};
window.addEventListener('resize', drawRoll);
initialize();
