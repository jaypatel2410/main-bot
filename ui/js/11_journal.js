  // ---- Journal (today / week / month / all, from the bot's journals) ----
  const jm = v => v == null ? '-' : (v > 0 ? '+' : v < 0 ? '-' : '') + '$' + Math.abs(v).toLocaleString('en-US', {maximumFractionDigits: 0});
  const jc = v => v == null || v === 0 ? '' : v > 0 ? 'grn' : 'red';
  function loadJournal(){
    api('journal', jRange, jMonth).then(d => {
      if (d && d.ok) { jData = d; renderJournal(); } else if (d) toast({kind: 'err', text: 'Journal: ' + d.error});
    });
  }
  function renderJournal(){
    const d = jData; if (!d) return;
    document.querySelectorAll('#jr-rng button').forEach(b => b.classList.toggle('on', b.dataset.v === jRange));
    $('j-meta').textContent = `${d.from === d.to ? d.to : (d.range === 'all' ? 'all days' : d.from + ' to ' + d.to)} - ${plural(d.days, 'day')} with trades`;
    $('j-src').textContent = d.source === 'tz' ? 'From TradeZero - real fills (strategy labels from the bot)' : "From the bot's trade journals (TradeZero returned no history)";
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
      const v = c.pnl, bg = v == null || v === 0 ? '' : v > 0 ? `background:rgba(34,171,148,${Math.min(.6, .14 + v / 8000).toFixed(2)})`
        : `background:rgba(242,54,69,${Math.min(.55, .16 - v / 4000).toFixed(2)})`;
      cal += `<div class="c${v == null ? ' e' : ''}${c.today ? ' td' : ''}" style="${bg}" title="${plural(c.n, 'trade')}"><span>${c.d}</span><b>${v == null ? '&ndash;' : jm(v)}</b></div>`;
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
    $('j-trades').innerHTML = `<div class="jtg h"><span>Date</span><span>Symbol</span><span>Side</span><span>Setup</span><span class="r">Entry</span><span class="r">Exit</span><span class="r">Shares</span><span class="r">Net</span><span>Result</span></div>` +
      (d.trades.length ? d.trades.map(t => `<div class="jtg"><span class="o-t">${esc(t.d.slice(5))} ${esc(t.tin)}</span><span class="o-s" data-os="${esc(t.sym)}">${esc(t.sym)}</span>` +
        `<span class="p-side ${t.side === 'Long' ? 'l' : 's'}">${esc(t.side)}</span><span class="o-ty">${esc(t.setup)}</span><span class="r">${fmtPx(t.entry)}</span>` +
        `<span class="r">${fmtPx(t.exit)}</span><span class="r">${Number(t.qty).toLocaleString('en-US')}</span><span class="r j${jc(t.net)}">${jm(t.net)}</span>` +
        `<span class="o-ty">${esc(t.res)}</span></div>`).join('') : '<div class="oempty">No closed trade in this range.</div>');
  }
  $('jr-rng').addEventListener('click', e => { const b = e.target.closest('[data-v]'); if (b) { jRange = b.dataset.v; jMonth = ''; loadJournal(); } });
  $('scr-journal').addEventListener('click', e => {
    const nv = e.target.closest('[data-jm]');
    if (nv && jData) {
      const [yy, mm] = jData.month.split('-').map(Number), dt = new Date(Date.UTC(yy, mm - 1 + Number(nv.dataset.jm), 1));
      jMonth = dt.getUTCFullYear() + '-' + pad(dt.getUTCMonth() + 1); loadJournal(); return;
    }
    const s2 = e.target.closest('[data-os]');
    if (s2) { api('load_symbol', s2.dataset.os).then(res => { if (res && res.recent) setRecent(res.recent); }); showScreen('chart'); }
  });
  $('jr-csv').addEventListener('click', () => api('journal_csv', jRange).then(res => toast(res && res.ok ? {kind: 'info', text: `Saved ${plural(res.n, 'trade')}: ${res.file}`}
    : {kind: res && res.error === 'cancelled' ? 'info' : 'err', text: res && res.error === 'cancelled' ? 'Not saved' : 'Could not save: ' + ((res && res.error) || '')})));

