  // ---- Journal (today / week / month / all, from the bot's journals) ----
  const jm = v => v == null ? '-' : (v > 0 ? '+' : v < 0 ? '-' : '') + '$' + Math.abs(v).toLocaleString('en-US', {maximumFractionDigits: 0});
  const jc = v => v == null || v === 0 ? '' : v > 0 ? 'grn' : 'red';
  function loadJournal(){
    api('journal', jRange, jMonth).then(d => {
      if (d && d.ok) { jData = d; renderJournal(); if (jView === 'heat') renderHeat(); } else if (d) toast({kind: 'err', text: 'Journal: ' + d.error});
    });
  }
  function renderJournal(){
    const d = jData; if (!d) return;
    document.querySelectorAll('#jr-rng button').forEach(b => b.classList.toggle('on', b.dataset.v === jRange));
    $('j-meta').textContent = `${d.from === d.to ? d.to : (d.range === 'all' ? 'all days' : d.from + ' to ' + d.to)} - ${plural(d.days, 'day')} with trades`;
    $('j-src').textContent = d.source === 'tz' ? 'TradeZero fills' : 'Bot journal';
    const bt = info.btref || {}, btw = 'backtest 63% (584 days, all strategies)';
    const KP = [['Net P&L', `<b class="${jc(d.net)}">${jm(d.net)}</b>`, d.best != null ? `best day ${jm(d.best)} - worst ${jm(d.worst)}` : 'no closed trade'],
      ['Trades', `<b>${d.n}</b>`, `${d.shorts} short - ${d.longs} long`],
      ['Win rate', `<b>${d.win == null ? '-' : d.win + '%'}</b>`, btw],
      ['Avg win / loss', `<b>${d.avgWin == null ? '-' : jm(d.avgWin)} / ${d.avgLoss == null ? '-' : jm(d.avgLoss)}</b>`, d.payoff ? `payoff ${d.payoff}` : '-'],
      ['Max drawdown', `<b class="${d.mdd < 0 ? 'red' : ''}">${jm(d.mdd)}</b>`, 'peak to low, trade by trade'],
      ['Costs', `<b>${jm(-d.loc)}</b>`, 'locates paid' + (d.slip != null ? ` - long stop slip ${d.slip}% (${d.slipN})` : '')]];
    $('j-kpi').innerHTML = KP.map(([k, v, s]) => `<div class="jk"><span>${k}</span>${v}<small>${esc(s)}</small></div>`).join('');
    let cal = `<div class="jt"><span>${esc(d.monthName)}</span><span class="sm">day P&amp;L <button class="jnav" data-jm="-1">&lsaquo;</button> <button class="jnav" data-jm="1">&rsaquo;</button></span></div><div class="jcal">` +
      ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'].map(x => `<span class="h">${x}</span>`).join('');
    if (d.cal.length) for (let i = 0; i < d.cal[0].wd; i++) cal += '<span></span>';
    for (const c of d.cal) {
      const v = c.pnl, bg = v == null || v === 0 ? '' : v > 0 ? `background:rgba(16,185,129,${Math.min(.32, .08 + v / 12000).toFixed(2)})`
        : `background:rgba(244,63,94,${Math.min(.32, .08 - v / 6000).toFixed(2)})`;   // 3.14: tinted cells, coloured text
      cal += `<div class="c${v == null ? ' e' : v > 0 ? ' pos' : v < 0 ? ' neg' : ''}${c.today ? ' td' : ''}" style="${bg}" title="${plural(c.n, 'trade')}"><span>${c.d}</span><b>${v == null ? '&ndash;' : jm(v)}</b></div>`;
    }
    $('j-cal').innerHTML = cal + '</div>';
    const pts = [0].concat(d.eq || []), W = Math.max(300, Math.round($('j-eq').getBoundingClientRect().width) || 800), H = 240;
    $('j-eq').setAttribute('viewBox', `0 0 ${W} ${H}`);
    if (pts.length < 2) $('j-eq').innerHTML = '<text x="16" y="30" fill="#5f646c" font-size="13">No closed trade in this range.</text>';
    else {
      const lo = Math.min(0, ...pts), hi = Math.max(0, ...pts), sp = (hi - lo) || 1;
      const y = v => (H - 16 - (v - lo) / sp * (H - 36)).toFixed(1), x = i => (8 + i / (pts.length - 1) * (W - 16)).toFixed(1);
      const end = pts[pts.length - 1];
      $('j-eq').innerHTML = `<line x1="0" x2="${W}" y1="${y(0)}" y2="${y(0)}" stroke="#2a2d32" stroke-dasharray="4 4"/>` +
        `<polyline points="${pts.map((v, i) => x(i) + ',' + y(v)).join(' ')}" fill="none" stroke="${end >= 0 ? '#22ab94' : '#f23645'}" stroke-width="2"/>` +
        `<text x="${W - 8}" y="16" fill="#8b9099" font-size="13" text-anchor="end">${jm(end)} after ${plural(pts.length - 1, 'trade')}</text>`;
    }
    $('j-strat').innerHTML = `<div class="jt">By strategy <span class="sm">real trades vs the backtest</span></div><div class="jst h"><span>Strategy</span><span class="r">Trades</span><span class="r">Win</span><span class="r">Net</span><span class="r">Avg</span></div>` +
      d.strat.map(s => `<div class="jst"><span><b style="color:#fff;font-weight:600">${esc(s.name)}</b><small>backtest ${s.bt ? s.bt.n + ' trades, ' + s.bt.win + '% win' : '-'}</small></span>` +
        `<span class="r">${s.n}</span><span class="r">${s.win == null ? '-' : s.win + '%'}</span><span class="r j${jc(s.net)}">${jm(s.net)}</span><span class="r">${jm(s.avg)}</span></div>`).join('');
    const jt = $('j-trades').previousElementSibling;   // 3.15: the totals line - gross / locates / net (+ unused locates)
    if (jt) jt.innerHTML = `Trades<span class="jtot">` +
      `<span>Gross <b class="${jc(d.gross)}">${jm(d.gross)}</b></span><span>Locates <b class="${d.loc ? 'red' : ''}">${jm(-d.loc)}</b></span>` +
      (d.unused ? `<span title="${esc((d.unusedList || []).map(u => u.d + ' ' + u.sym + ' ' + jm(-u.cost)).join(', '))}">Unused locates <b class="red">${jm(-d.unused)}</b></span>` : '') +
      `<span>Net <b class="${jc(d.net)}">${jm(d.net)}</b></span></span>`;
    $('j-trades').innerHTML = `<div class="jtg h"><span>Date</span><span>Symbol</span><span>Side</span><span>Setup</span><span class="r">Entry</span><span class="r">Exit</span><span class="r">Shares</span><span class="r">Gross</span><span class="r">Locate</span><span class="r">Net</span><span>Result</span></div>` +
      (d.trades.length ? d.trades.map(t => `<div class="jtg"><span class="o-t">${esc(t.d.slice(5))} ${esc(t.tin)}</span><span class="o-s" data-os="${esc(t.sym)}">${esc(t.sym)}</span>` +
        `<span class="p-side ${t.side === 'Long' ? 'l' : 's'}">${esc(t.side)}</span><span class="o-ty">${esc(t.setup)}</span><span class="r">${fmtPx(t.entry)}</span>` +
        `<span class="r">${fmtPx(t.exit)}</span><span class="r">${Number(t.qty).toLocaleString('en-US')}</span><span class="r j${jc(t.net + (t.loc || 0))}">${jm(t.net + (t.loc || 0))}</span>` +
        `<span class="r">${t.loc ? `<span class="jred">${jm(-t.loc)}</span>${t.locType ? `<small>${esc(t.locType)}</small>` : ''}` : '-'}</span>` +
        `<span class="r j${jc(t.net)}">${jm(t.net)}</span><span class="o-ty">${esc(t.res)}</span></div>`).join('') : '<div class="oempty">No closed trade in this range.</div>');
  }
  $('jr-rng').addEventListener('click', e => { const b = e.target.closest('[data-v]'); if (b) { jRange = b.dataset.v; jMonth = ''; loadJournal(); if (jView === 'missed') loadMissed(); } });
  // ---- 3.15: Journal views - Trades / Missed (signals not taken, followed to their would-have exit) / Heat map ----
  let jView = 'trades', msData = null, hmStrat = 'all';
  const MS_CAT = ['Under the price minimum', 'No locate', 'Locate over 5%', 'Buying power', 'Halted at signal', 'Max trades reached', 'Paused', 'Alert only', 'Auto-trade off'];
  const msCls = c => /locate/i.test(c) ? 'a' : c === 'Buying power' ? 'r' : '';
  function jShowView(){
    document.querySelectorAll('#jr-view button').forEach(b => b.classList.toggle('on', b.dataset.v === jView));
    ['trades', 'missed', 'heat'].forEach(v => $('jv-' + v).classList.toggle('hidden', v !== jView));
    $('j-meta').style.display = $('j-src').style.display = jView === 'trades' ? '' : 'none';
    if (jView === 'missed') loadMissed();
    if (jView === 'heat') renderHeat();
  }
  function loadMissed(){
    api('missed_list', jRange).then(r => {
      if (!r || !r.ok) { $('ms-list').innerHTML = `<div class="oempty">${esc((r && r.error) || 'Not available')}</div>`; return; }
      msData = r; renderMissed();
    });
  }
  function renderMissed(){
    const r = msData; if (!r) return;
    const cats = r.cats || {}, top = Object.entries(cats).sort((a, b) => b[1].n - a[1].n)[0];
    const K = [['Missed signals', `<b>${r.n}</b>`, r.open ? `${r.open} still followed` : 'trades the bot did not take'],
      ['Would have made', `<b class="${jc(r.pnl)}">${jm(r.pnl)}</b>`, 'at the sizing of that moment, after 3% locate'],
      ['Would-have win %', `<b>${r.done ? Math.round(100 * r.wins / r.done) + '%' : '-'}</b>`, `${r.wins} of ${r.done}`],
      ['Top reason', `<b>${top ? esc(top[0]) : '-'}</b>`, top ? `${top[1].n} signal${top[1].n === 1 ? '' : 's'} - ${jm(top[1].pnl)}` : '-']];
    $('ms-kpi').innerHTML = K.map(([k, v, s]) => `<div class="jk"><span>${k}</span>${v}<small>${esc(s)}</small></div>`).join('');
    const names = MS_CAT.concat(Object.keys(cats).filter(c => !MS_CAT.includes(c)));
    $('ms-cats').innerHTML = names.map(c => `<span class="mscat ${msCls(c)}${cats[c] ? '' : ' z'}">${esc(c)} · ${cats[c] ? cats[c].n : 0}</span>`).join('');
    const hm = t => new Date(t * 1000).toISOString().slice(11, 19);
    $('ms-list').innerHTML = r.rows.length ? r.rows.map(x => {
      const mv = x.move == null ? '-' : (x.move > 0 ? '+' : '') + x.move.toFixed(1) + '%', good = x.side === 'Short' ? x.move < 0 : x.move > 0;
      return `<div class="msrow2"><span class="o-t">${jRange === 'today' ? '' : esc(x.day.slice(5)) + ' '}${hm(x.t)}</span><b>${esc(x.sym)}</b><span>${esc(x.setup || x.strat)}</span>` +
        `<span class="r">${fmtPx(x.px)}</span><span><span class="mscat ${msCls(x.cat)}" title="${esc(x.reason)}">${esc(x.cat)}</span></span>` +
        `<span class="r">${x.exit_px == null ? '-' : fmtPx(x.exit_px)}</span><span class="o-t">${esc(x.state === 'open' ? 'following...' : x.exit_why)}</span>` +
        `<span class="r ${x.move == null ? '' : good ? 'grn' : 'red'}">${mv}</span><span class="r ${jc(x.pnl)}">${x.pnl == null ? '-' : jm(x.pnl)}</span>` +
        `<span><button class="sbtn" data-os="${esc(x.sym)}">Chart</button></span></div>`; }).join('')
      : '<div class="oempty">No missed signal in this range.</div>';
  }
  function renderHeat(){                               // weekday x hour of the trades in the Trades data (net, after locates)
    const T = ((jData && jData.trades) || []).filter(t => hmStrat === 'all' || t.strat === hmStrat);
    const strats = Array.from(new Set(((jData && jData.trades) || []).map(t => t.strat))).filter(Boolean);
    const SN = {long: 'Premarket long', jr2: 'Jay-read 2', jr: 'Jay-read v1.2', sq: 'Max squeeze', manual: 'Manual', v16: 'v16'};
    $('hm-strat').innerHTML = `<button data-v="all" class="${hmStrat === 'all' ? 'on' : ''}">All strategies</button>` +
      strats.map(s => `<button data-v="${esc(s)}" class="${hmStrat === s ? 'on' : ''}">${esc(SN[s] || s)}</button>`).join('');
    const HR = [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15], DY = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'];
    const V = DY.map(() => HR.map(() => [0, 0]));
    for (const t of T) {
      const wd = new Date(t.d + 'T12:00:00Z').getUTCDay() - 1, hr = parseInt(t.tin, 10);
      const j = HR.indexOf(Math.min(15, Math.max(4, hr)));
      if (wd < 0 || wd > 4 || j < 0 || isNaN(hr)) continue;
      V[wd][j][0] += t.net || 0; V[wd][j][1] += 1;
    }
    const mx = Math.max(1, ...V.flat().map(c => Math.abs(c[0])));
    const cell = (v, n, tot) => !n ? '<div style="color:var(--dim)">·</div>' :
      `<div class="${tot ? 'tot' : ''}" style="${tot ? '' : `background:${v >= 0 ? 'rgba(16,185,129,' : 'rgba(244,63,94,'}${(.06 + Math.min(Math.abs(v) / mx, 1) * .55).toFixed(2)});`}color:${v >= 0 ? '#a7f3d0' : '#fecdd3'}">${jm(v)}<small>${n} tr</small></div>`;
    let h = '<div class="hh"></div>' + HR.map(x => `<div class="hh">${pad(x)}:00</div>`).join('') + '<div class="hh">Total</div>';
    DY.forEach((d, i) => { h += `<div class="rl">${d}</div>` + V[i].map(c => cell(c[0], c[1])).join('');
      h += cell(V[i].reduce((a, c) => a + c[0], 0), V[i].reduce((a, c) => a + c[1], 0), true); });
    h += '<div class="rl">Total</div>' + HR.map((x, j) => cell(V.reduce((a, r) => a + r[j][0], 0), V.reduce((a, r) => a + r[j][1], 0), true)).join('') +
      cell(T.reduce((a, t) => a + (t.net || 0), 0), T.length, true);
    $('hm-grid').innerHTML = h;
  }
  $('jr-view').addEventListener('click', e => { const b = e.target.closest('[data-v]'); if (b) { jView = b.dataset.v; jShowView(); } });
  $('hm-strat').addEventListener('click', e => { const b = e.target.closest('[data-v]'); if (b) { hmStrat = b.dataset.v; renderHeat(); } });
  $('jv-missed').addEventListener('click', e => { const s2 = e.target.closest('[data-os]');
    if (s2) { api('load_symbol', s2.dataset.os).then(res => { if (res && res.recent) setRecent(res.recent); }); showScreen('chart'); } });

  $('scr-journal').addEventListener('click', e => {
    const nv = e.target.closest('[data-jm]');
    if (nv && jData) {
      const [yy, mm] = jData.month.split('-').map(Number), dt = new Date(Date.UTC(yy, mm - 1 + Number(nv.dataset.jm), 1));
      jMonth = dt.getUTCFullYear() + '-' + pad(dt.getUTCMonth() + 1); loadJournal(); return;
    }
    const s2 = e.target.closest('[data-os]');
    if (s2) { api('load_symbol', s2.dataset.os).then(res => { if (res && res.recent) setRecent(res.recent); }); showScreen('chart'); }
  });
  $('jr-csv').addEventListener('click', () => api(jView === 'missed' ? 'missed_csv' : 'journal_csv', jRange).then(res => toast(res && res.ok ? {kind: 'info', text: `Saved ${plural(res.n, 'trade')}: ${res.file}`}
    : {kind: res && res.error === 'cancelled' ? 'info' : 'err', text: res && res.error === 'cancelled' ? 'Not saved' : 'Could not save: ' + ((res && res.error) || '')})));

