  // ---- 3.14: Notes tab - a journal of every ticker-day with chart notes (live chart + backtest charts, one store:
  // core/data/chart_notes.py) or a backtest verdict. Click a row = that day's 1-minute chart with the notes pinned. ----
  let ntItems = [], ntSel = '', ntVerd = 'all', ntSrc = 'all', ntGrp = 'day', ntChart = null, ntSer = null, ntVw = null, ntReq = 0;
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
      `<button class="sbtn danger" data-ndel="${esc(n.id)}">Delete</button></div><div class="tx">${esc(n.text)}</div></div>`).join('')
      : '<div class="sm">No chart notes - only a verdict.</div>';
    if (first) ntBars(x); else ntMarkers(x);
  }
  function ntBars(x){
    if (!ntChart) {
      ntChart = LWC.createChart($('nt-chart'), Object.assign({}, ntChartOpt, {timeScale: {timeVisible: true, secondsVisible: false, borderColor: '#222'}}));
      ntSer = ntChart.addCandlestickSeries({upColor: '__UP__', downColor: '__DOWN__', borderVisible: false, wickUpColor: '__UP__', wickDownColor: '__DOWN__'});
      ntVw = ntChart.addLineSeries({color: '__VWAP__', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false});
    }
    ntSer.setData([]); ntVw.setData([]); ntSer.setMarkers([]);
    $('nt-cmsg').textContent = 'Loading the chart...';
    const req = ++ntReq;
    api('notes_bars', x.tk, x.day).then(r => {
      if (req !== ntReq) return;
      if (!r || !r.ok) { $('nt-cmsg').textContent = (r && r.error) || 'No candles for this day'; return; }
      $('nt-cmsg').textContent = '';
      ntSer.setData(r.bars.map(b => ({time: b.time, open: b.open, high: b.high, low: b.low, close: b.close})));
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
    m.sort((a, b) => a.time - b.time); ntSer.setMarkers(m);
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
  $('nt-notes').addEventListener('click', e => { const d = e.target.closest('[data-ndel]'); if (!d) return; const nid = d.dataset.ndel;
    twoStep(d, 'ntdel' + nid, 'Delete', 'Delete this note? Click Delete again.', () => api('note_delete', nid).then(r => {
      if (!r || !r.ok) { toast({kind: 'err', text: (r && r.error) || 'The note was not deleted'}); return; }
      const x = ntItems.find(i => ntKey(i) === ntSel);
      if (x) { x.notes = x.notes.filter(n => n.id !== nid); if (cnAll[x.tk]) cnAll[x.tk] = cnAll[x.tk].filter(n => n.id !== nid);
        if (!x.notes.length && !x.verdicts.length) { ntItems = ntItems.filter(i => i !== x); ntSel = ''; } }
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

