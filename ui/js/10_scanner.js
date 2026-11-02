  // ---- Scanner (runs only while open: IBKR top % gainers + live quotes) ----
  const pct = v => v == null ? '-' : (v >= 0 ? '+' : '') + v.toFixed(1) + '%';
  function scanSegs(){
    document.querySelectorAll('#sc-up button').forEach(b => b.classList.toggle('on', Number(b.dataset.v) === scanCfg.up));
    document.querySelectorAll('#sc-px button').forEach(b => b.classList.toggle('on', Number(b.dataset.v) === scanCfg.px));
  }
  $('sc-up').addEventListener('click', e => { const b = e.target.closest('[data-v]'); if (!b) return; scanCfg.up = Number(b.dataset.v); scanSegs(); api('scan_screen', true, scanCfg); });
  $('sc-px').addEventListener('click', e => { const b = e.target.closest('[data-v]'); if (!b) return; scanCfg.px = Number(b.dataset.v); scanSegs(); api('scan_screen', true, scanCfg); });
  function scanChips(r){
    if (r.watch) {
      const pos = /^(SHORT|YOUR SHORT)/.test(r.status || '');
      return `<span class="chipx ${pos ? 'pos' : 'wl'}" title="${esc(r.status)}">${esc(r.status || 'on the watchlist')}</span>`;
    }
    return (r.chips || []).map(c => `<span class="chipx ${c.ok ? 'ok' : 'no'}" title="${esc(c.t)}">${esc(c.t.split(':')[0])} ${c.ok ? '&#10003;' : '&ndash;'}</span>`).join('');
  }
  function scanDetail(r){
    const need = (r.chips || []).map(c => `<div class="need"><i class="${c.ok ? 'ok' : ''}"></i><span>${esc(c.t)}</span></div>`).join('');
    return `<div><span class="big">${esc(r.sym)}</span><span style="font-size:15px;color:#fff;margin-left:10px">${fmtPx(r.last)}</span>` +
      `<span class="sc-chg${(r.chg || 0) < 0 ? ' neg' : ''}" style="margin-left:8px">${pct(r.chg)}</span>${r.halt ? ' <span class="chipx pos">HALTED</span>' : ''}</div>` +
      `<div class="kv"><div><span>Prior close</span><b>${fmtPx(r.pc)}</b></div><div><span>Day high</span><b>${fmtPx(r.hi)}</b></div>` +
      `<div><span>Volume</span><b>${fmtV(r.vol)}</b></div><div><span>$ Volume</span><b>${r.dol ? '$' + fmtV(r.dol) : '-'}</b></div>` +
      `<div><span>Volume vs an average day</span><b>${r.rvol == null ? '-' : r.rvol.toFixed(1) + 'x'}</b></div><div><span>Under the high</span><b>${r.from == null ? '-' : r.from.toFixed(1) + '%'}</b></div></div>` +
      (r.watch ? `<div class="jt">On the bot watchlist</div><div class="bcnow" style="white-space:normal">${esc(r.status)}</div>` : '') +
      `<div class="jt">What each strategy needs</div>${need || '<div class="sm">-</div>'}` +
      `<div class="sm" style="white-space:normal;line-height:1.5">The strategies read only watchlist stocks. ${info.scanOn ? `The bot's own scanner adds stocks up ${info.scanUp}%+ by itself (07:00-15:00).` : 'The auto short-scanner is off - add stocks yourself.'}</div>` +
      `<div style="display:flex;gap:8px;margin-top:auto"><button class="sbtn" style="flex:1;height:32px" data-scc="${esc(r.sym)}">Open chart</button>` +
      (r.watch ? '' : `<button class="sbtn pri" style="flex:1;height:32px" data-scw="${esc(r.sym)}">Add to watchlist</button>`) +
      `<button class="sbtn" style="height:32px" data-scf="${esc(r.sym)}" title="Favorites">${isFav(r.sym) ? '&#9829; Favorite' : '&#9825; Favorite'}</button>` + '</div>';
  }
  function renderScan(){
    scanSegs();
    const p = scan || {rows: [], at: '', err: '', n: 0};
    $('sc-meta').textContent = p.err ? p.err : `${p.n || 0} stocks up ${scanCfg.up}%+ from $${scanCfg.px} - ` + (p.at ? `scanned ${p.at} ET, quotes live` : 'scanning...');
    $('sc-meta').className = 'sm' + (p.err ? ' jred' : '');
    const rows = p.rows || [];
    if (rows.length && !rows.some(x => x.sym === scanSel)) scanSel = rows[0].sym;
    $('sc-list').innerHTML = rows.length ? rows.map(r => `<div class="scrow scgrid${r.sym === scanSel ? ' sel' : ''}" data-sc="${esc(r.sym)}">` +
      `<span class="o-t">${r.n}</span><span class="sc-sym"><b>${esc(r.sym)}</b>${r.halt ? '<i>HALT</i>' : ''}</span><span class="r">${fmtPx(r.last)}</span>` +
      `<span class="r sc-chg${(r.chg || 0) < 0 ? ' neg' : ''}">${pct(r.chg)}</span><span class="r">${fmtV(r.vol)}</span>` +
      `<span class="r">${r.dol ? '$' + fmtV(r.dol) : '-'}</span><span class="r">${r.rvol == null ? '-' : r.rvol.toFixed(1) + 'x'}</span>` +
      `<span class="r">${r.from == null ? '-' : '-' + r.from.toFixed(0) + '%'}</span><span style="min-width:0;overflow:hidden">${scanChips(r)}</span>` +
      `<span class="scbtn"><button class="sbtn" data-scc="${esc(r.sym)}">Chart</button>` +
      (r.watch ? '<button class="sbtn" disabled>Watching</button>' : `<button class="sbtn" data-scw="${esc(r.sym)}">+ Watch</button>`) + '</span></div>').join('')
      : `<div class="oempty">${p.err ? esc(p.err) : 'Waiting for the first scan (IBKR top % gainers)...'}</div>`;
    const sel = rows.find(x => x.sym === scanSel);
    $('sc-det').innerHTML = sel ? scanDetail(sel) : '<div class="sm">Click a row for the details.</div>';
  }
  // main chart page: compact live scanner under the watchlist (symbol, last, % up); click = load that chart
  function renderMiniScan(){
    const p = scan || {rows: [], err: ''}, rows = p.rows || [];
    $('ms-meta').textContent = p.err ? p.err : `${rows.length} up ${scanCfg.up}%+`;
    $('ms-list').innerHTML = rows.length ? rows.map(r => `<div class="msrow" data-ms="${esc(r.sym)}"><b>${esc(r.sym)}</b>` +
      `<span class="r">${fmtPx(r.last)}</span><span class="r up${(r.chg || 0) < 0 ? ' neg' : ''}">${pct(r.chg)}</span></div>`).join('')
      : `<div class="empty-sig">${p.err ? esc(p.err) : 'Waiting for the first scan...'}</div>`;
  }
  $('ms-list').addEventListener('click', e => {
    const r = e.target.closest('[data-ms]'); if (!r) return;
    api('load_symbol', r.dataset.ms).then(res => { if (res && res.recent) setRecent(res.recent); });
  });
  whenApi(() => api('scan_screen', true, scanCfg));          // the scanner now runs all the time (the chart page shows it too)
  $('scr-scan').addEventListener('click', e => {
    const c = e.target.closest('[data-scc]');
    if (c) { api('load_symbol', c.dataset.scc).then(res => { if (res && res.recent) setRecent(res.recent); }); showScreen('chart'); return; }
    const w = e.target.closest('[data-scw]');
    if (w) { api('bot_add', w.dataset.scw); toast({kind: 'info', text: `${w.dataset.scw} added to the watchlist`}); return; }
    const f = e.target.closest('[data-scf]');
    if (f) { favToggle(f.dataset.scf); return; }
    const rw = e.target.closest('[data-sc]'); if (rw) { scanSel = rw.dataset.sc; renderScan(); }
  });
  $('scr-scan').addEventListener('dblclick', e => {           // 3.12.1: double click a row = open its chart
    if (e.target.closest('button')) return;
    const rw = e.target.closest('[data-sc]'); if (!rw) return;
    api('load_symbol', rw.dataset.sc).then(res => { if (res && res.recent) setRecent(res.recent); }); showScreen('chart');
  });

