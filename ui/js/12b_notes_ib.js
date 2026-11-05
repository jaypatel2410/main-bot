  // ---- 3.14: Notes tab - a journal of every ticker-day with chart notes (live chart + backtest charts, one store:
  // core/data/chart_notes.py) or a backtest verdict. Click a row = that day's 1-minute chart with the notes pinned. ----
  let ntItems = [], ntSel = '', ntVerd = 'all', ntSrc = 'all', ntGrp = 'day', ntChart = null, ntSer = null, ntVw = null, ntReq = 0;
  let ntPin = null, ntEdit = '', ntLastBar = null;     // ntLastBar: the latest candle of the open day {t, close}                       // the new note's pin {t, px}; the note being edited (id)
  const ntKey = x => x.tk + '|' + x.day;
  const ntVcls = v => /good/i.test(v) ? 'good' : /bad/i.test(v) ? 'bad' : /skip/i.test(v) ? 'skip' : '';
  const ntDayLab = d => fmtDate(Date.UTC(+d.slice(0, 4), +d.slice(5, 7) - 1, +d.slice(8, 10)) / 1000);
  const ntChartOpt = {autoSize: true, layout: {background: {color: '#000'}, textColor: '#9aa3b2', fontSize: 11},
    grid: {vertLines: {visible: false}, horzLines: {visible: false}}, rightPriceScale: {borderColor: '#222'}, crosshair: {mode: 0}};
  function ntLoad(){
    $('nt-meta').textContent = 'Loading...';
    api('notes_list').then(r => {
      if (!r || !r.ok) { $('nt-meta').textContent = (r && r.error) || 'Not available'; return; }
      ntItems = r.items || [];
      const nn = ntItems.reduce((a, x) => a + x.notes.length, 0);
      $('nt-meta').textContent = `${nn.toLocaleString()} note${nn === 1 ? '' : 's'} on ${ntItems.length.toLocaleString()} ticker-day${ntItems.length === 1 ? '' : 's'}`;
      ntRender();
    });
  }
  function ntShown(){
    const q = ($('nt-q').value || '').trim().toLowerCase();
    return ntItems.filter(x => {
      if (ntVerd !== 'all' && !x.verdicts.some(v => v.v === ntVerd)) return false;
      if (ntSrc === 'live' && !x.src.includes('live')) return false;
      if (ntSrc === 'backtest' && !(x.src.some(s => s.startsWith('backtest')) || x.verdicts.length || x.trades.length)) return false;
      if (!q) return true;
      return x.tk.toLowerCase().includes(q) || x.notes.some(n => (n.text || '').toLowerCase().includes(q));
    });
  }
  function ntRender(){
    const cnt = {};
    ntItems.forEach(x => new Set(x.verdicts.map(v => v.v)).forEach(v => { cnt[v] = (cnt[v] || 0) + 1; }));
    if (ntVerd !== 'all' && !cnt[ntVerd]) ntVerd = 'all';
    $('nt-verd').innerHTML = `<button data-v="all" class="${ntVerd === 'all' ? 'on' : ''}">All<b>${ntItems.length}</b></button>` +
      Object.keys(cnt).sort().map(v => `<button data-v="${esc(v)}" class="${ntVerd === v ? 'on' : ''}">${esc(v)}<b>${cnt[v]}</b></button>`).join('');
    const S = ntShown();
    if (ntGrp === 'tk') S.sort((a, b) => a.tk < b.tk ? -1 : a.tk > b.tk ? 1 : a.day < b.day ? 1 : -1);
    let head = '', html = '';
    for (const x of S) {
      const g = ntGrp === 'tk' ? x.tk : ntDayLab(x.day);
      if (g !== head) { head = g; html += `<div class="ntg">${esc(g)}</div>`; }
      const last = x.notes.length ? x.notes[x.notes.length - 1].text : (x.verdicts.length ? 'Verdict only' : '');
      const pnl = x.trades.length ? x.trades.reduce((a, t) => a + (t.pnl || 0), 0) : null;
      const strat = x.trades.length ? x.trades[0].strat : x.verdicts.length ? x.verdicts[0].strat : 'Live chart';
      html += `<div class="ntrow${ntKey(x) === ntSel ? ' sel' : ''}" data-nk="${esc(ntKey(x))}"><div class="t"><b>${esc(x.tk)}</b>` +
        `<span class="sm">${esc(ntGrp === 'tk' ? ntDayLab(x.day) : strat)}</span><div class="spacer"></div>` +
        (x.verdicts.length ? `<span class="ntvd ${ntVcls(x.verdicts[0].v)}">${esc(x.verdicts[0].v)}</span>` : '') + '</div>' +
        `<div class="x">${esc(last)}</div><div class="f"><span>${x.notes.length} note${x.notes.length === 1 ? '' : 's'}</span>` +
        (pnl != null ? `<span class="${pnl > 0 ? 'grn' : pnl < 0 ? 'red' : ''}" style="color:${pnl > 0 ? 'var(--pos)' : pnl < 0 ? 'var(--neg)' : 'inherit'}">${btm(pnl)}</span>` : '') +
        x.src.map(s => `<span class="ntsrc">${s === 'live' ? 'live' : 'backtest'}</span>`).filter((v, i, a) => a.indexOf(v) === i).join('') + '</div></div>';
    }
    $('nt-list').innerHTML = html || `<div class="oempty">${ntItems.length ? 'Nothing matches this filter.' : 'No notes yet. Right click the live chart or a backtest chart and pick Add note.'}</div>`;
    const sel = S.find(x => ntKey(x) === ntSel) || S[0];
    if (sel) ntShow(sel); else { ntSel = ''; $('nt-det').style.visibility = 'hidden'; }
  }
  function ntShow(x){
    const first = ntSel !== ntKey(x);
    ntSel = ntKey(x); $('nt-det').style.visibility = '';
    document.querySelectorAll('#nt-list .ntrow').forEach(r => r.classList.toggle('sel', r.dataset.nk === ntSel));
    $('nt-tk').textContent = x.tk; $('nt-day').textContent = ntDayLab(x.day);
    $('nt-vd').innerHTML = x.verdicts.map(v => `<span class="ntvd ${ntVcls(v.v)}" title="${esc(v.strat)}">${esc(v.v)}</span>`).join(' ');
    $('nt-bt').hidden = !x.trades.length;
    $('nt-facts').innerHTML = x.trades.slice(0, 4).map(t => `<div>${esc(t.strat)}${t.setup ? ' - ' + esc(t.setup) : ''}` +
      `<b>${fmtPx(t.entry)} ${esc((t.entry_hms || '').slice(0, 5))} &rarr; ${fmtPx(t.exit)} ${esc((t.exit_hms || '').slice(0, 5))}</b>` +
      `<b class="${btc(t.pnl)}">${btm(t.pnl)} <span class="sm">${esc(t.result || '')}</span></b></div>`).join('') +
      (x.trades.length > 4 ? `<div>More trades<b>${x.trades.length - 4}</b></div>` : '');
    $('nt-notes').innerHTML = x.notes.length ? x.notes.map((n, i) => `<div class="ntnote"><div class="h"><span class="n">${i + 1}</span>` +
      `<span>${n.t != null ? fmtT(n.t) : 'not pinned'}${n.px != null ? ' - ' + fmtPx(n.px) : ''}</span><span>written ${esc((n.created || '').slice(5, 16))}` +
      `${n.updated && n.updated !== n.created ? ', edited ' + esc(n.updated.slice(5, 16)) : ''}</span><span class="ntsrc">${String(n.src || 'live').startsWith('backtest') ? 'backtest' : 'live'}</span>` +
      `<button class="sbtn" data-nedit="${esc(n.id)}" style="margin-left:auto">Edit</button><button class="sbtn danger" data-ndel="${esc(n.id)}" style="margin-left:0">Delete</button></div>` +
      (ntEdit === n.id ? `<textarea data-ntx="${esc(n.id)}">${esc(n.text)}</textarea><div class="eb"><span class="sm" style="margin-right:auto">` +
        `${n.t == null ? 'Not pinned yet - click the chart to pin it (else it goes to the latest candle)' : 'Click the chart to move its pin'}</span><button class="sbtn" data-ncancel="1">Cancel</button>` +
        `<button class="sbtn pri" data-nsave="${esc(n.id)}">Save</button></div>` : `<div class="tx">${esc(n.text)}</div>`) + '</div>').join('')
      : '<div class="sm">No chart notes yet - write one above.</div>';
    if (first) { ntPin = null; ntEdit = ''; ntPinShow(); }
    if (first) ntBars(x); else ntMarkers(x);
  }
  function ntBars(x){
    if (!ntChart) {
      ntChart = LWC.createChart($('nt-chart'), Object.assign({}, ntChartOpt, {timeScale: {timeVisible: true, secondsVisible: false, borderColor: '#222'}}));
      ntSer = ntChart.addCandlestickSeries({upColor: '__UP__', downColor: '__DOWN__', borderVisible: false, wickUpColor: '__UP__', wickDownColor: '__DOWN__'});
      ntVw = ntChart.addLineSeries({color: '__VWAP__', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false});
      ntChart.subscribeClick(p => {                    // click = pin the note being written to that candle and price
        if (!p || !p.point || p.time == null) return;
        const px = ntSer.coordinateToPrice(p.point.y); if (px == null) return;
        ntPin = {t: Number(p.time), px: Number(Number(px).toPrecision(5))}; ntPinShow();
        const x = ntCur(); if (x) ntMarkers(x);
      });
    }
    ntSer.setData([]); ntVw.setData([]); ntSer.setMarkers([]); ntLastBar = null;
    $('nt-cmsg').textContent = 'Loading the chart...';
    const req = ++ntReq;
    api('notes_bars', x.tk, x.day).then(r => {
      if (req !== ntReq) return;
      if (!r || !r.ok) { $('nt-cmsg').textContent = (r && r.error) || 'No candles for this day'; return; }
      $('nt-cmsg').textContent = '';
      ntSer.setData(r.bars.map(b => ({time: b.time, open: b.open, high: b.high, low: b.low, close: b.close})));
      if (r.bars.length) { const b = r.bars[r.bars.length - 1]; ntLastBar = {t: b.time, px: b.close}; } ntPinShow();
      ntVw.setData(r.bars.map(b => ({time: b.time, value: b.vwap})));
      ntMarkers(x);
      const ts = x.notes.filter(n => n.t != null).map(n => n.t).concat(x.trades.map(t => btEpoch(x.day, t.entry_hms)).filter(Boolean));
      if (ts.length) { const lo = Math.min(...ts), hi = Math.max(...ts);
        try { ntChart.timeScale().setVisibleRange({from: lo - 2 * 3600, to: hi + 2 * 3600}); } catch (e) { ntChart.timeScale().fitContent(); } }
      else ntChart.timeScale().fitContent();
    });
  }
  function ntMarkers(x){
    if (!ntSer) return;
    const m = [], fl = t => Math.floor(t / 60) * 60;
    x.notes.forEach((n, i) => { if (n.t != null) m.push({time: fl(n.t), position: 'aboveBar', color: '#fde68a', shape: 'circle', text: String(i + 1)}); });
    x.trades.forEach(t => { const short = t.side !== 'Long';
      if (t.entry_hms) m.push({time: fl(btEpoch(x.day, t.entry_hms)), position: short ? 'aboveBar' : 'belowBar', color: short ? '#ff1744' : '#00e676', shape: short ? 'arrowDown' : 'arrowUp', text: ''});
      if (t.exit_hms) m.push({time: fl(btEpoch(x.day, t.exit_hms)), position: short ? 'belowBar' : 'aboveBar', color: short ? '#00e676' : '#ff1744', shape: short ? 'arrowUp' : 'arrowDown', text: ''}); });
    if (ntPin) m.push({time: fl(ntPin.t), position: 'aboveBar', color: '#5b6cf2', shape: 'circle', text: '+'});
    m.sort((a, b) => a.time - b.time); ntSer.setMarkers(m);
  }
  function ntPinShow(){
    $('nt-pin').textContent = ntPin ? `Pinned to ${fmtT(ntPin.t)} at ${fmtPx(ntPin.px)} (click the chart again to move it)`
      : ntLastBar ? `Pinned to the latest candle (${fmtT(ntLastBar.t)} at ${fmtPx(ntLastBar.px)}) - or click the chart to pick one` : 'Click the chart to pin it to a candle and price';
    $('nt-unpin').hidden = !ntPin;
  }
  const ntCur = () => ntItems.find(i => ntKey(i) === ntSel);
  function ntStore(x, note){                           // a saved note -> this list and the charts' notes
    const i = x.notes.findIndex(n => n.id === note.id);
    if (i >= 0) x.notes[i] = note; else x.notes.push(note);
    x.notes.sort((a, b) => (a.created || '') < (b.created || '') ? -1 : 1);
    if (!x.src.includes(note.src || 'live')) x.src.push(note.src || 'live');
    if (typeof cnPut === 'function') cnPut(note);
  }
  $('nt-list').addEventListener('click', e => { const r = e.target.closest('[data-nk]'); if (!r) return;
    const x = ntItems.find(i => ntKey(i) === r.dataset.nk); if (x) ntShow(x); });
  $('nt-verd').addEventListener('click', e => { const b = e.target.closest('[data-v]'); if (b) { ntVerd = b.dataset.v; ntRender(); } });
  $('nt-src').addEventListener('click', e => { const b = e.target.closest('[data-v]'); if (!b) return; ntSrc = b.dataset.v;
    document.querySelectorAll('#nt-src button').forEach(x => x.classList.toggle('on', x === b)); ntRender(); });
  $('nt-grp').addEventListener('click', e => { const b = e.target.closest('[data-v]'); if (!b) return; ntGrp = b.dataset.v;
    document.querySelectorAll('#nt-grp button').forEach(x => x.classList.toggle('on', x === b)); ntRender(); });
  $('nt-q').addEventListener('input', ntRender);
  $('nt-live').addEventListener('click', () => { const x = ntItems.find(i => ntKey(i) === ntSel); if (!x) return;
    api('load_symbol', x.tk).then(res => { if (res && res.recent) setRecent(res.recent); }); showScreen('chart'); });
  $('nt-bt').addEventListener('click', () => { const x = ntItems.find(i => ntKey(i) === ntSel); if (!x || !x.trades.length) return;
    btGo = {k: x.trades[0].k, tk: x.tk, day: x.day}; showScreen('bt'); });
  // add a note (pinned if the chart was clicked) / edit a note's text
  $('nt-add').addEventListener('click', () => {
    const x = ntCur(), text = $('nt-new').value.trim(); if (!x) return;
    if (!text) { toast({kind: 'warn', text: 'Write the note first'}); $('nt-new').focus(); return; }
    const pin = ntPin || ntLastBar;                    // no pin picked: the latest candle of the day (the charts draw pinned notes only)
    api('note_save', x.tk, x.day, pin ? pin.t : null, pin ? pin.px : null, text, null, 'live').then(r => {
      if (!r || !r.ok) { toast({kind: 'err', text: (r && r.error) || 'The note was not saved'}); return; }
      if (!ntItems.includes(x)) ntItems.unshift(x);
      ntStore(x, r.note); $('nt-new').value = ''; ntPin = null; ntPinShow(); ntRender(); toast({kind: 'info', text: `Note saved - ${x.tk} ${x.day}`});
    });
  });
  $('nt-new').addEventListener('keydown', e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) $('nt-add').click(); });
  $('nt-unpin').addEventListener('click', () => { ntPin = null; ntPinShow(); const x = ntCur(); if (x) ntMarkers(x); });
  $('nt-notes').addEventListener('click', e => {
    const ed = e.target.closest('[data-nedit]');
    if (ed) { ntEdit = ed.dataset.nedit; const x = ntCur(); if (x) ntShow(x);
      setTimeout(() => { const ta = document.querySelector(`#nt-notes textarea[data-ntx="${CSS.escape(ntEdit)}"]`); if (ta) { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); } }, 0); return; }
    if (e.target.closest('[data-ncancel]')) { ntEdit = ''; const x = ntCur(); if (x) ntShow(x); return; }
    const sv = e.target.closest('[data-nsave]');
    if (sv) {
      const x = ntCur(), n = x && x.notes.find(i => i.id === sv.dataset.nsave); if (!n) return;
      const ta = document.querySelector(`#nt-notes textarea[data-ntx="${CSS.escape(n.id)}"]`), text = ta ? ta.value.trim() : '';
      if (!text) { toast({kind: 'warn', text: 'The note is empty - use Delete to remove it'}); return; }
      const pin = ntPin || (n.t == null || n.px == null ? ntLastBar : null);    // an unpinned note gets a pin when it is edited
      api('note_save', n.tk, n.day, pin ? pin.t : n.t, pin ? pin.px : n.px, text, n.id, n.src).then(r => {
        if (!r || !r.ok) { toast({kind: 'err', text: (r && r.error) || 'The note was not saved'}); return; }
        ntEdit = ''; ntPin = null; ntPinShow(); ntStore(x, r.note); ntRender(); toast({kind: 'info', text: 'Note changed'});
      });
      return;
    }
  });
  $('nt-notes').addEventListener('keydown', e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && e.target.dataset.ntx) {
    const b = document.querySelector(`#nt-notes [data-nsave="${CSS.escape(e.target.dataset.ntx)}"]`); if (b) b.click(); } });
  // a new ticker-day (no note yet): open its chart here and write the first note
  $('nt-nday').value = new Date().toLocaleDateString('en-CA', {timeZone: 'America/New_York'});
  $('nt-open').addEventListener('click', () => {
    const tk = ($('nt-ntk').value || '').trim().toUpperCase(), day = $('nt-nday').value;
    if (!/^[A-Z0-9.]{1,12}$/.test(tk) || !/^\d{4}-\d{2}-\d{2}$/.test(day)) { toast({kind: 'warn', text: 'Type a ticker and pick a day'}); return; }
    let x = ntItems.find(i => i.tk === tk && i.day === day);
    if (!x) { x = {tk, day, notes: [], verdicts: [], trades: [], src: [], last: day}; ntItems.unshift(x); }
    ntSel = ''; $('nt-q').value = ''; ntVerd = 'all'; ntRender(); ntShow(x); $('nt-new').focus();
  });
  $('nt-ntk').addEventListener('keydown', e => { if (e.key === 'Enter') $('nt-open').click(); });
  // the chart's height: drag the bar under it (remembered on this PC)
  (() => {
    const box = $('nt-cbox'), grip = $('nt-grip'), set = h => box.style.setProperty('--nt-ch', Math.round(h) + 'px');
    try { const h = Number(localStorage.getItem('ntCh')); if (h >= 160) set(h); } catch (e) {}
    grip.addEventListener('mousedown', e => {
      if (e.button !== 0) return; e.preventDefault(); grip.classList.add('drag');
      const y0 = e.clientY, h0 = box.getBoundingClientRect().height;
      const mv = ev => set(Math.min(Math.max(160, h0 + ev.clientY - y0), window.innerHeight - 160));
      const up = () => { window.removeEventListener('mousemove', mv); window.removeEventListener('mouseup', up); grip.classList.remove('drag');
        try { localStorage.setItem('ntCh', String(Math.round(box.getBoundingClientRect().height))); } catch (e) {} };
      window.addEventListener('mousemove', mv); window.addEventListener('mouseup', up);
    });
    grip.addEventListener('dblclick', () => { box.style.removeProperty('--nt-ch'); try { localStorage.removeItem('ntCh'); } catch (e) {} });
  })();
  $('nt-notes').addEventListener('click', e => { const d = e.target.closest('[data-ndel]'); if (!d) return; const nid = d.dataset.ndel;
    twoStep(d, 'ntdel' + nid, 'Delete', 'Delete this note? Click Delete again.', () => api('note_delete', nid).then(r => {
      if (!r || !r.ok) { toast({kind: 'err', text: (r && r.error) || 'The note was not deleted'}); return; }
      const x = ntItems.find(i => ntKey(i) === ntSel);
      if (x) { x.notes = x.notes.filter(n => n.id !== nid); if (cnAll[x.tk]) cnAll[x.tk] = cnAll[x.tk].filter(n => n.id !== nid);
        if (!x.notes.length && !x.verdicts.length && !x.trades.length) { ntItems = ntItems.filter(i => i !== x); ntSel = ''; } }
      ntRender(); toast({kind: 'info', text: 'Note deleted'}); })); });

  // ---- 3.14: IB tab - the IB account's positions (read only: nothing here can place an order). Click a position for
  // its daily chart. One snapshot when the tab opens (and on Refresh) - nothing streams. ----
  let ibRows = [], ibSel = '', ibChart = null, ibSer = null, ibLine = null, ibReq = 0;
  const ibMoney = v => v == null ? '-' : (v < 0 ? '-' : '') + 'C$' + Math.abs(v).toLocaleString('en-US', {maximumFractionDigits: 0});
  function ibLoad(){ ibFetch(); }
  function ibFetch(){
    $('ib-meta').textContent = 'Getting a snapshot from IB Gateway...';
    api('ib_portfolio').then(r => {
      if (!r || !r.ok) { $('ib-meta').textContent = 'Not loaded: ' + ((r && r.error) || 'the app is not connected');
        if (!ibRows.length) $('ib-list').innerHTML = '<div class="oempty">Connect IB Gateway to see the positions of the account.</div>'; return; }
      ibRows = r.rows || [];
      $('ib-meta').textContent = `${(r.accounts || []).join(', ') || 'IB'} - snapshot at ${r.at} - all amounts in CAD` +
        (r.usdcad ? ` (USD/CAD ${r.usdcad.toFixed(4)}${r.fx_src ? ', ' + r.fx_src : ''})` : ' (no USD/CAD rate - USD positions stay in USD)') +
        (r.missing ? ` - ${r.missing} without a price` : '');
      const sgn = v => v == null ? '-' : (v > 0 ? '+' : '') + ibMoney(v);
      $('ib-mv').textContent = r.value == null ? '-' : ibMoney(r.value);
      $('ib-day').textContent = sgn(r.day); $('ib-day').className = btc(r.day);
      $('ib-up').textContent = sgn(r.upnl); $('ib-up').className = btc(r.upnl);
      $('ib-list').innerHTML = ibRows.length ? ibRows.map(x => `<div class="ibrow${x.sym === ibSel ? ' sel' : ''}" data-ib="${esc(x.sym)}">` +
        `<span><b>${esc(x.sym)}</b>${x.type && x.type !== 'STK' ? `<small>${esc(x.type)}</small>` : ''}${x.cad ? '' : `<small>${esc(x.cur)}</small>`}</span>` +
        `<span>${x.qty == null ? '-' : Number(x.qty).toLocaleString()}</span><span>${fmtPx(x.avg)}</span><span>${fmtPx(x.last)}</span><span>${ibMoney(x.value)}</span>` +
        `<span class="${btc(x.day)}">${sgn(x.day)}${x.day_pct == null ? '' : `<small>${x.day_pct > 0 ? '+' : ''}${x.day_pct.toFixed(1)}%</small>`}</span>` +
        `<span class="${btc(x.upnl)}">${sgn(x.upnl)}${x.pct == null ? '' : `<small>${x.pct > 0 ? '+' : ''}${x.pct.toFixed(1)}%</small>`}</span></div>`).join('')
        : '<div class="oempty">No open positions in the IB account.</div>';
      if (!ibSel && ibRows.length) ibShow(ibRows[0].sym);
    });
  }
  function ibShow(s){
    ibSel = s; $('ib-sym').textContent = s;
    document.querySelectorAll('#ib-list .ibrow').forEach(r => r.classList.toggle('sel', r.dataset.ib === s));
    if (!ibChart) {
      ibChart = LWC.createChart($('ib-chart'), Object.assign({}, ntChartOpt, {timeScale: {timeVisible: false, borderColor: '#222'}}));
      ibSer = ibChart.addCandlestickSeries({upColor: '__UP__', downColor: '__DOWN__', borderVisible: false, wickUpColor: '__UP__', wickDownColor: '__DOWN__'});
    }
    ibSer.setData([]); if (ibLine) { ibSer.removePriceLine(ibLine); ibLine = null; }
    $('ib-cmsg').textContent = `Loading daily candles for ${s}...`;
    const req = ++ibReq;
    api('get_daily', s).then(r => {
      if (req !== ibReq) return;
      if (!r || !r.ok) { $('ib-cmsg').textContent = `${s}: ${(r && r.error) || 'no daily candles'}`; return; }
      $('ib-cmsg').textContent = '';
      ibSer.setData((r.rows || []).map(b => ({time: b[0], open: b[1], high: b[2], low: b[3], close: b[4]})));
      const p = ibRows.find(x => x.sym === s);
      if (p && p.avg_native) ibLine = ibSer.createPriceLine({price: p.avg_native, color: '#9aa3b2', lineWidth: 1, lineStyle: LWC.LineStyle.Dashed, axisLabelVisible: true, title: 'avg cost'});
      ibChart.timeScale().fitContent();
    });
  }
  $('ib-list').addEventListener('click', e => { const r = e.target.closest('[data-ib]'); if (r) ibShow(r.dataset.ib); });
  $('ib-ref').addEventListener('click', ibFetch);
  $('ib-main').addEventListener('click', () => { if (!ibSel) return;
    api('load_symbol', ibSel).then(res => { if (res && res.recent) setRecent(res.recent); }); showScreen('chart'); setTf('D'); });

