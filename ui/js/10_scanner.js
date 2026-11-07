  // ---- Scanner (runs only while open: IBKR top % gainers + live quotes) ----
  const pct = v => v == null ? '-' : (v >= 0 ? '+' : '') + v.toFixed(1) + '%';
  function scanSegs(){
    document.querySelectorAll('#sc-up button').forEach(b => b.classList.toggle('on', Number(b.dataset.v) === scanCfg.up));
    document.querySelectorAll('#sc-px button').forEach(b => b.classList.toggle('on', Number(b.dataset.v) === scanCfg.px));
  }
  $('sc-up').addEventListener('click', e => { const b = e.target.closest('[data-v]'); if (!b) return; scanCfg.up = Number(b.dataset.v); scanSegs(); api('scan_screen', true, scanCfg); });
  $('sc-px').addEventListener('click', e => { const b = e.target.closest('[data-v]'); if (!b) return; scanCfg.px = Number(b.dataset.v); scanSegs(); api('scan_screen', true, scanCfg); });
  // ---- 3.15: Scanner cards (List | Cards) - price line like the Discord chart: price, VWAP, prior close, HOD, now ----
  const sparkC = {};
  function cardLine(r){
    const s = sparkC[r.sym];
    if (!s || !s.p || s.p.length < 2) return '<div class="cdl cdl-wait">chart loading...</div>';
    const W = 300, H = 118, R = W - 46, T = 14, B = 96, n = s.p.length;
    const stop = r.pos && r.pos.stop, hod = s.hod || Math.max(...s.p);
    const lo = Math.min(...s.p.filter(v => v != null), r.pc || Infinity) * 0.97, hi = Math.max(hod, stop || 0) * 1.03;
    const X = x => (x * R).toFixed(1), Y = v => (B - (v - lo) / ((hi - lo) || 1) * (B - T)).toFixed(1);
    const halt = r.halt, lc = halt ? '#fbbf24' : '#e2e8f0';
    const pts = s.p.map((v, i) => `${X(s.x[i])},${Y(v)}`).join(' ');
    const wv = s.w.map((v, i) => v == null || (s.x930 != null && s.x[i] < s.x930) ? null : `${X(s.x[i])},${Y(v)}`).filter(Boolean).join(' ');
    let hiI = 0; s.p.forEach((v, i) => { if (v > s.p[hiI]) hiI = i; });
    const last = s.p[n - 1], ly = +Y(last), fh = hod ? Math.round((last / hod - 1) * 100) : 0, bad = fh <= -20;
    const id = 'g' + r.sym.replace(/[^A-Z0-9]/g, '');
    let ex = '';
    if (s.x930 != null) ex += `<rect x="0" y="${T - 6}" width="${X(s.x930)}" height="${B - T + 6}" fill="rgba(255,255,255,.025)"/>`;
    if (r.pc) ex += `<line x1="0" x2="${R}" y1="${Y(r.pc)}" y2="${Y(r.pc)}" stroke="#475569" stroke-dasharray="2 3"/><text x="2" y="${+Y(r.pc) - 3}" fill="#64748b" font-size="9">close ${fmtPx(r.pc)}</text>`;
    if (stop) ex += `<line x1="0" x2="${R}" y1="${Y(stop)}" y2="${Y(stop)}" stroke="#f43f5e" stroke-dasharray="3 3"/><text x="2" y="${+Y(stop) - 3}" fill="#fb7185" font-size="9">stop ${fmtPx(stop)}</text>`;
    if (r.pos && r.pos.avg) ex += `<line x1="0" x2="${R}" y1="${Y(r.pos.avg)}" y2="${Y(r.pos.avg)}" stroke="#818cf8" stroke-dasharray="1 3"/><path d="M${R - 5},${+Y(r.pos.avg) - 12} l10,0 l-5,8z" fill="#f43f5e"/>`;
    if (halt) ex += `<rect x="${R - 14}" y="${T - 6}" width="14" height="${B - T + 6}" fill="rgba(245,158,11,.16)"/><text x="${R - 16}" y="${T}" fill="#fbbf24" font-size="9" text-anchor="end">halt</text>`;
    const tl = m => String(Math.floor(m / 60)).padStart(2, '0') + ':' + String(m % 60).padStart(2, '0');
    return `<div class="cdl"><svg viewBox="0 0 ${W} ${H}">` +
      `<defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${lc}" stop-opacity=".16"/><stop offset="1" stop-color="${lc}" stop-opacity="0"/></linearGradient></defs>` + ex +
      `<polygon points="0,${B} ${pts} ${X(s.x[n - 1])},${B}" fill="url(#${id})"/>` +
      (wv ? `<polyline points="${wv}" fill="none" stroke="#f5a623" stroke-width="1.3"/>` : '') +
      `<polyline points="${pts}" fill="none" stroke="${lc}" stroke-width="1.6" stroke-linejoin="round"/>` +
      `<circle cx="${X(s.x[hiI])}" cy="${Y(s.p[hiI])}" r="2.6" fill="#94a3b8"/><text x="${X(s.x[hiI])}" y="${+Y(s.p[hiI]) - 5}" fill="#94a3b8" font-size="9" text-anchor="middle">${fmtPx(hod)}</text>` +
      `<circle cx="${X(s.x[n - 1])}" cy="${ly}" r="7" fill="${lc}" opacity=".18"/><circle cx="${X(s.x[n - 1])}" cy="${ly}" r="3.2" fill="${lc}"/>` +
      `<rect x="${W - 42}" y="${ly - 10}" width="42" height="20" rx="5" fill="${bad ? 'rgba(244,63,94,.18)' : 'rgba(30,41,59,.9)'}" stroke="${bad ? 'rgba(244,63,94,.4)' : 'rgba(255,255,255,.08)'}"/>` +
      `<text x="${W - 21}" y="${ly + 4}" fill="${bad ? '#fb7185' : '#cbd5e1'}" font-size="10" font-weight="700" text-anchor="middle">${fh}%</text>` +
      `<g fill="#475569" font-size="9"><text x="0" y="${H - 4}">${tl(s.m0)}</text>` + (s.x930 != null && s.x930 > .12 && s.x930 < .8 ? `<text x="${X(s.x930)}" y="${H - 4}" text-anchor="middle">09:30</text>` : '') +
      `<text x="${R}" y="${H - 4}" text-anchor="end">now</text></g></svg></div>`;
  }
  function scanCard(r){
    const s = sparkC[r.sym], vw = s && s.w && s.w.length ? s.w[s.w.length - 1] : null;
    const inPos = !!r.pos, hot = (r.chg || 0) >= 150;
    const cls = (inPos ? ' pos' : r.halt ? ' halt' : hot ? ' hot' : '') + (r.sstop ? ' stopped' : '');
    const why = inPos ? `<span class="ind">SHORT ${Number(r.pos.qty).toLocaleString()} @ ${fmtPx(r.pos.avg)}${r.pos.stop ? ' · stop ' + fmtPx(r.pos.stop) : ''}</span>`
      : r.halt ? '<span class="amb">HALTED - prices ignored until the reopen</span>'
      : r.watch ? esc(r.status || 'On the watchlist')
      : esc(((r.chips || []).find(c => !c.ok) || (r.chips || [])[0] || {t: ''}).t);
    const st = (r.sstop ? '<span class="sc2 st">&#9940; Shorts stopped today</span>' : '') + (inPos ? '<span class="sc2 in">In trade</span>' : r.halt ? '<span class="sc2 rd">Halted</span>' : r.watch ? '<span class="sc2 ok">On the watchlist</span>' : '');
    const chips = (r.chips || []).map(c => `<span class="sc2 ${c.ok ? 'ok' : 'no'}" title="${esc(c.t)}">${esc(c.t.split(':')[0])} ${c.ok ? '&#10003;' : '&ndash;'}</span>`).join('');
    const fl = r.float ? fmtV(r.float.v) + (r.float.kind === 'O/S' ? '<small> O/S</small>' : '') : '-';
    return `<div class="sccard${cls}${r.sym === scanSel ? ' sel' : ''}" data-sc="${esc(r.sym)}">` +
      `<div class="cdt"><div><div class="cds">${esc(r.sym)}${r.halt ? '<span class="cdh">HALTED</span>' : ''}</div>` +
      `<div class="cdp">${fmtPx(r.last)}<small>${vw ? 'VWAP ' + fmtPx(vw) : ''}</small></div></div>` +
      `<span class="cdb${hot ? ' hot' : ''}${(r.chg || 0) < 0 ? ' neg' : ''}">${pct(r.chg)}</span></div>` + cardLine(r) +
      `<div class="cdst"><div><span>Vol</span><b>${fmtV(r.vol)}</b></div><div><span>$ Vol</span><b>${r.dol ? '$' + fmtV(r.dol) : '-'}</b></div>` +
      `<div><span>RVOL</span><b>${r.rvol == null ? '-' : r.rvol.toFixed(1) + 'x'}</b></div><div><span>Float</span><b>${fl}</b></div></div>` +
      `<div class="cdw">${why}</div><div class="cdf">${st}${r.watch ? '' : chips}</div>` +
      `<div class="cda"><button class="sbtn" data-scf="${esc(r.sym)}">${isFav(r.sym) ? '&#9829;' : '&#9825;'}</button>` +
      (r.watch ? '' : `<button class="sbtn" data-scw="${esc(r.sym)}">+ Watch</button>`) +
      `<button class="sbtn pri" data-scc="${esc(r.sym)}">Chart</button></div></div>`;
  }
  function renderScan(){
    scanSegs();
    const p = scan || {rows: [], at: '', err: '', n: 0};
    $('sc-meta').textContent = p.err ? p.err : `${p.n || 0} stocks up ${scanCfg.up}%+ from $${scanCfg.px}` +
      (p.hidden ? ` (${p.hidden} hidden: under ${fmtV(p.minVol || 0)} shares or over $${fmtV(p.maxCap || 0)})` : '') + ' - ' + (p.at ? `scanned ${p.at} ET, quotes live` : 'scanning...');
    $('sc-meta').className = 'sm' + (p.err ? ' jred' : '');
    const rows = p.rows || [];
    if (rows.length && !rows.some(x => x.sym === scanSel)) scanSel = rows[0].sym;
    rows.forEach(r => { if (r.spark) sparkC[r.sym] = r.spark; });
    $('sc-cards').innerHTML = rows.length ? rows.map(scanCard).join('') : `<div class="oempty">${p.err ? esc(p.err) : 'Waiting for the first scan (IBKR top % gainers)...'}</div>`;
  }
  function scanSelect(){                                     // highlight only
    document.querySelectorAll('#sc-cards [data-sc]').forEach(el => el.classList.toggle('sel', el.dataset.sc === scanSel));
  }
  // ---- 3.15: the Float chip (Alpha Vantage / SEC, with its age - free data can be old after an offering) ----
  let flSym = '', flInfo = null;
  function floatChip(){
    const c = $('c-float'), f = flInfo && flInfo.sym === sym && flInfo.v ? flInfo : null;
    c.querySelector('span').textContent = f ? fmtV(f.v) + (f.kind === 'O/S' ? ' O/S' : '') : '-';
    c.querySelector('.fage').textContent = f ? (f.age === 0 ? 'today' : f.age + 'd') : '';
    c.title = f ? `${f.kind === 'O/S' ? 'Shares outstanding (last SEC filing)' : 'Float'} - ${f.src}, as of ${f.asof || '?'}` : 'Float - not known yet';
  }
  setInterval(() => { if (sym && sym !== flSym) { flSym = sym; flInfo = null; floatChip();
    api('float_get', sym).then(r => { if (r && r.ok && r.sym === sym) { flInfo = r; floatChip(); } }); } }, 500);
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
    const rw = e.target.closest('[data-sc]'); if (rw) { scanSel = rw.dataset.sc; scanSelect(); }
  });
  $('scr-scan').addEventListener('dblclick', e => {           // 3.12.1: double click a row = open its chart
    if (e.target.closest('button')) return;
    const rw = e.target.closest('[data-sc]');                 // a scan landing between the two clicks: take the row
    const sy = rw ? rw.dataset.sc : (e.target.closest('#sc-cards') ? scanSel : '');     // the first click selected
    if (!sy) return;
    api('load_symbol', sy).then(res => { if (res && res.recent) setRecent(res.recent); }); showScreen('chart');
  });

