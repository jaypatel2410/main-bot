  // ---- Bot center ----
  const BC_STRATS = [['jr2', 'Jay-read 2 short'], ['jr', 'Jay-read short v1.2'], ['long', 'Premarket long']];   // 3.13.0   // 3.12.2: no max squeeze live
  const stratOf = s => /squeeze/i.test(s || '') ? 'sq' : /JR2|jay-read 2/i.test(s || '') ? 'jr2' : /jay-read/i.test(s || '') ? 'jr' : /long/i.test(s || '') ? 'long' : 'other';
  function renderBC(){
    if (screen !== 'bot' || !bot) return;
    const md = bot.modes || {}, mon = bot.modeOn || {}, h = bot.health || {}, cl = bot.closed || [], ps = bot.pos || [], bt = info.btref || {};
    const chip = $('trade-chip');
    $('bc-chip').className = chip.className; $('bc-chip').querySelector('span').textContent = chip.querySelector('span').textContent;
    $('bc-meta').textContent = `${h.watch || 0} of ${h.max || 15} on the watchlist - ${plural(bot.trades || 0, 'short trade')} today (max ${bot.maxTrades})`;
    const pb = $('bc-pause');
    if (!(armed2.pause && Date.now() - armed2.pause < 5000)) { pb.textContent = bot.auto ? 'Pause new entries' : 'Resume entries'; pb.className = 'sbtn ' + (bot.auto ? 'danger' : 'pri'); }
    $('bc-cards').innerHTML = BC_STRATS.map(([k, nm]) => {
      const m = md[k] || 'trading', on = mon[k] !== false;
      const c2 = cl.filter(x => k === 'long' ? x.side === 'Long' : x.side === 'Short' && stratOf(x.setup) === k);
      const o2 = ps.filter(x => k === 'long' ? x.kind === 'long' : x.kind === 'short' && stratOf(x.setup) === k);
      const pnl = c2.reduce((a, x) => a + (x.pnl || 0), 0) + o2.reduce((a, x) => a + (x.unreal || 0), 0);
      const cnt = k === 'long' ? (lng ? (lng.act || []).length + (lng.n || 0) : 0) : ((bot.sig || {})[k] || 0);
      let now;
      if (!on) now = `<div>Not running</div>`;
      else if (k === 'long') now = lng ? `<div>${esc({off: 'Off', waiting: 'Waiting for its window', running: 'Scanning and trading', closing: 'Selling the open longs', done: 'Done for today'}[lng.st] || lng.st)} - ${esc(lng.win)} ET</div>` +
        `<div>${lng.note ? esc(lng.note) : `${lng.watch} watched - ${(lng.act || []).length} open`}</div>` : '<div>Starting...</div>';
      else if (k === 'sq') now = `<div>Reads the same watchlist as the Jay-read short - one short per stock at a time.</div><div>Up ${'30'}%+, a ${'50'}% squeeze over a swing high, red candle at the top - 09:30-15:00.</div>`;
      else { const rs = (bot.rows || []).slice(0, 3); now = rs.length ? rs.map(x => `<div title="${esc(x.sym + ' - ' + x.status)}"><b style="color:#fff">${esc(x.sym)}</b> ${esc(x.status)}</div>`).join('') : '<div>The watchlist is empty.</div>'; }
      return `<div class="bcc"><div class="n">${nm}<small>backtest ${bt[k] ? bt[k].n + ' trades, ' + bt[k].win + '% win' : ''}</small></div>` +
        `<div class="seg${on ? '' : ' na'}">` + [['trading', 'Trading'], ['alert', 'Alert only'], ['off', 'Off']].map(([v, t]) =>
          `<button class="${v}${m === v ? ' on' : ''}" data-mk="${k}" data-mv="${v}">${t}</button>`).join('') + '</div>' +
        `<div class="bcs"><div><span>${k === 'long' ? 'Trades today' : 'Signals today'}</span><b>${cnt}</b></div><div><span>Closed / open</span><b>${c2.length} / ${o2.length}</b></div>` +
        `<div><span>Day P&amp;L</span><b class="j${jc(pnl)}">${c2.length || o2.length ? jm(pnl) : '$0'}</b></div></div><div class="bcnow">${now}</div></div>`;
    }).join('');
    const lg = (bot.log || []).slice().reverse().filter(l => feedTab === 'all' || (feedTab === 'trade' ? l.k === 'trade' : (l.k === 'warn' || l.k === 'err')));
    $('bc-feed').innerHTML = lg.length ? lg.map(l => `<div class="bfe k-${esc(l.k)}"><span>${esc(l.t)}</span><span>${esc(l.x)}</span></div>`).join('') : '<div class="oempty">Nothing yet.</div>';
    document.querySelectorAll('#bc-ft button').forEach(b => b.classList.toggle('on', b.dataset.v === feedTab));
    const tz = bot.tz || {}, dc = bot.dc || {}, ca = h.cache;
    const dot = c => c === 'connected' ? 'ok' : c === 'connecting' || c === 'warning' ? 'warn' : 'bad';
    const HL = [[dot(h.ib), 'IB Gateway', h.ibText || '', h.ibMs != null ? h.ibMs + ' ms' : '-'],
      [dot(tz.conn), 'TradeZero', tz.text || '', h.tzMs != null ? h.tzMs + ' ms' : '-'],
      [dc.conn === 'connected' ? 'ok' : dc.conn === 'error' ? 'bad' : 'warn', 'Discord', dc.text || '', ''],
      [ca ? 'ok' : 'warn', 'Candle cache', ca ? `${ca.days} days on disk (${ca.mb} MB)${ca.vaultOn ? ' + your IB data vault' : ''}` : 'off (BAR_CACHE = False)',
        ca && ca.hit != null ? `${ca.hit}% from disk` : ''],
      ['ok', 'Last chart open', h.loadSrc ? 'candles: ' + h.loadSrc : '-', h.loadMs != null ? (h.loadMs / 1000).toFixed(1) + ' s' : '-'],
      [bot.sizeBase ? 'ok' : 'warn', 'Position size', bot.size || '', bot.sizeBase ? '$' + Math.round(bot.sizeBase).toLocaleString('en-US') + ' base' : 'equity now']];
    let hh = '<div class="jt">Connections and speed</div>' + HL.map(([c, k, d2, v]) => `<div class="hl"><i class="${c}"></i><span><b>${k}</b><small title="${esc(d2)}">${esc(d2)}</small></span><em>${esc(v)}</em></div>`).join('');
    const lat = h.lat || [];
    hh += `<div class="jt" style="margin-top:6px">Short signal to order at TradeZero <span class="sm">${lat.length ? 'median ' + h.latMed + ' ms - ' + plural(lat.length, 'order') : 'no bot order yet'}</span></div>`;
    if (lat.length) {
      const mx = Math.max(250, ...lat);
      hh += '<svg viewBox="0 0 400 80" style="width:100%;height:80px">' + lat.map((v, i) => `<rect x="${i * 8}" y="${(78 - v / mx * 74).toFixed(1)}" width="6" height="${Math.max(1, v / mx * 74).toFixed(1)}" rx="1" fill="${v > 1000 ? '#f0b232' : '#2962ff'}"><title>${v} ms</title></rect>`).join('') + '</svg>';
    }
    const hm = h.haltMs || [];                     // 3.12: halt reopen -> TradeZero's answer
    hh += `<div class="jt" style="margin-top:6px">Halt reopen to TradeZero's answer <span class="sm">${hm.length ? 'last ' + hm[hm.length - 1] + ' ms - ' + plural(hm.length, 'reopen') : 'no halt on a held short yet'}</span></div>`;
    $('bc-health').innerHTML = hh;
  }
  $('bc-cards').addEventListener('click', e => {
    const b = e.target.closest('[data-mk]'); if (!b) return;
    api('set_mode', b.dataset.mk, b.dataset.mv).then(res => { if (res && !res.ok) toast({kind: 'err', text: res.error}); });
  });
  $('bc-ft').addEventListener('click', e => { const b = e.target.closest('[data-v]'); if (b) { feedTab = b.dataset.v; renderBC(); } });
  $('bc-pause').addEventListener('click', () => {
    if (!bot) return;
    if (bot.auto) twoStep($('bc-pause'), 'pause', 'Pause new entries', 'Pause new entries: click again within 5 seconds. Working entry orders are cancelled; open positions keep their stops.',
      () => api('bot_auto', false));
    else { $('t-auto').checked = true; $('t-auto').dispatchEvent(new Event('change')); }
  });

