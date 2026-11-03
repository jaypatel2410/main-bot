  // ---- 3.14: chart notes - right click on the chart -> Add note. The note is pinned to that candle and price and stays
  // there as a numbered badge (1, 2, 3 ... per ticker-day, in the order written). One note belongs to a ticker-day, not
  // to a screen: the live chart and every backtest chart of that ticker-day show the same notes (core/data/chart_notes.py:
  // Turso + a copy on this PC). Click a badge to edit it; hover it to read it. ----
  const cnAll = {};                                   // ticker -> every note of it (all days), oldest first
  let cnBars = [];                                    // the backtest chart's candle times (its logical index = position)
  let cnEd = null, cnCtx = null, cnHot = null;        // the open editor, the right-click spot, the badge under the mouse
  const cnDayOf = t => new Date(t * 1000).toISOString().slice(0, 10);
  const cnHM = t => t == null ? '' : fmtT(t);
  function cnNumbers(list){                           // id -> its number on its day
    const by = {}, out = {};
    for (const n of list) { by[n.day] = (by[n.day] || 0) + 1; out[n.id] = by[n.day]; }
    return out;
  }
  function cnPx(p){ return p == null ? null : Number(Number(p).toFixed(p < 1 ? 4 : p < 10 ? 3 : 2)); }

  // the badges: drawn on the chart's own canvas (they move with every scroll / zoom), hit-tested for hover and clicks
  function cnLayer(series, xOf, items){
    return {
      _p: null, hits: [],
      attached(p){ this._p = p; }, detached(){ this._p = null; }, updateAllViews(){},
      update(){ if (this._p) this._p.requestUpdate(); },
      paneViews(){ const self = this; return [{zOrder: () => 'top', renderer: () => ({draw: tg => self.draw(tg)})}]; },
      draw(target){
        const hits = [];
        target.useMediaCoordinateSpace(({context: ctx, mediaSize: ms}) => {
          ctx.font = '700 11px Bahnschrift,"Segoe UI",Arial,sans-serif';
          ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
          for (const {n, k} of items()) {
            if (n.t == null || n.px == null) continue;
            const x = xOf(n.t), y = series.priceToCoordinate(n.px);
            if (x == null || y == null || x < -20 || x > ms.width + 20 || y < -20 || y > ms.height + 20) continue;
            const lab = String(k), w = Math.max(18, 10 + ctx.measureText(lab).width), h = 18, up = y - 30 >= 2;
            const bx = x - w / 2, by = up ? y - 30 : y + 12, hot = n.id && cnHot && cnHot.id === n.id, open = cnEd && (n.id ? cnEd.note && cnEd.note.id === n.id : true);
            ctx.strokeStyle = 'rgba(253,230,138,.85)'; ctx.lineWidth = 1;              // stem from the badge to the price
            ctx.beginPath(); ctx.moveTo(x + 0.5, up ? by + h : by); ctx.lineTo(x + 0.5, up ? y - 3 : y + 3); ctx.stroke();
            ctx.beginPath(); ctx.arc(x, y, 2.6, 0, 2 * Math.PI);                         // the exact price
            ctx.fillStyle = '#fde68a'; ctx.fill(); ctx.lineWidth = 1.2; ctx.strokeStyle = 'rgba(0,0,0,.9)'; ctx.stroke();
            ctx.beginPath(); ctx.roundRect(bx, by, w, h, h / 2);
            ctx.fillStyle = hot || open ? '#fff3c4' : '#fde68a'; ctx.fill();
            ctx.lineWidth = 1.5; ctx.strokeStyle = 'rgba(0,0,0,.9)'; ctx.stroke();
            if (hot || open) { ctx.beginPath(); ctx.roundRect(bx - 3, by - 3, w + 6, h + 6, h / 2 + 3);
              ctx.lineWidth = 1.5; ctx.strokeStyle = 'rgba(253,230,138,.55)'; ctx.stroke(); }
            ctx.fillStyle = '#1c1606'; ctx.fillText(lab, x, by + h / 2 + 0.5);
            if (n.id) hits.push({x0: bx - 3, y0: by - 3, x1: bx + w + 3, y1: by + h + 3, n, k});   // not the draft
          }
        });
        this.hits = hits;
      },
      hit(x, y){ for (let i = this.hits.length - 1; i >= 0; i--) { const h = this.hits[i];
        if (x >= h.x0 && x <= h.x1 && y >= h.y0 && y <= h.y1) return h; } return null; },
    };
  }
  function cnLiveX(t){                                // the live chart: the note's candle at the current timeframe
    if (!shown.length) return null;
    const i = lastIdx(bucketOf(t));
    if (i < 0 || (tf !== 'D' && dayOf(shown[i][0]) !== dayOf(t))) return null;     // its day is not loaded
    return chart.timeScale().logicalToCoordinate(i);
  }
  function cnBtIdx(t){ let lo = 0, hi = cnBars.length - 1, r = -1;
    while (lo <= hi) { const m = (lo + hi) >> 1; if (cnBars[m] <= t) { r = m; lo = m + 1; } else hi = m - 1; } return r; }
  function cnBtX(t){ const i = cnBtIdx(t); return i < 0 || !btChart ? null : btChart.timeScale().logicalToCoordinate(i); }
  function cnItems(tk, day){
    const list = cnAll[tk] || [], num = cnNumbers(list);
    return list.filter(n => !day || n.day === day).map(n => ({n, k: num[n.id]}));
  }
  function cnDraft(tk, day, src){                     // the note being written: its badge shows where it will be pinned
    const e = cnEd;
    if (!e || e.note || e.tk !== tk || (day && e.day !== day) || e.src !== src) return [];
    return [{n: {id: '', t: e.t, px: e.px}, k: e.k}];
  }
  const cnLive = cnLayer(candles, cnLiveX, () => sym ? cnItems(sym).concat(cnDraft(sym, '', 'live')) : []);
  candles.attachPrimitive(cnLive);
  let cnBt = null;
  function cnAttachBt(){                              // called once the backtest chart exists (08_backtest.js)
    if (cnBt || !btSer) return;
    cnBt = cnLayer(btSer, cnBtX, () => btCur ? cnItems(btCur.tk, btCur.day).concat(cnDraft(btCur.tk, btCur.day, 'backtest')) : []);
    btSer.attachPrimitive(cnBt);
    cnHook($('bt-chart'), () => cnBt, 'bt');
  }
  function cnBtSetBars(bars){ cnBars = (bars || []).map(b => b.time); if (cnBt) cnBt.update(); }
  function cnRefresh(){
    cnLive.update(); if (cnBt) cnBt.update();
    cnRenderBtList(); cnSyncTrades();
  }
  function cnLoad(tk){
    if (!tk) return;
    api('notes_get', tk).then(r => { if (r && r.ok) { cnAll[tk] = r.notes || []; cnRefresh(); } });
  }
  function cnPut(n){
    const L = cnAll[n.tk] || (cnAll[n.tk] = []), i = L.findIndex(x => x.id === n.id);
    if (i >= 0) L[i] = n; else L.push(n);
    cnRefresh();
  }
  function cnDrop(n){ const L = cnAll[n.tk] || []; const i = L.findIndex(x => x.id === n.id); if (i >= 0) L.splice(i, 1); cnRefresh(); }

  // mouse on the badges: hover = read the note, click = edit it (the chart does not see that click)
  function cnHook(host, layer, src){
    const at = e => { const r = host.getBoundingClientRect(), L = layer(); return L ? L.hit(e.clientX - r.left, e.clientY - r.top) : null; };
    host.addEventListener('mousemove', e => {
      const h = at(e), id = h ? h.n.id : null;
      host.classList.toggle('cn-hot', !!h);
      if ((cnHot && cnHot.id) !== id) { cnHot = h ? h.n : null; const L = layer(); if (L) L.update(); }
      if (h && !(cnEd && cnEd.note && cnEd.note.id === h.n.id)) cnTip(h, e); else cnTip(null);
    });
    host.addEventListener('mouseleave', () => { host.classList.remove('cn-hot'); cnTip(null);
      if (cnHot) { cnHot = null; const L = layer(); if (L) L.update(); } });
    ['mousedown', 'click', 'dblclick'].forEach(ev => host.addEventListener(ev, e => {
      if (e.button !== 0) return;
      const h = at(e); if (!h) return;
      e.stopPropagation(); e.preventDefault();
      if (ev === 'mousedown') { cnTip(null); cnOpen({note: h.n, k: h.k, src, x: e.clientX, y: e.clientY}); }
    }, true));
  }
  cnHook($('chart'), () => cnLive, 'live');
  function cnTip(h, e){
    const tip = $('cn-tip');
    if (!h) { tip.classList.add('hidden'); return; }
    const n = h.n;
    tip.innerHTML = `<div class="cn-th"><b class="cn-k">${h.k}</b><span>${esc(fmtDay(n.t))} · ${esc(cnHM(n.t))} · ${esc(fmtPx(n.px))}</span></div>` +
      `<div class="cn-tt">${esc(n.text)}</div><div class="cn-tf">Click to edit</div>`;
    tip.classList.remove('hidden');
    const W = tip.offsetWidth, H = tip.offsetHeight;
    tip.style.left = Math.min(e.clientX + 14, window.innerWidth - W - 8) + 'px';
    tip.style.top = (e.clientY + 16 + H > window.innerHeight - 8 ? e.clientY - H - 12 : e.clientY + 16) + 'px';
  }

  // the editor: Enter saves, Shift + Enter = new line, Esc = discard, a click anywhere else = keep what you typed
  function cnOpen(o){
    cnClose(true);
    const ed = $('cn-ed'), ta = $('cn-tx'), n = o.note;
    cnEd = Object.assign({}, o, {orig: n ? n.text : ''});
    const tk = n ? n.tk : o.tk, t = n ? n.t : o.t, px = n ? n.px : o.px;
    const k = n ? o.k : (cnItems(o.tk).filter(x => x.n.day === o.day).length + 1);
    cnEd.k = k; $('cn-k').textContent = k;
    $('cn-meta').textContent = [tk, t != null ? fmtDay(t) : (n ? n.day : o.day), cnHM(t), px != null ? fmtPx(px) : ''].filter(Boolean).join(' · ');
    $('cn-del').classList.toggle('hidden', !n); $('cn-del').textContent = 'Delete';
    $('cn-st').textContent = n ? `written ${n.created.slice(5, 16)}${n.updated !== n.created ? ', edited ' + n.updated.slice(5, 16) : ''}` : 'New note';
    ta.value = n ? n.text : '';
    ed.classList.remove('hidden');
    cnSize();
    const W = ed.offsetWidth, H = ed.offsetHeight;    // beside the pinned point (never over its badge): right, else left
    const right = o.side !== 'left' && o.x + 28 + W <= window.innerWidth - 8;
    ed.style.left = Math.max(8, right ? o.x + 28 : o.x - 28 - W) + 'px';
    ed.style.top = Math.max(8, Math.min(o.y - 22, window.innerHeight - H - 8)) + 'px';
    ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length);
    cnLive.update(); if (cnBt) cnBt.update();
  }
  function cnSize(){ const ta = $('cn-tx'); ta.style.height = 'auto'; ta.style.height = Math.min(240, Math.max(66, ta.scrollHeight)) + 'px'; }
  function cnClose(keep){                             // keep = save what was typed (a click elsewhere); false = discard (Esc)
    if (!cnEd) return;
    const e = cnEd, text = $('cn-tx').value.trim();
    cnEd = null;
    $('cn-ed').classList.add('hidden');
    cnLive.update(); if (cnBt) cnBt.update();
    if (!keep || !text || text === e.orig) return;
    cnSave(e, text);
  }
  function cnSave(e, text){
    const n = e.note;
    const call = n ? api('note_save', n.tk, n.day, n.t, n.px, text, n.id, n.src)
      : api('note_save', e.tk, e.day, e.t, e.px, text, null, e.src);
    call.then(r => {
      if (r && r.ok) { cnPut(r.note); toast({kind: 'info', text: `Note ${n ? e.k + ' changed' : 'saved'} - ${r.note.tk} ${r.note.day}`}); return; }
      toast({kind: 'err', text: (r && r.error) || 'The note was not saved (the app is not connected)'});
      cnOpen(Object.assign({}, e)); $('cn-tx').value = text; cnSize();          // nothing typed is lost
    });
  }
  $('cn-tx').addEventListener('input', cnSize);
  $('cn-tx').addEventListener('keydown', e => {
    e.stopPropagation();                              // the order hotkeys never see what you type here
    if (e.key === 'Escape') { e.preventDefault(); cnClose(false); return; }
    if (e.key !== 'Enter' || e.shiftKey) return;
    e.preventDefault();
    const ed = cnEd, text = $('cn-tx').value.trim();
    if (ed && ed.note && !text) {                     // an emptied note + Enter = delete it
      cnEd = null; $('cn-ed').classList.add('hidden'); cnDelete(ed.note, ed.k); return;
    }
    cnClose(true);
  });
  $('cn-del').addEventListener('click', () => {
    const ed = cnEd; if (!ed || !ed.note) return;
    twoStep($('cn-del'), 'cndel' + ed.note.id, 'Delete', `Delete note ${ed.k}? Click Delete again.`, () => {
      cnEd = null; $('cn-ed').classList.add('hidden'); cnDelete(ed.note, ed.k); });
  });
  function cnDelete(n, k){
    api('note_delete', n.id).then(r => {
      if (r && r.ok) { cnDrop(n); toast({kind: 'info', text: `Note ${k} deleted`}); }
      else toast({kind: 'err', text: (r && r.error) || 'The note was not deleted'});
    });
  }
  document.addEventListener('mousedown', e => {      // a click anywhere else closes the editor and keeps the note
    if (cnEd && !e.target.closest('#cn-ed')) cnClose(true);
  }, true);
  window.addEventListener('blur', () => cnTip(null));

  // right click on the live chart: Add note (+ the price alerts) - on a badge: edit / delete that note
  function cnMenuHead(tk, t, px){ return `${esc(tk)} · ${esc(cnHM(t))} · ${esc(fmtPx(px))}`; }
  function cnMenu(e, items){
    const m = $('ctxm');
    m.innerHTML = items;
    m.classList.remove('hidden');
    m.style.left = Math.min(e.clientX, window.innerWidth - m.offsetWidth - 8) + 'px';
    m.style.top = Math.min(e.clientY, window.innerHeight - m.offsetHeight - 8) + 'px';
  }
  function cnBadgeItems(h){
    return h ? `<button data-cne="1"><span class="ci">&#9998;</span>Edit note ${h.k}</button>` +
      `<button data-cnd="1" class="cdanger"><span class="ci">&#10005;</span>Delete note ${h.k}</button><div class="cd"></div>` : '';
  }
  $('chart').addEventListener('contextmenu', e => {
    if (!sym || !shown.length) return;
    e.preventDefault();
    const rc = $('chart').getBoundingClientRect(), x = e.clientX - rc.left, y = e.clientY - rc.top;
    const p0 = candles.coordinateToPrice(y);
    if (p0 == null || !(p0 > 0)) return;
    const lg = chart.timeScale().coordinateToLogical(x);
    const i = Math.max(0, Math.min(shown.length - 1, lg == null ? shown.length - 1 : Math.round(lg)));
    const t = shown[i][0], px = cnPx(p0), h = cnLive.hit(x, y), p = Number(Number(p0).toFixed(precision));
    cnCtx = {tk: sym, day: cnDayOf(t), t, px, src: 'live', x: e.clientX, y: e.clientY, hit: h};
    cnMenu(e, `<div class="ch">${cnMenuHead(sym, t, px)}</div>` + cnBadgeItems(h) +
      (tf === 'D' ? '' : `<button data-cn="1" class="cpri"><span class="ci">+</span>Add note here</button><div class="cd"></div>`) +
      `<div class="ch">Price alert - fires once, Discord</div>` +
      `<button data-cd="up" data-cp="${p}">Alert price above ${fmtPx(p)}</button><button data-cd="down" data-cp="${p}">Alert price below ${fmtPx(p)}</button>`);
  });
  function cnBtMenu(e){                               // right click on a backtest chart
    if (!btCur || !cnBars.length || !btSer) return;
    e.preventDefault();
    const rc = $('bt-chart').getBoundingClientRect(), x = e.clientX - rc.left, y = e.clientY - rc.top;
    const p0 = btSer.coordinateToPrice(y);
    if (p0 == null || !(p0 > 0)) return;
    const lg = btChart.timeScale().coordinateToLogical(x);
    const i = Math.max(0, Math.min(cnBars.length - 1, lg == null ? cnBars.length - 1 : Math.round(lg)));
    const t = cnBars[i], px = cnPx(p0), h = cnBt ? cnBt.hit(x, y) : null;
    cnCtx = {tk: btCur.tk, day: btCur.day, t, px, src: 'backtest', x: e.clientX, y: e.clientY, hit: h};
    cnMenu(e, `<div class="ch">${cnMenuHead(btCur.tk, t, px)}</div>` + cnBadgeItems(h) +
      `<button data-cn="1" class="cpri"><span class="ci">+</span>Add note here</button>`);
  }
  $('bt-chart').addEventListener('contextmenu', cnBtMenu);
  $('ctxm').addEventListener('click', e => {
    const c = cnCtx; if (!c) return;
    if (e.target.closest('[data-cn]')) { ctxClose(); cnOpen({tk: c.tk, day: c.day, t: c.t, px: c.px, src: c.src, x: c.x, y: c.y}); return; }
    if (e.target.closest('[data-cne]') && c.hit) { ctxClose(); cnOpen({note: c.hit.n, k: c.hit.k, src: c.src, x: c.x, y: c.y}); return; }
    if (e.target.closest('[data-cnd]') && c.hit) { ctxClose(); cnDelete(c.hit.n, c.hit.k); }
  });

  // the backtest chart's side panel: this ticker-day's notes, numbered like the badges; click one to edit it
  function cnRenderBtList(){
    const box = $('bt-notes'); if (!box) return;
    if (!btCur) { box.innerHTML = ''; return; }
    const it = cnItems(btCur.tk, btCur.day);
    box.innerHTML = it.length ? it.map(({n, k}) => `<button class="cn-row" data-cni="${esc(n.id)}"><b class="cn-k">${k}</b>` +
      `<span class="cn-rb"><span class="cn-rm">${n.t != null ? esc(cnHM(n.t)) + ' · ' + esc(fmtPx(n.px)) : 'not pinned to a candle'}${n.src === 'live' ? ' · from the live chart' : ''}</span>` +
      `<span class="cn-rt">${esc(n.text)}</span></span></button>`).join('')
      : '<div class="sm">No note on this chart yet.</div>';
  }
  $('bt-notes').addEventListener('click', e => {
    const b = e.target.closest('[data-cni]'); if (!b || !btCur) return;
    const it = cnItems(btCur.tk, btCur.day).find(x => x.n.id === b.dataset.cni); if (!it) return;
    const r = b.getBoundingClientRect();
    cnOpen({note: it.n, k: it.k, src: 'backtest', x: r.left + 16, y: r.top + 22, side: 'left'});   // beside the list
  });
  function cnSyncTrades(){                            // the trade list's "your note" column and "With notes" filter
    if (!btRes || !btRes.trades) return;
    const seen = {};
    for (const t of btRes.trades) {
      const key = t.tk + '|' + t.day;
      if (!(t.tk in cnAll)) continue;                 // a ticker not loaded here keeps what the run result said
      const ns = seen[key] || (seen[key] = (cnAll[t.tk] || []).filter(n => n.day === t.day));
      t.nnote = ns.length; t.note1 = ns.length ? ns[ns.length - 1].text.slice(0, 120) : '';
    }
    if (btV === 'res') btRenderTrades();
  }
