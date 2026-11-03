  // ---- 3.13: Backtest tab ----
  let btS = [], btK = 'jr', btRes = null, btRid = '', btList = [], btI = -1, btBy = 'halves', btTF = 'all', btPoll = null;
  let btChart = null, btSer = null, btVw = null, btDay = null, btDSer = null, btStopLine = null, btCur = null, btNotes = null, btVerd = '';
  const btm = v => v == null ? '-' : (v > 0 ? '+' : v < 0 ? '-' : '') + '$' + Math.abs(v).toLocaleString('en-US', {maximumFractionDigits: 0});
  const btc = v => v == null || v === 0 ? '' : v > 0 ? 'grn' : 'red';
  const btEpoch = (day, hms) => { const [y, m, d] = day.split('-').map(Number); const [h, mi, s] = ((hms || '00:00:00') + ':00:00').split(':').map(Number);
    return Date.UTC(y, m - 1, d, h, mi, s) / 1000; };
  let btV = 'cards';
  function btView(v){ btV = v; ['cards', 'run', 'res', 'tr'].forEach(x => $('btv-' + x).classList.toggle('on', x === v)); if (v === 'tr' && btChart) setTimeout(btResize, 30); }
  // 3.14: the Backtest page = one card per strategy; a card opens that strategy's dashboard. A strategy has ONE run: it is
  // created once ("Run once"), and every time the strategy is opened only the new vault days are run and added to it.
  function btCards(){
    api('bt_cards').then(r => {
      if (!r || !r.ok) { $('bt-cards').innerHTML = `<div class="sm">${esc((r && r.error) || 'Not available')}</div>`; return; }
      btS = r.strats || [];
      $('bt-meta').textContent = r.vinfo && r.vinfo.ok ? `${r.vinfo.days.toLocaleString()} vault days · ${r.vinfo.from} – ${r.vinfo.to}` : 'Vault not set';
      $('bt-cards').innerHTML = btS.map(s => {
        const l = s.last, t = (l && l.tot) || null, o = (l && l.oos) || {}, live = r.running && r.running.k === s.k;
        const side = String(s.side || '').toLowerCase();
        const head = `<div class="bch"><div class="bcn">${esc(s.name)}</div><span class="bcs ${side === 'short' ? 'short' : side === 'long' ? 'long' : ''}">${esc(String(s.side || '').toUpperCase())}</span></div>`;
        if (!l || (!t && !live)) return `<div class="bcard empty" data-bk="${esc(s.k)}">${head}<div class="bcp">No run yet</div></div>`;
        const foot = live ? '<span class="bcrun">Updating...</span>' : s.new_days ? `<span class="bcnew">${s.new_days.toLocaleString()} new vault days</span>` : '<span>Up to date</span>';
        return `<div class="bcard" data-bk="${esc(s.k)}">${head}<div class="bcp ${btc(t && t.pnl)}">${t ? btm(t.pnl) : '...'}</div>` +
          `<div class="bck"><div>Trades<b>${t ? t.n : '-'}</b></div><div>Win %<b>${t && t.win != null ? t.win + '%' : '-'}</b></div><div>Profit factor<b>${t && t.pf != null ? t.pf : '-'}</b></div><div>Out-of-sample PF<b>${o.pf ?? '-'}</b></div></div>` +
          `<div class="bcf">${foot}<span style="margin-left:auto">${l.updated ? 'updated ' + esc(l.updated) : ''}</span></div></div>`;
      }).join('');
    });
  }
  $('bt-cards').addEventListener('click', e => { const c = e.target.closest('[data-bk]'); if (c) btOpenStrategy(c.dataset.bk); });
  function btOpenStrategy(k){
    btK = k; btStrats(); btRes = null; btRid = '';
    $('bt-upst').textContent = '';
    btRuns().then(list => {
      const m = list[0];
      if (m && (m.state === 'done' || m.state === 'stopped')) { btOpen(m.id); btAutoUpdate(false); }
      else if (m && m.state === 'running') { btWatch(); btView('run'); }
      else btView('run');
    });
  }
  function btAutoUpdate(manual){            // only the vault days the run has not covered yet; the run is replaced by the updated one
    $('bt-upst').textContent = 'Checking the vault for new ticker-days...';
    api('bt_update', btK).then(r => {
      if (!r || !r.ok) { $('bt-upst').textContent = ''; if (manual || (r && r.error && !/already running/.test(r.error))) toast({kind: 'warn', text: 'Update: ' + ((r && r.error) || 'could not start')}); return; }
      if (r.uptodate) { $('bt-upst').textContent = 'Up to date - no new ticker-days in the vault'; return; }
      $('bt-upst').textContent = `Updating ${r.new.toLocaleString()} new ticker-days...`;
      toast({kind: 'info', text: `Backtest update: ${r.new.toLocaleString()} new ticker-days (the rest is kept as it is)`});
      btWatch();
    });
  }
  function btLoad(){
    api('bt_list').then(r => {
      if (!r || !r.ok) { $('bt-meta').textContent = (r && r.error) || 'Not available'; return; }
      btS = r.strats || []; if (!btS.some(s => s.k === btK) && btS.length) btK = btS[0].k;
      $('bt-vault').value = r.vault || '';
      $('bt-meta').textContent = r.vinfo && r.vinfo.ok ? `${r.vinfo.days.toLocaleString()} days · ${r.vinfo.from} – ${r.vinfo.to}` : 'Vault not set';
      const c = r.last || {};
      $('bt-from').value = c.from || ''; $('bt-to').value = c.to || ''; $('bt-days').value = c.days || 'all'; $('bt-list').value = c.list || '';
      $('bt-loc').value = c.locate ?? 3; $('bt-slip').value = c.slip ?? 0.1; $('bt-bal').value = c.start_bal ?? 10000;
      $('bt-cp').value = c.comp_pct ?? 20; $('bt-cm').value = c.comp_max ?? 50000; $('bt-cml').value = c.comp_max_long ?? 10000; $('bt-procs').value = c.procs ?? 0;
      $('bt-listw').classList.toggle('hidden', $('bt-days').value !== 'list');
      btFoldSum(); if (!r.running && !btPoll) $('bt-progc').classList.add('hidden');
      btStrats(); btCards(); btView('cards'); if (r.running) { btWatch(); }
    });
  }
  function btStrats(){
    const live = btS.filter(s => s.engine !== 'custom'), own = btS.filter(s => s.engine === 'custom');
    const b = s => `<button data-bk="${esc(s.k)}" class="${s.k === btK ? 'on' : ''}">${esc(s.name)}</button>`;   // 3.13.1: names only
    $('bt-strats').innerHTML = live.map(b).join('') + own.map(b).join('');
    const s = btS.find(x => x.k === btK); $('bt-sname').textContent = s ? s.name : '-';
  }
  function btRuns(){ return api('bt_runs', btK).then(r => { btList = (r && r.runs) || []; return btList; }); }
  // 3.12.2: the run settings fold away (closed by default; remembered on this PC)
  function btFoldSum(){ const c = btCfg();
    $('bt-foldsum').textContent = `${c.from || 'start'} to ${c.to || 'end'} - ${c.days === 'fav' ? 'favorites' : c.days === 'list' ? 'list file' : 'all vault days'} - locate ${c.locate}% - slip ${c.slip}% - $${(c.start_bal || 0).toLocaleString()} start, ${c.comp_pct}% per trade (short max $${(c.comp_max || 0).toLocaleString()}, long max $${(c.comp_max_long || 0).toLocaleString()})`; }
  function btFold(open){ $('bt-setc').classList.toggle('hidden', !open); $('bt-fold').setAttribute('aria-expanded', open ? 'true' : 'false');
    try { localStorage.setItem('btFold', open ? '1' : '0'); } catch (e) {} }
  $('bt-fold').addEventListener('click', () => btFold($('bt-setc').classList.contains('hidden')));
  try { if (localStorage.getItem('btFold') === '1') btFold(true); } catch (e) {}
  $('bt-setc').addEventListener('input', btFoldSum);
  function btCfg(){ const n = id => parseFloat($(id).value);
    return {from: $('bt-from').value.trim(), to: $('bt-to').value.trim(), days: $('bt-days').value, list: $('bt-list').value.trim(),
      locate: n('bt-loc'), slip: n('bt-slip'), start_bal: n('bt-bal'), comp_pct: n('bt-cp'), comp_max: n('bt-cm'), comp_max_long: n('bt-cml'), procs: parseInt($('bt-procs').value || '0', 10) || 0}; }
  function btWatch(){
    clearInterval(btPoll); $('bt-progc').classList.remove('hidden'); $('bt-go').disabled = true; $('bt-stop').classList.remove('hidden');
    btPoll = setInterval(() => api('bt_status').then(r => {
      const j = r && r.job; if (!j) return;
      const pc = j.total ? Math.round(100 * (j.done || 0) / j.total) : 0;
      $('bt-progb').style.width = pc + '%';
      $('bt-progt').textContent = j.state === 'running' ? `Running ${esc(j.k)}: ${(j.done || 0).toLocaleString()} / ${(j.total || 0).toLocaleString()} ticker-days (saved days are reused) - ${j.trades || 0} trades so far` :
        j.state === 'error' ? 'Backtest failed: ' + (j.error || '') : `Finished: ${j.trades || 0} trades in ${j.secs || '-'} s`;
      if (j.state !== 'running' || !j.alive) {
        clearInterval(btPoll); btPoll = null; $('bt-go').disabled = false; $('bt-stop').classList.add('hidden');
        $('bt-progc').classList.add('hidden');            // 3.12.2: the bar only shows while a run is going
        if (j.state === 'error') toast({kind: 'err', text: 'Backtest failed: ' + (j.error || 'unknown error')});
        $('bt-upst').textContent = j.state === 'error' ? '' : 'Up to date';
        if ((j.state === 'done' || j.state === 'stopped') && btV !== 'cards' && j.k === btK) btOpen(j.rid);   // the updated run replaces the old one
        if (btV === 'cards') btCards();
      }
    }), 1000);
  }
  function btOpen(rid){
    btRid = rid;
    api('bt_result', btK, rid).then(r => {
      if (!r || !r.ok) { toast({kind: 'err', text: 'Backtest: ' + ((r && r.error) || 'no result')}); return; }
      if (!r.summary) { toast({kind: 'warn', text: r.progress && r.progress.state === 'running' ? 'Still running' : 'This run has no result (' + ((r.progress && r.progress.error) || 'not finished') + ')'}); return; }
      btRes = r; btRenderRes(); btView('res');
    });
  }
  function btRenderRes(){
    const r = btRes, sm = r.summary, t = sm.tot, s = btS.find(x => x.k === btK), c = r.job || {};
    $('bt-rtitle').textContent = s ? s.name : btK;
    $('bt-rsub').textContent = `${sm.updated ? 'updated ' + sm.updated + ' - ' : ''}${c.from || 'start'} to ${c.to || 'end'} - ${(sm.days_run || 0).toLocaleString()} ticker-days - locate ${c.locate}% - slippage ${c.slip}%${sm.missing ? ' - ' + sm.missing + ' not in the vault' : ''}${sm.errors && sm.errors.length ? ' - ' + sm.errors.length + ' errors' : ''}${sm.stopped ? ' - STOPPED early' : ''}`;
    const sb = Number(c.start_bal || 10000), cmS = Number(c.comp_max || 50000), cmL = Number(c.comp_max_long || 10000);
    const K = [['Trades', t.n, ''], ['Win %', t.win == null ? '-' : t.win + '%', ''],
      ['P&L', `<span class="${btc(t.pnl)}">${btm(t.pnl)}</span>`, `$${sb.toLocaleString()} -> $${Number(t.comp_end || 0).toLocaleString()} - ${c.comp_pct || 20}% per trade, short max $${cmS.toLocaleString()}, long max $${cmL.toLocaleString()}, after costs`],
      ['Profit factor', t.pf ?? '-', ''], ['Without best 5', `<span class="${btc(t.no5)}">${btm(t.no5)}</span>`, ''], ['Max drawdown', btm(-t.dd), t.comp_dd_pct != null ? t.comp_dd_pct + '% of the account at its peak' : ''],
      ['Out-of-sample PF', (sm.halves[1] || {}).pf ?? '-', `${(sm.halves[1] || {}).n || 0} trades`]];
    $('bt-kpi').innerHTML = K.map(([l, v, sub]) => `<div>${l}<b>${v}</b>${sub ? '<span>' + sub + '</span>' : ''}</div>`).join('');
    const eq = sm.eq || [], svg = $('bt-eq');
    if (eq.length > 1) { const lo = Math.min(0, ...eq), hi = Math.max(0, ...eq), rg = (hi - lo) || 1, n = eq.length - 1;
      const y = v => 165 - (v - lo) / rg * 158, pts = eq.map((v, i) => `${(i / n * 600).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
      const cutI = r.trades.findIndex(x => x.day >= sm.cut);
      svg.innerHTML = `<line x1="0" x2="600" y1="${y(0)}" y2="${y(0)}" stroke="#2a2f3a"/>` + (cutI > 0 ? `<line x1="${cutI / n * 600}" x2="${cutI / n * 600}" y1="0" y2="170" stroke="#3a404c" stroke-dasharray="4 4"/>` : '') +
        `<polyline points="${pts}" fill="none" stroke="${eq[n] >= 0 ? '#22ab94' : '#f23645'}" stroke-width="1.6" vector-effect="non-scaling-stroke"/>`;
      $('bt-eqs').textContent = cutI > 0 ? `dashed line = out-of-sample from ${sm.cut}` : '';
    } else { svg.innerHTML = ''; $('bt-eqs').textContent = 'no trades'; }
    btRenderBrk(); btRenderTrades();
  }
  function btRenderBrk(){
    const sm = btRes.summary, rows = btBy === 'halves' ? sm.halves : (sm.by[btBy] || []);
    $('bt-brk').innerHTML = '<div class="btrow h"><span>' + (btBy === 'halves' ? 'PERIOD' : btBy.toUpperCase()) + '</span><span>TRADES</span><span>WIN %</span><span>P&amp;L</span><span>PF</span><span>W/O BEST 5</span></div>' +
      rows.map(b => `<div class="btrow"><span>${esc(b.name)}</span><span>${b.n}</span><span>${b.win == null ? '-' : b.win + '%'}</span><span class="${btc(b.pnl)}">${btm(b.pnl)}</span><span>${b.pf ?? '-'}</span><span class="${btc(b.no5)}">${btm(b.no5)}</span></div>`).join('');
  }
  function btShown(){ const T = btRes ? btRes.trades : [];
    return T.map((t, i) => [t, i]).filter(([t]) => btTF === 'all' || (btTF === 'win' && t.pnl > 0) || (btTF === 'loss' && t.pnl <= 0) || (btTF === 'note' && (t.verdict || t.nnote))); }
  function btRenderTrades(){
    const S = btShown();
    $('bt-trades').innerHTML = '<div class="btrow h"><span>#</span><span>TICKER</span><span>DAY</span><span>SETUP</span><span>ENTRY</span><span>STOP</span><span>EXIT</span><span>TIME</span><span>RESULT</span><span>P&amp;L</span><span>YOUR NOTE</span></div>' +
      (S.length ? S.slice(0, 1500).map(([t, i]) => `<div class="btrow click" data-bti="${i}"><span class="sm">${i + 1}</span><b>${esc(t.tk)}</b><span>${esc(t.day)}</span><span>${esc(t.setup)}</span>` +
        `<span>${fmtPx(t.entry)}</span><span>${fmtPx(t.stop)}</span><span>${fmtPx(t.exit)}</span><span class="sm">${esc((t.entry_hms || '').slice(0, 5))}</span><span class="sm">${esc(t.result)}</span>` +
        `<span class="${btc(t.pnl)}">${btm(t.pnl)}</span><span style="color:#fde68a">${esc(t.verdict ? t.verdict + (t.note1 ? ' - ' : '') : '')}${esc(t.note1 || '')}</span></div>`).join('')
        : '<div class="sm" style="padding:8px 6px">No trade in this filter.</div>');
  }
  function btResize(){ const el = $('bt-chart'), d = $('bt-daily'); if (btChart && el.clientWidth) btChart.resize(el.clientWidth, el.clientHeight); if (btDay && d.clientWidth) btDay.resize(d.clientWidth, d.clientHeight); }
  function btMkChart(){
    if (btChart) return;
    const opt = {layout: {background: {color: '#000'}, textColor: '#9aa3b2', fontSize: 11}, grid: {vertLines: {visible: false}, horzLines: {visible: false}},
      timeScale: {timeVisible: true, secondsVisible: false, borderColor: '#222'}, rightPriceScale: {borderColor: '#222'}, crosshair: {mode: 0}};
    btChart = LWC.createChart($('bt-chart'), opt);
    btSer = btChart.addCandlestickSeries({upColor: '__UP__', downColor: '__DOWN__', borderVisible: false, wickUpColor: '__UP__', wickDownColor: '__DOWN__'});
    btVw = btChart.addLineSeries({color: '__VWAP__', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false});
    btDay = LWC.createChart($('bt-daily'), Object.assign({}, opt, {timeScale: {timeVisible: false, borderColor: '#222'}, handleScroll: false, handleScale: false}));
    btDSer = btDay.addCandlestickSeries({upColor: '__UP__', downColor: '__DOWN__', borderVisible: false, wickUpColor: '__UP__', wickDownColor: '__DOWN__'});
    cnAttachBt();                                     // 3.14: right click -> Add note; the numbered badges (09b_chart_notes.js)
    window.addEventListener('resize', btResize);
  }
  function btMarkers(){
    const t = btCur; if (!t) return;
    const short = t.side !== 'Long', m = [];
    const fl = s => Math.floor(btEpoch(t.day, s) / 60) * 60;
    if (t.entry_hms) m.push({time: fl(t.entry_hms), position: short ? 'aboveBar' : 'belowBar', color: short ? '#ff1744' : '#00e676', shape: short ? 'arrowDown' : 'arrowUp', text: ''});
    if (t.exit_hms) m.push({time: fl(t.exit_hms), position: short ? 'belowBar' : 'aboveBar', color: short ? '#00e676' : '#ff1744', shape: short ? 'arrowUp' : 'arrowDown', text: ''});
    m.sort((a, b) => a.time - b.time); btSer.setMarkers(m);
  }
  function btRenderNotes(){                          // 3.14: the verdict (per strategy); the notes are chart notes (cnRenderBtList)
    const n = btNotes || {}; btVerd = n.verdict || '';
    document.querySelectorAll('#bt-verd [data-vd]').forEach(b => b.classList.toggle('on', b.dataset.vd === btVerd));
  }
  function btOpenTrade(i){
    const T = btRes.trades; if (i < 0 || i >= T.length) return;
    btI = i; btCur = T[i]; cnBars = []; cnRenderBtList(); cnLoad(btCur.tk);
    const t = btCur, s = btS.find(x => x.k === btK);
    $('bt-ttitle').textContent = `${t.tk} - ${t.day}`; $('bt-tsub').textContent = `Trade ${i + 1} of ${T.length} - ${s ? s.name : ''}`;
    const F = [['Setup', esc(t.setup)], ['Result', esc(t.result)], ['Entry', `${fmtPx(t.entry)} - ${esc((t.entry_hms || '').slice(0, 5))}`], ['Exit', `${fmtPx(t.exit)} - ${esc((t.exit_hms || '').slice(0, 5))}`],
      ['Stop', t.stop ? `${fmtPx(t.stop)} (${(Math.abs(t.stop / t.entry - 1) * 100).toFixed(1)}%)` : '-'], ['P&L', `<span class="${btc(t.pnl)}">${btm(t.pnl)}</span> (${t.ret_pct == null ? '-' : t.ret_pct.toFixed(1) + '%'})`]];
    $('bt-facts').innerHTML = F.map(([l, v]) => `<div>${l}<b>${v}</b></div>`).join('') + (t.note ? `<div style="grid-column:1/-1">Why<b style="font-weight:400;font-size:12px;white-space:normal">${esc(t.note)}</b></div>` : '');
    btView('tr'); btMkChart(); setTimeout(btResize, 30);
    btSer.setData([]); btVw.setData([]); btDSer.setData([]); btSer.setMarkers([]);
    if (btStopLine) { btSer.removePriceLine(btStopLine); btStopLine = null; }
    api('bt_bars', t.tk, t.day).then(r => {
      if (btCur !== t) return;
      if (!r || !r.ok) { toast({kind: 'warn', text: `${t.tk} ${t.day}: no bars in the vault`}); return; }
      btSer.setData(r.bars.map(b => ({time: b.time, open: b.open, high: b.high, low: b.low, close: b.close})));
      btVw.setData(r.bars.map(b => ({time: b.time, value: b.vwap})));
      btDSer.setData(r.daily || []); btDay.timeScale().fitContent(); cnBtSetBars(r.bars);
      if (t.stop) btStopLine = btSer.createPriceLine({price: t.stop, color: '#ffd600', lineWidth: 1, lineStyle: LWC.LineStyle.Dashed, axisLabelVisible: true, title: 'stop'});
      const e = Math.floor(btEpoch(t.day, t.entry_hms) / 60) * 60;
      btChart.timeScale().setVisibleRange({from: e - 3 * 3600, to: Math.max(e + 3 * 3600, Math.floor(btEpoch(t.day, t.exit_hms || '16:00:00') / 60) * 60 + 1800)});
      btMarkers();
    });
    api('bt_notes', btK, t.tk, t.day).then(n => { if (btCur === t && n && n.ok) { btNotes = n; btRenderNotes(); } });
  }
  function btNoteSync(n){ btNotes = n; btRenderNotes(); const t = btCur; if (!t) return;     // the verdict of this ticker-day
    (btRes.trades || []).forEach(x => { if (x.tk === t.tk && x.day === t.day) x.verdict = n.verdict || ''; }); }
  let btDelArm = false, btDelT = null;
  $('bt-upd').addEventListener('click', () => btAutoUpdate(true));
  $('bt-reset').addEventListener('click', () => {                 // delete the run (and its notes) to start over - click twice
    const b = $('bt-reset');
    if (!btDelArm) { btDelArm = true; b.textContent = 'Click again to confirm'; clearTimeout(btDelT); btDelT = setTimeout(() => { btDelArm = false; b.textContent = 'Delete run'; }, 4000); return; }
    btDelArm = false; clearTimeout(btDelT); b.textContent = 'Delete run';
    api('bt_delete', btK, btRid).then(r => {
      if (!r || !r.ok) { toast({kind: 'err', text: (r && r.error) || 'Not deleted'}); return; }
      btRes = null; btRid = ''; toast({kind: 'info', text: 'Run deleted with its verdicts - your chart notes are kept'}); btView('run');
    });
  });
  $('bt-days').addEventListener('change', () => $('bt-listw').classList.toggle('hidden', $('bt-days').value !== 'list'));
  $('bt-vset').addEventListener('click', () => api('bt_vault', $('bt-vault').value).then(r => { if (r && r.ok) { toast({kind: 'info', text: 'Vault set'}); btLoad(); } else toast({kind: 'err', text: (r && r.error) || 'Vault not found'}); }));
  $('bt-go').addEventListener('click', () => api('bt_run', btK, btCfg()).then(r => {
    if (r && r.ok) { toast({kind: 'info', text: `Backtest started: ${r.n.toLocaleString()} ticker-days`}); btWatch(); }
    else toast({kind: 'err', text: 'Backtest: ' + ((r && r.error) || 'could not start')}); }));
  $('bt-stop').addEventListener('click', () => api('bt_stop').then(() => toast({kind: 'info', text: 'Stopping the backtest - the trades so far are kept'})));
  document.querySelectorAll('[data-btback]').forEach(b => b.addEventListener('click', () => { const v = b.dataset.btback; if (v === 'res') btRenderTrades(); else if (v === 'cards') btCards(); btView(v); }));
  $('bt-by').addEventListener('click', e => { const b = e.target.closest('[data-v]'); if (!b) return; btBy = b.dataset.v;
    document.querySelectorAll('#bt-by button').forEach(x => x.classList.toggle('on', x === b)); btRenderBrk(); });
  $('bt-tf').addEventListener('click', e => { const b = e.target.closest('[data-v]'); if (!b) return; btTF = b.dataset.v;
    document.querySelectorAll('#bt-tf button').forEach(x => x.classList.toggle('on', x === b)); btRenderTrades(); });
  $('bt-trades').addEventListener('click', e => { const r = e.target.closest('[data-bti]'); if (r) btOpenTrade(Number(r.dataset.bti)); });
  const btStep = d => { const S = btShown().map(x => x[1]); const k = S.indexOf(btI); if (k >= 0 && S[k + d] != null) btOpenTrade(S[k + d]); };
  $('bt-prev').addEventListener('click', () => btStep(-1)); $('bt-next').addEventListener('click', () => btStep(1));
  $('bt-verd').addEventListener('click', e => { const b = e.target.closest('[data-vd]'); if (!b || !btCur) return; const v = btVerd === b.dataset.vd ? '' : b.dataset.vd;
    api('bt_note_save', btK, btCur.tk, btCur.day, v).then(n => { if (n && n.ok) btNoteSync(n); }); });

