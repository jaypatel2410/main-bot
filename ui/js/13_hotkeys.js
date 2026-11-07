  // ---- Hotkeys ----
  const HK_DEF = [
    ['Close and manage', [
      ['cover', 'Shift+C', "Cover the open chart's short", 'at market - like the Cover button (a working entry order is cancelled)', 1],
      ['sell', 'Shift+X', "Sell the open chart's long", 'limit at the bid before 09:30, market after - like the Sell button', 1],
      ['cancel', 'Shift+K', 'Cancel your pending orders on the open chart', "your own orders only - the bot's stops stay", 1],
      ['flatten', 'F9', 'Flatten all', 'press twice within 3 seconds - cancels every bot order, covers every bot short', 1],
      ['stop', 'Ctrl+Click', "Move the short's stop to the clicked price", 'Ctrl + click on the chart (a buy stop above the last price)', 1, 1]]],
    ['Chart', [
      ['alert', 'Alt+Click', 'Price alert at the clicked price', 'Alt + click on the chart - fires once: sound + Discord', 0, 1],
      ['tf', '1 - 6', 'Timeframe', '1, 2, 5, 15, 30 minutes, 1 day', 0, 1],
      ['live', 'Home', 'Back to the latest candle', 'and the normal zoom', 0],
      ['search', '/', 'Symbol search', 'or just start typing a ticker', 0]]],
    ['Watchlist and locates', [
      ['next', 'ArrowDown', 'Next watchlist symbol', '', 0], ['prev', 'ArrowUp', 'Previous watchlist symbol', '', 0],
      ['watch', 'Shift+A', 'Add the open chart to the watchlist', '', 0],
      ['locate', 'Shift+L', 'Locate shares for the open chart', 'opens the Locates tab with the symbol filled in', 0]]],
    ['Screens', [
      ['scan', 'F2', 'Scanner', '', 0], ['journal', 'F3', 'Journal', '', 0], ['botc', 'F4', 'Bot center', '', 0],
      ['keys', 'F6', 'Settings', '', 0], ['favs', 'F7', 'Favorites', '', 0], ['btest', 'F8', 'Dashboard', '', 0], ['chart', 'Escape', 'Back to the chart', '', 0, 1]]]];
  const HK_ORDER = new Set(['cover', 'sell', 'cancel', 'flatten']);
  let hkMap = {}, hkEnabled = false, hkCapture = '';
  function hkDefault(){ const m = {}; for (const [, rows] of HK_DEF) for (const rw of rows) if (!rw[5]) m[rw[0]] = rw[1]; return m; }
  hkMap = hkDefault();
  function comboOf(e){
    const k = e.key;
    if (!k || ['Shift', 'Control', 'Alt', 'Meta'].includes(k)) return '';
    const key = k.length === 1 ? k.toUpperCase() : k;
    const named = /^[A-Z0-9]$/.test(key) || /^F\d{1,2}$/.test(key) || key.startsWith('Arrow') ||
      ['Home', 'End', 'PageUp', 'PageDown', 'Escape', 'Delete', 'Insert', 'Enter', 'Tab'].includes(key);
    return (e.ctrlKey ? 'Ctrl+' : '') + (e.altKey ? 'Alt+' : '') + (e.shiftKey && named ? 'Shift+' : '') + (key === ' ' ? 'Space' : key);
  }
  const KNAME = {ArrowDown: '&darr;', ArrowUp: '&uarr;', ArrowLeft: '&larr;', ArrowRight: '&rarr;', Escape: 'Esc'};
  const hkLabel = c => c ? String(c).split('+').map(p => `<kbd>${KNAME[p] || esc(p)}</kbd>`).join('') : '<span class="sm">none</span>';
  function renderHK(){
    $('hk-on').checked = hkEnabled;
    $('hk-list').innerHTML = HK_DEF.map(([g, rows]) => `<div class="hkg"><div class="t">${g}</div>` + rows.map(([id, def, name, sub, ord, fixed]) => {
      const c = fixed ? def : (hkMap[id] != null ? hkMap[id] : def), off = ord && !hkEnabled;
      return `<div class="hkr${off ? ' off' : ''}"><span class="hkk">${hkCapture === id ? '<kbd class="cap">press a key...</kbd>' : hkLabel(c)}</span>` +
        `<span class="d"><b>${esc(name)}${ord ? ' <small style="color:#f0b232">order</small>' : ''}</b><small>${esc(sub)}${off ? (sub ? ' - ' : '') + 'off: switch on Order hotkeys' : ''}</small></span>` +
        (fixed ? '<span></span>' : `<button class="sbtn" data-hkc="${id}">${hkCapture === id ? 'Cancel' : 'Change'}</button>`) + '</div>';
    }).join('') + '</div>').join('');
  }
  function hkSave(){ api('save_hotkeys', {on: hkEnabled, map: hkMap}); }
  $('hk-on').addEventListener('change', e => {
    hkEnabled = e.target.checked; hkSave(); renderHK();
    toast({kind: hkEnabled ? 'warn' : 'info', text: hkEnabled ? 'Order hotkeys ON - cover, sell, cancel, flatten and Ctrl + click now act at once' : 'Order hotkeys OFF'});
  });
  $('hk-reset').addEventListener('click', () => { hkMap = hkDefault(); hkCapture = ''; hkSave(); renderHK(); });
  $('hk-list').addEventListener('click', e => { const b = e.target.closest('[data-hkc]'); if (!b) return; hkCapture = hkCapture === b.dataset.hkc ? '' : b.dataset.hkc; renderHK(); });
  document.addEventListener('keydown', e => {                       // capture the new key for "Change"
    if (!hkCapture) return;
    const c = comboOf(e); if (!c) return;
    e.preventDefault(); e.stopImmediatePropagation();
    if (c !== 'Escape') { for (const k of Object.keys(hkMap)) if (hkMap[k] === c) hkMap[k] = ''; hkMap[hkCapture] = c; hkSave(); }
    hkCapture = ''; renderHK();
  }, true);
  function hkAction(id){
    const row = ((bot && bot.rows) || []).find(x => x.sym === sym);
    const need = () => { if (!sym) { toast({kind: 'warn', text: 'Open a chart first'}); return false; } return true; };
    if (id === 'cover') {
      if (!need()) return;
      if (!row || !['short', 'manual', 'working'].includes(row.phase)) { toast({kind: 'warn', text: `No bot short on ${sym}`}); return; }
      api('bot_cover', sym); toast({kind: 'warn', text: `${sym}: ${row.phase === 'working' ? 'cancelling the entry order' : 'covering at market'} (hotkey)`});
    } else if (id === 'sell') {
      if (!need()) return;
      if (!((bot && bot.pos) || []).some(p => p.sym === sym && p.kind === 'long')) { toast({kind: 'warn', text: `No open long on ${sym}`}); return; }
      api('long_sell', sym).then(res => toast(res && res.ok === false ? {kind: 'err', text: res.error} : {kind: 'warn', text: `${sym}: selling the long (hotkey)`}));
    } else if (id === 'cancel') {
      if (!need()) return;
      const mine = ((ords && ords.pend) || []).filter(o => o.s === sym && o.r === 'you' && !o.op);
      if (!mine.length) { toast({kind: 'info', text: `No pending order of yours on ${sym}`}); return; }
      mine.forEach(o => api('order_cancel', o.c)); toast({kind: 'warn', text: `${sym}: cancelling ${plural(mine.length, 'order')} of yours (hotkey)`});
    } else if (id === 'flatten') {
      if (Date.now() - f9At < 3000) { f9At = 0; api('bot_flatten'); toast({kind: 'warn', text: 'Flatten all: cancelling every bot order and covering every bot short'}); }
      else { f9At = Date.now(); toast({kind: 'warn', text: 'Press it again within 3 seconds to flatten everything'}); }
    } else if (id === 'live') { if (shown.length) defaultView(); }
    else if (id === 'search') { inp.value = ''; inp.focus(); }
    else if (id === 'next' || id === 'prev') {
      const rs = (bot && bot.rows) || []; if (!rs.length) return;
      let i = rs.findIndex(x => x.sym === sym);
      i = id === 'next' ? (i + 1) % rs.length : (i <= 0 ? rs.length - 1 : i - 1);
      api('load_symbol', rs[i].sym).then(res => { if (res && res.recent) setRecent(res.recent); });
    } else if (id === 'watch') { if (need()) { api('bot_add', sym); toast({kind: 'info', text: `${sym} added to the watchlist`}); } }
    else if (id === 'locate') { if (need()) { showScreen('chart'); showTab('loc'); $('lc-sym').value = sym; setTimeout(() => $('lc-qty').focus(), 80); } }
    else if (id === 'scan') showScreen('scan'); else if (id === 'journal') showScreen('journal');
    else if (id === 'botc') showScreen('bot'); else if (id === 'keys') openSettings('hotkeys'); else if (id === 'favs') showScreen('fav'); else if (id === 'btest') showScreen('bt');
  }
  function hotkey(e){
    const c = comboOf(e); if (!c) return false;
    if (c === 'Escape') { if (screen !== 'chart') { showScreen('chart'); return true; } return false; }
    if (screen === 'chart' && /^[1-6]$/.test(c)) { setTf([1, 2, 5, 15, 30, 'D'][Number(c) - 1]); return true; }
    for (const [id, k] of Object.entries(hkMap)) {
      if (k && k === c) {
        if (HK_ORDER.has(id) && !hkEnabled) return false;
        if (screen !== 'chart' && !['scan', 'journal', 'botc', 'keys', 'favs', 'btest', 'flatten'].includes(id)) return false;
        hkAction(id); return true;
      }
    }
    return false;
  }

  setInterval(() => {
    try { $('f-clock').textContent = new Date().toLocaleTimeString('en-US', {timeZone: 'America/New_York', hour12: false}) + ' ET'; } catch (e) {}
    if (lastUpd) { const s = Math.round((Date.now() - lastUpd) / 1000); $('f-upd').textContent = 'Last tick ' + (s < 2 ? 'now' : s + 's ago'); }
  }, 1000);

  return {
    init(cfg){
      const s = cfg.settings || {};
      ext = s.ext !== false; showSkip = !!s.skipped; sound = s.sound !== false;
      $('t-ext').checked = ext; $('t-skip').checked = showSkip; $('t-sound').checked = sound;
      showSkip = false;                                         // 3.10: no skipped dots on the chart
      if (typeof s.wside === 'number') sideFrac = clamp(s.wside, 0.12, 0.45);
      if (typeof s.scanh === 'number') scanFrac = clamp(s.scanh, 0.12, 0.88);
      if (typeof s.ordh === 'number') ordFrac = clamp(s.ordh, 0.10, 0.70);
      if (typeof s.newsw === 'number') newsFrac = clamp(s.newsw, 0.15, 0.75);
      if (typeof s.tsw === 'number') tsFrac = clamp(s.tsw, 0.12, 0.45);     // 3.15: Time & Sales
      tsShow(!!s.ts);
      if (s.orders === false) $('leftcol').classList.add('oclosed');
      ordAll = !!s.ordall; $('o-all').checked = ordAll;
      const t0 = s.otab || 'pos';                                // 3.10: Positions is the default tab
      oTab = ['loc', 'orders', 'alr'].includes(t0) ? t0 : 'pos';  // 3.14: the premarket long tab is gone
      $('orders').classList.toggle('tab-loc', oTab === 'loc');
      $('orders').classList.toggle('tab-pos', oTab === 'pos'); $('orders').classList.toggle('tab-alr', oTab === 'alr');
      ['ord', 'loc', 'pos', 'alr'].forEach(k => $('tab-' + k).classList.toggle('on', (k === 'ord' ? 'orders' : k) === oTab));
      const hk0 = s.hotkeys || {}; hkEnabled = !!hk0.on; hkMap = Object.assign(hkDefault(), hk0.map || {});
      $('o-tog').innerHTML = $('leftcol').classList.contains('oclosed') ? '&#9650;' : '&#9660;';
      applySizes();
      setTf(s.tf || '1', true);
      info = cfg.info || {};
      setRecent(cfg.recent);
      $('f-info').textContent = `${info.app || ''} - Strategies: ${info.strategy || ''} - IB ${info.ib || ''} - history ${info.history || ''}`;
      $('c-up').title = 'Gap at the 09:30 open vs prior close (before the open: % vs prior close)';
      $('c-off').title = 'How far the price is under the high of day';
      $('c-vol').title = "Today's volume (premarket included)";
      if (cfg.status) this.setStatus(cfg.status);
    },
    setStatus(s){
      const labels = {connected: 'Connected', connecting: 'Connecting', disconnected: 'Disconnected', warning: 'Data warning'};
      const p = $('conn'); p.className = 'pill ' + s.conn; p.querySelector('span').textContent = labels[s.conn] || s.conn;
      $('f-status').textContent = s.text || '';
      fitSoon();
    },
    toast: toast,
    setLoading(p){
      inp.value = p.sym;
      if (p.quiet) return;
      setOverlay('empty', false);
      $('ld-sym').textContent = p.sym;
      $('ld-text').textContent = p.waiting ? 'Waiting for the IB Gateway connection...' : `Loading ${info.history || '5 D'} of 1-minute candles and running the strategy...`;
      setOverlay('loading', true);
    },
    setError(p){
      setOverlay('loading', false);
      toast({kind: 'err', text: p.text});
      if (!bars.length) { setOverlay('empty', true); $('empty').querySelector('.big').textContent = p.text; }
      inp.value = sym;
    },
    setHistory(p){
      const keep = p.keepView && p.sym === sym && bars.length;
      const first = (p.bars && p.bars.length) ? p.bars[0][0] : Infinity;
      const older = keep ? bars.filter(b => b[0] < first) : [];           // 3.10: a reload keeps the older history
      if (!keep) { histDone[p.sym] = false; dailyDone[p.sym] = false; }
      gen = p.gen; sym = p.sym; precision = p.precision; bars = older.concat(p.bars || []);
      if (dailySym !== sym) { daily = null; dailySym = ''; }
      if (tf === 'D') ensureDaily();
      if (!keep) { markers = []; skipMarkers = []; trades = []; oldTrades = []; sig = null; setLevels([]); renderPanel(); $('p-stats').textContent = 'Running the strategy...'; }
      candles.applyOptions({priceFormat: {type: 'price', precision: precision, minMove: 1 / Math.pow(10, precision)}});
      vwap.applyOptions({priceFormat: {type: 'price', precision: precision, minMove: 1 / Math.pow(10, precision)}});
      chart.applyOptions({watermark: {text: sym}});
      $('q-sym').textContent = sym; $('q-name').textContent = ''; fitSoon();       // 3.11: the ticker only
      if (!keep) { $('q-bid').textContent = $('q-ask').textContent = '-'; $('q-ba').classList.remove('halt'); }   // 3.14: never the last symbol's quote
      $('p-sym').textContent = sym; inp.value = sym;
      if (!keep || !(sym in cnAll)) cnLoad(sym);                // 3.14: this ticker's chart notes
      render(keep);
      if (!keep) defaultView();
      alSeen = ''; renderBot();
      setOverlay('loading', false); setOverlay('empty', false);
      lastUpd = Date.now();
    },
    tsReset(p){ tsResetTo(p || {}); },
    tsPush(rows){ tsAdd(rows); },
    upsertBars(p){
      if (p.gen !== gen) return;
      let need = false;
      const touched = new Set();
      for (const b of p.bars) {
        let i = bars.length - 1;
        while (i >= 0 && bars[i][0] > b[0]) i--;
        if (tf !== 1) {                                      // higher timeframe: update the 1-min store, rebuild the bucket below
          if (i >= 0 && bars[i][0] === b[0]) bars[i] = b; else bars.splice(i + 1, 0, b);
          if (ext || b[6] || tf === 'D') touched.add(bucketOf(b[0]));
          continue;
        }
        if (i >= 0 && bars[i][0] === b[0]) { bars[i] = b; if (i !== bars.length - 1) { need = true; continue; } }
        else if (i === bars.length - 1) bars.push(b);
        else { bars.splice(i + 1, 0, b); need = true; continue; }
        if (!ext && !b[6]) continue;
        if (noTrade(b)) continue;                                // halted / no trade yet: nothing to draw
        const ls = shown.length ? shown[shown.length - 1] : null;
        if (ls && (ls[0] > b[0] || dayOf(ls[0]) !== dayOf(b[0]))) { need = true; continue; }   // new day: full redraw
        if (ls && ls[0] === b[0]) shown[shown.length - 1] = b; else shown.push(b);
        try {
          candles.update(Cd(b)); volume.update(Vd(b));
          vwap.update(Wd(b));
        } catch (e) { need = true; }
      }
      for (const t0 of [...touched].sort((a, b) => a - b)) {
        const row = tf === 'D' ? todayDaily() : bucketRow(t0);
        if (!row) continue;
        const ls = shown.length ? shown[shown.length - 1] : null;
        if (ls && (row[0] < ls[0] || (tf !== 'D' && dayOf(ls[0]) !== dayOf(row[0])))) { need = true; continue; }
        if (ls && ls[0] === row[0]) shown[shown.length - 1] = row; else shown.push(row);
        try {
          candles.update(Cd(row)); volume.update(Vd(row));
          if (tf !== 'D') vwap.update(Wd(row));
        } catch (e) { need = true; }
      }
      if (need) scheduleRender();
      else if (p.bars.length && markers.some(m => m.time >= bucketOf(p.bars[0][0]))) applyMarkers();   // signal arrived with its candle
      lastUpd = Date.now();
      volLabelsSoon();
      if (hover === null) legend(null);
    },
    setQuote(q){
      if (q.gen !== gen) return;
      $('q-last').textContent = fmtP(q.last); lastPx = q.last;
      const ch = $('q-chg');
      if (q.prior) { ch.textContent = `${q.chg >= 0 ? '+' : ''}${fmtP(q.chg)} (${q.up >= 0 ? '+' : ''}${q.up.toFixed(2)}%)`; ch.className = q.chg >= 0 ? 'up' : 'dn'; }
      else { ch.textContent = ''; }
      $('q-bid').textContent = q.bid == null ? '-' : fmtP(q.bid);          // 3.14: bid x ask, every quote change (halts too)
      $('q-ask').textContent = q.ask == null ? '-' : fmtP(q.ask);
      $('q-ba').classList.toggle('halt', !!q.halted);
      const cu = $('c-up'), co = $('c-off');
      const gv = q.gap != null ? q.gap : q.up;
      cu.querySelector('span').textContent = gv == null ? '-' : `${gv >= 0 ? '+' : ''}${gv.toFixed(gv >= 100 ? 0 : 1)}%`;
      cu.className = 'chip';
      co.querySelector('span').textContent = q.off == null ? '-' : `${q.off.toFixed(1)}%`;
      co.className = 'chip';
      $('c-hod').querySelector('span').textContent = fmtP(q.hod);
      $('c-vwap').querySelector('span').textContent = fmtP(q.vwap);
      $('c-vol').querySelector('span').textContent = fmtV(q.vol);
      $('c-halt').classList.toggle('on', !!q.halted);
      fitSoon();
      for (const t of trades) {
        if (!t.open) continue;
        const el = document.querySelector(`[data-live="${t.t}"]`);
        if (el) el.textContent = fmtR(liveR(t, q.last));
      }
    },
    setSignals(p){
      if (p.gen !== gen) return;
      sig = p; markers = p.markers || []; skipMarkers = p.skipMarkers || []; trades = p.trades || []; scratch = p.scratch || 0.2;
      applyMarkers(); setLevels(p.levels); renderPanel();
    },
    setBot(p){ bot = p; renderBot(); },
    setOrders(p){ ords = p; renderOrders(); },
    setLong(p){ lng = p; if (screen === 'bot') renderBC(); },   // 3.14: the long bot's own panel is gone (Bot center / Positions show it)
    olderSignals(p){                                       // 3.11: the strategies on scrolled-back days (display only)
      if (p.sym !== sym || p.gen !== gen) return;
      const ds = new Set(p.days || []);
      oldTrades = oldTrades.filter(t => !ds.has(t.day)).concat(p.trades || []).sort((a, b) => b.t - a.t);
      overlay.refresh(); renderPanel();
    },
    setScan(p){ scan = p; (p.rows || []).forEach(r => { if (r.spark) sparkC[r.sym] = r.spark; }); renderMiniScan(); if (screen === 'scan') renderScan(); },
    news(n){ newsAdd(n); },
    newsStatus(s){ nwStatus = s || {}; renderNews(); },
    newsReset(s){ newsReset(s); },
    shutdownPrompt(p){ shutdownPrompt(p); },
    floatInfo(p){ if (p && p.sym === sym) { flInfo = p; floatChip(); } },
    setLocate(p){ loc = p; locRecv = Date.now() / 1000; renderLoc(); },
    askClose(p){ askClose(p); },
    orderMsg(m){ toast(m); },
    alert(a){
      const b = $('banner'); b.className = a.kind; b.dataset.t = a.t;
      b.innerHTML = `<b>${esc(a.title)}</b><span>${esc(a.text)}</span>`;
      clearTimeout(bannerTimer); bannerTimer = setTimeout(() => b.className = 'hidden', a.kind === 'short' ? 20000 : 10000);
      setTimeout(() => { const c = document.querySelector(`.card[data-t="${a.t}"]`); if (c) c.classList.add('flash'); }, 300);
    },
  };
}
if (window.LightweightCharts) window.__bootChart();
})();
