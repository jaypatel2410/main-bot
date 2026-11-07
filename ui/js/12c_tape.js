  // ---- 3.15: Time & Sales - the prints of the open chart, right of the chart ----
  // live = every print as it arrives (from 09:00, tick-by-tick slot); q = 4 draws a second (premarket); sum = IB summarised
  var tsOpen = false, tsFrac = 0.22, tsMode = '', tsSym = '', tsMin = 0, tsRows = [], tsSec = {}, tsLastT = 0, tsStatAt = 0;
  const TS_MAX = 150, TS_BIG = 5000;
  const tsPad = (n, w) => String(n).padStart(w || 2, '0');
  function tsTime(t){ const s = Math.floor(t), ms = Math.floor((t - s) * 1000);
    return `${Math.floor(s / 3600)}:${tsPad(Math.floor(s / 60) % 60)}:${tsPad(s % 60)}` + (tsMode === 'sum' ? '' : `<em>.${tsPad(ms, 3)}</em>`); }
  function tsRow(p){ const c = p[3] > 0 ? 'a' : p[3] < 0 ? 'b' : 'n';
    return `<div class="r ${c}${p[2] >= TS_BIG ? ' g' : ''}"><span>${tsTime(p[0])}</span><span>${fmtPx(p[1])}</span><span>${p[2].toLocaleString()}</span><span class="x">${esc(p[4] || '')}</span></div>`; }
  function tsApplyW(){
    const w = $('chartwrap').getBoundingClientRect().width || window.innerWidth * 0.6;
    $('chartwrap').style.setProperty('--ts-w', Math.round(clamp(tsFrac * w, 280, w * 0.45)) + 'px');
  }
  function tsShow(on, quiet){
    tsOpen = !!on;
    $('tsp').hidden = !tsOpen; $('chartwrap').classList.toggle('ts-on', tsOpen); $('ts-btn').classList.toggle('on', tsOpen);
    if (tsOpen) tsApplyW();
    if (!quiet) api('ts_on', tsOpen);
  }
  function tsBadge(){
    const m = $('ts-md'); m.className = 'md ' + tsMode;
    m.querySelector('b').textContent = tsMode === 'live' ? 'EVERY PRINT' : tsMode === 'q' ? '4× / SEC' : tsMode === 'sum' ? 'SUMMARISED' : '-';
    m.title = tsMode === 'sum' ? 'No tick-by-tick slot free - IB summarised trades until one frees up' : '';
  }
  function tsRedraw(){
    const v = tsRows.filter(p => p[2] >= tsMin).slice(0, TS_MAX);
    $('ts-rows').innerHTML = v.length ? v.map(tsRow).join('') : '<div class="empty">' + (tsSym ? 'Waiting for prints' : 'Open a chart') + '</div>';
  }
  function tsStats(force){
    const now = performance.now(); if (!force && now - tsStatAt < 250) return; tsStatAt = now;
    const t = Math.floor(tsLastT); const hist = [];
    for (let s = t - 59; s <= t; s++) { const b = tsSec[s]; hist.push(b ? b.n : 0); }
    const cv = $('ts-spd'), W = cv.clientWidth || 260, H = 34, dpr = window.devicePixelRatio || 1;
    if (cv.width !== Math.round(W * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
    const g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
    const mx = Math.max(1, ...hist), bw = W / 60;
    hist.forEach((x, i) => { const h = Math.max(1, x / mx * (H - 2)); g.fillStyle = i >= 55 ? '#818cf8' : 'rgba(129,140,248,.45)'; g.fillRect(i * bw, H - h, Math.max(1, bw - 1), h); });
  }
  function tsResetTo(p){
    const same = p.sym && p.sym === tsSym;
    tsMode = p.mode || ''; tsSym = p.sym || '';
    tsBadge();
    if (!same) { tsRows = []; tsSec = {}; tsLastT = 0; tsRedraw(); tsStats(true); }
  }
  function tsAdd(rows){
    if (!rows || !rows.length) return;
    for (const p of rows) {                       // [ET seconds, price, size, side +1 ask / -1 bid / 0, exchange]
      const s = Math.floor(p[0]), b = tsSec[s] || (tsSec[s] = {n: 0, v: 0, va: 0, vb: 0, g: 0});
      b.n++; b.v += p[2]; if (p[3] > 0) b.va += p[2]; else if (p[3] < 0) b.vb += p[2]; if (p[2] >= TS_BIG) b.g++;
      if (p[0] > tsLastT) tsLastT = p[0];
    }
    const cut = Math.floor(tsLastT) - 70; for (const k in tsSec) if (+k < cut) delete tsSec[k];
    const fresh = rows.slice().reverse();         // newest first
    tsRows = fresh.concat(tsRows); if (tsRows.length > 2000) tsRows.length = 2000;
    const add = fresh.filter(p => p[2] >= tsMin);
    const box = $('ts-rows');
    if (add.length) {
      if (add.length >= TS_MAX || !box.firstElementChild || box.firstElementChild.classList.contains('empty')) tsRedraw();
      else {
        box.insertAdjacentHTML('afterbegin', add.map(tsRow).join(''));
        while (box.childElementCount > TS_MAX) box.lastElementChild.remove();
      }
    }
    tsStats();
  }
  $('ts-btn').addEventListener('click', () => { tsShow(!tsOpen); save(); });
  $('ts-fl').addEventListener('click', e => { const b = e.target.closest('[data-f]'); if (!b) return;
    tsMin = Number(b.dataset.f) || 0; $('ts-fl').querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b)); tsRedraw(); });
  (function(){
    const el = $('tssplit');
    el.addEventListener('mousedown', e => {
      if (e.button !== 0) return; e.preventDefault(); el.classList.add('drag'); document.body.classList.add('resizing');
      const move = ev => { const r = $('chartwrap').getBoundingClientRect(); tsFrac = clamp((r.right - ev.clientX) / r.width, 0.12, 0.45); tsApplyW(); };
      const up = () => { window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up);
        el.classList.remove('drag'); document.body.classList.remove('resizing'); save(); };
      window.addEventListener('mousemove', move); window.addEventListener('mouseup', up);
    });
    el.addEventListener('dblclick', () => { tsFrac = 0.22; tsApplyW(); save(); });
  })();
  window.addEventListener('resize', () => { if (tsOpen) tsApplyW(); });
  setInterval(() => { if (tsOpen) tsStats(); }, 1000);
