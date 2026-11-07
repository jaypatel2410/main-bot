function createApp(){
  const LWC = window.LightweightCharts;
  const css = getComputedStyle(document.documentElement);
  const GRID = __GRID__;
  let UPC = css.getPropertyValue('--up').trim(), DNC = css.getPropertyValue('--down').trim(), VWC = css.getPropertyValue('--vwap').trim();
  const rgba = (hex, a) => { const h = hex.replace('#', ''); const n = parseInt(h.length === 3 ? h.split('').map(x => x + x).join('') : h, 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`; };
  let VOL_UP = rgba(UPC, .30), VOL_DN = rgba(DNC, .50), SHADE = 'rgba(255,255,255,0.085)'; const CLEAR = 'rgba(0,0,0,0)';
  const DAYS = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'], MON = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

  let gen = 0, sym = '', precision = 2, bars = [], shown = [], ext = true, showSkip = false, sound = true;
  let botFills = [], histBusy = false, histDone = {}, dailyDone = {};
  let oldTrades = [], lastPx = null, alerts = [], alertLines = [], screen = 'chart', scan = null, scanSel = '';   // 3.11
  let scanCfg = {up: 30, px: 0.5}, jData = null, jRange = 'month', jMonth = '', f9At = 0, feedTab = 'all', jClosedN = -1;
  let markers = [], skipMarkers = [], trades = [], priceLines = [], hover = null, lastUpd = 0, renderTimer = null;
  let bannerTimer = null, toastTimer = null, scratch = 0.2, info = {}, sig = null;
  let bot = null;
  let tf = 1, daily = null, dailySym = '', dailyLoading = '';
  const tfLabel = () => tf === 'D' ? '1D' : tf + 'm';
  const bucketOf = t => tf === 'D' ? Math.floor(t / 86400) * 86400 : tf === 1 ? t : Math.floor(t / (tf * 60)) * (tf * 60);

  const fmtP = p => (p == null || isNaN(p)) ? '-' : Number(p).toFixed(precision);
  const fmtV = v => v == null ? '-' : v >= 1e9 ? (v / 1e9).toFixed(2) + 'B' : v >= 1e6 ? (v / 1e6).toFixed(2) + 'M' : v >= 1e3 ? (v / 1e3).toFixed(1) + 'K' : String(Math.round(v));
  const fmtR = r => r == null ? '' : (r >= 0 ? '+' : '') + Number(r).toFixed(2) + 'R';
  const pad = n => String(n).padStart(2, '0');
  const fmtT = t => { const d = new Date(t * 1000); return pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes()); };
  const fmtDay = t => { const d = new Date(t * 1000); return DAYS[d.getUTCDay()] + ' ' + MON[d.getUTCMonth()] + ' ' + d.getUTCDate(); };
  const fmtFull = t => fmtDay(t) + "  " + fmtT(t);
  const fmtDate = t => { const d = new Date(t * 1000); return fmtDay(t) + " '" + String(d.getUTCFullYear()).slice(2); };
  const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  const dayOf = t => Math.floor(t / 86400);
  const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;

  const chart = LWC.createChart($('chart'), {
    autoSize: true,
    layout: {background: {type: 'solid', color: '#000000'}, textColor: '#9a9ea6', fontSize: 12,
      fontFamily: '-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif'},
    grid: {vertLines: {color: 'rgba(255,255,255,0.06)', visible: GRID}, horzLines: {color: 'rgba(255,255,255,0.06)', visible: GRID}},
    crosshair: {mode: LWC.CrosshairMode.Normal,
      vertLine: {color: '#6b7078', width: 1, style: LWC.LineStyle.Dashed, labelBackgroundColor: '#303338'},
      horzLine: {color: '#6b7078', width: 1, style: LWC.LineStyle.Dashed, labelBackgroundColor: '#303338'}},
    rightPriceScale: {borderVisible: false, scaleMargins: {top: 0.10, bottom: 0.13}},
    timeScale: {borderVisible: false, timeVisible: true, secondsVisible: false, rightOffset: 12, barSpacing: 6, minBarSpacing: 0.2},
    localization: {locale: 'en-US', priceFormatter: p => p < 0 ? '' : fmtP(p), timeFormatter: t => tf === 'D' ? fmtDate(t) : fmtFull(t)},
    watermark: {visible: false, text: '', fontSize: 72, color: 'rgba(120,123,134,0.07)', horzAlign: 'center', vertAlign: 'center'},
  });
  const shade = chart.addHistogramSeries({priceScaleId: 'shade', priceFormat: {type: 'volume'}, lastValueVisible: false, priceLineVisible: false});
  chart.priceScale('shade').applyOptions({scaleMargins: {top: 0, bottom: 0}});
  const volume = chart.addHistogramSeries({priceScaleId: 'vol', priceFormat: {type: 'volume'}, lastValueVisible: false, priceLineVisible: false});
  chart.priceScale('vol').applyOptions({scaleMargins: {top: 0.90, bottom: 0}});
  const candles = chart.addCandlestickSeries({upColor: UPC, downColor: DNC, borderUpColor: UPC, borderDownColor: DNC,
    wickUpColor: UPC, wickDownColor: DNC, priceLineVisible: true, lastValueVisible: true,
    priceLineStyle: LWC.LineStyle.Dotted, priceLineColor: '#8a8f98'});
  const vwap = chart.addLineSeries({color: VWC, lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
    crosshairMarkerVisible: false});

  // 3.10: one drawing layer on the candles (Webull look): the high of the visible candles as a small label with a
  // bracket at its candle (no HOD line), and the trades as triangles whose tip sits at the exact fill price - red down
  // = short / sell, green up = cover / buy. No text on the chart: the details are in Discord.
  let TRI_DN = '#e8242f', TRI_UP = '#18c93a';
  function lastIdx(t){                           // the last shown candle at/before chart time t (halted minutes are not drawn)
    let lo = 0, hi = shown.length - 1, r = -1;
    while (lo <= hi) { const m = (lo + hi) >> 1; if (shown[m][0] <= t) { r = m; lo = m + 1; } else hi = m - 1; }
    return r;
  }
  function tradeMarks(){
    if (tf === 'D' || !shown.length) return [];
    const out = [], real = botFills.filter(f => f.sym === sym), realDays = new Set(real.map(f => dayOf(f.t)));
    for (const t of trades.concat(oldTrades)) {  // the strategy's trades (backtest view: loaded week + 3.11 older days)
      if (realDays.has(dayOf(t.t))) continue;    // ... the bot's real fills replace them on days it traded
      if (t.entry != null) out.push({t: t.t, px: t.entry, dn: true});
      if (t.xT != null && t.xPx != null) out.push({t: t.xT, px: t.xPx, dn: false});
    }
    for (const f of real) out.push({t: f.t, px: f.px, dn: f.dir === 'down'});
    return out;
  }
  const overlay = {
    _p: null, marks: [],
    attached(p){ this._p = p; }, detached(){ this._p = null; },
    updateAllViews(){},
    refresh(){ this.marks = tradeMarks(); if (this._p) this._p.requestUpdate(); },
    paneViews(){ const self = this; return [{zOrder: () => 'bottom', renderer: () => ({draw: tg => self.drawExt(tg)})},
                                           {zOrder: () => 'top', renderer: () => ({draw: tg => self.draw(tg)})}]; },
    drawExt(target){                             // pre-market / after-hours: one solid grey band (Webull look)
      if (!ext || tf === 'D' || !shown.length) return;
      const ts = chart.timeScale(), lr = ts.getVisibleLogicalRange();
      if (!lr) return;
      const a = Math.max(0, Math.floor(lr.from) - 1), b = Math.min(shown.length - 1, Math.ceil(lr.to) + 1);
      const half = (ts.options().barSpacing || 6) / 2;
      target.useMediaCoordinateSpace(({context: ctx, mediaSize}) => {
        ctx.fillStyle = SHADE;
        let i = a;
        while (i <= b) {
          if (shown[i][6]) { i++; continue; }
          let j = i;
          while (j + 1 <= b && !shown[j + 1][6]) j++;
          const x0 = ts.logicalToCoordinate(i), x1 = ts.logicalToCoordinate(j);
          if (x0 != null && x1 != null) ctx.fillRect(Math.floor(x0 - half), 0, Math.ceil(x1 - x0 + 2 * half), mediaSize.height);
          i = j + 1;
        }
      });
    },
    draw(target){
      if (!shown.length || !this._p) return;
      const ts = chart.timeScale(), lr = ts.getVisibleLogicalRange();
      if (!lr) return;
      target.useMediaCoordinateSpace(({context: ctx, mediaSize}) => {
        // high of the visible candles: "15.590" + dot + bracket down to the wick (left of it; right when near the edge)
        const a = Math.max(0, Math.ceil(lr.from)), b = Math.min(shown.length - 1, Math.floor(lr.to));
        let hi = -1;
        for (let i = a; i <= b; i++) if (hi < 0 || shown[i][2] > shown[hi][2]) hi = i;
        if (hi >= 0) {
          const x = ts.logicalToCoordinate(hi), y = candles.priceToCoordinate(shown[hi][2]);
          if (x != null && y != null) {
            const txt = Number(shown[hi][2]).toFixed(Math.max(precision, 3));
            ctx.font = '11px -apple-system,"Segoe UI",Roboto,Arial,sans-serif';
            const w = ctx.measureText(txt).width, yy = Math.max(9, y - 12), left = x - 26 - w > 2;
            ctx.strokeStyle = ctx.fillStyle = '#8c8f96'; ctx.lineWidth = 1;
            ctx.beginPath(); ctx.moveTo(left ? x - 16 : x + 16, yy + 0.5); ctx.lineTo(x + 0.5, yy + 0.5); ctx.lineTo(x + 0.5, y - 2); ctx.stroke();
            ctx.beginPath(); ctx.arc(left ? x - 16 : x + 16, yy + 0.5, 1.8, 0, 2 * Math.PI); ctx.fill();
            ctx.textBaseline = 'middle'; ctx.textAlign = left ? 'right' : 'left';
            ctx.fillText(txt, left ? x - 21 : x + 21, yy + 0.5);
          }
        }
        // trades: triangle tip exactly at the fill price, on the fill's candle
        for (const m of this.marks) {
          const i = lastIdx(bucketOf(m.t));
          if (i < 0 || i < a - 2 || i > b + 2) continue;
          const x = ts.logicalToCoordinate(i), y = candles.priceToCoordinate(m.px);
          if (x == null || y == null) continue;
          const s = 6.5, h = 10.5, d = m.dn ? -1 : 1;
          ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x - s, y + d * h); ctx.lineTo(x + s, y + d * h); ctx.closePath();
          ctx.fillStyle = m.dn ? TRI_DN : TRI_UP; ctx.fill();
          ctx.lineWidth = 1.4; ctx.strokeStyle = '#ffffff'; ctx.lineJoin = 'round'; ctx.stroke();
        }
      });
    },
  };
  candles.attachPrimitive(overlay);

  const Cd = b => ({time: b[0], open: b[1], high: b[2], low: b[3], close: b[4]});
  const Vd = b => ({time: b[0], value: b[5] || 0, color: b[4] >= b[1] ? VOL_UP : VOL_DN});
  const Sd = b => ({time: b[0], value: 1, color: b[6] ? CLEAR : SHADE});
  // VWAP resets every day: the last point of each day gets a transparent segment so days are not joined
  const Wd = b => b[7] == null ? {time: b[0]} : {time: b[0], value: b[7]};
  function vwSeries(arr){
    const out = new Array(arr.length);
    for (let i = 0; i < arr.length; i++) {
      const b = arr[i], nx = arr[i + 1];
      out[i] = (b[7] != null && nx && dayOf(nx[0]) !== dayOf(b[0])) ? {time: b[0], value: b[7], color: CLEAR} : Wd(b);
    }
    return out;
  }

  // higher timeframes are built from the 1-minute candles (clock-aligned buckets, ET)
  function aggregate(src, sec){
    const out = []; let cur = null;
    for (const b of src) {
      const t = Math.floor(b[0] / sec) * sec;
      if (!cur || cur[0] !== t) { if (cur) out.push(cur); cur = [t, b[1], b[2], b[3], b[4], b[5] || 0, b[6], b[7]]; }
      else { if (b[2] > cur[2]) cur[2] = b[2]; if (b[3] < cur[3]) cur[3] = b[3]; cur[4] = b[4]; cur[5] += b[5] || 0; if (b[7] != null) cur[7] = b[7]; }
    }
    if (cur) out.push(cur);
    return out;
  }
  function bucketRow(t0){                     // rebuild one higher-timeframe candle
    const sec = tf * 60, part = [];
    for (let i = bars.length - 1; i >= 0 && bars[i][0] >= t0; i--) {
      const b = bars[i];
      if (b[0] < t0 + sec && (ext || b[6]) && !noTrade(b)) part.push(b);
    }
    if (!part.length) return null;
    part.reverse();
    return aggregate(part, sec)[0];
  }
  function todayDaily(){                      // today's daily candle from the live 1-minute candles (regular hours)
    if (!bars.length) return null;
    const d = dayOf(bars[bars.length - 1][0]);
    const r = [];
    for (let i = bars.length - 1; i >= 0 && dayOf(bars[i][0]) === d; i--) if (bars[i][6]) r.push(bars[i]);
    if (!r.length) return null;
    r.reverse();
    const row = aggregate(r, 86400)[0]; row[7] = null; row[6] = 1;
    return row;
  }
  function dailyRows(){
    const rows = daily && dailySym === sym ? daily.slice() : [];
    const td = todayDaily();
    if (td) {
      if (rows.length && rows[rows.length - 1][0] === td[0]) rows[rows.length - 1] = td;
      else if (!rows.length || rows[rows.length - 1][0] < td[0]) rows.push(td);
    }
    return rows;
  }
  // 3.10: a minute with no trade (halted: IB sends a flat zero-volume candle) is not drawn - no flat "halt lines"
  const noTrade = b => !(b[5] > 0) && b[2] === b[3];
  const drawable = arr => arr.filter(b => !noTrade(b));
  function render(keep){
    const ts = chart.timeScale();
    let pos = null, range = null;
    if (keep && shown.length) { pos = ts.scrollPosition(); range = ts.getVisibleRange(); }
    const src = drawable(ext ? bars : bars.filter(b => b[6]));
    shown = tf === 'D' ? dailyRows() : tf === 1 ? src.slice() : aggregate(src, tf * 60);
    candles.setData(shown.map(Cd));
    volume.setData(shown.map(Vd));
    shade.setData([]);                                // 3.10: the drawing layer paints the extended-hours band
    vwap.setData(tf === 'D' ? [] : vwSeries(shown));
    applyMarkers();
    if (keep && pos !== null) {
      if (pos > -3) ts.scrollToPosition(pos, false);
      else if (range) { try { ts.setVisibleRange(range); } catch (e) {} }
    }
    legend(hover);  volLabelsSoon();
  }
  // 3.12.2: volume labels on the volume pane - the live volume of the newest candle above its bar, and on the
  // biggest-volume candle of the day: its shares and dollars (shares x typical price). Display only.
  const vlHost = $('chart'); if (getComputedStyle(vlHost).position === 'static') vlHost.style.position = 'relative';
  const mkVL = c => { const d = document.createElement('div'); d.style.cssText = 'position:absolute;z-index:3;pointer-events:none;' +
    'transform:translate(-50%,-100%);white-space:nowrap;font:600 10px -apple-system,"Segoe UI",Roboto,Arial,sans-serif;' +
    'padding:1px 4px;border-radius:3px;display:none;' + c; vlHost.appendChild(d); return d; };
  const vlNow = mkVL('color:#e6e8ee;background:rgba(40,44,52,.85)'), vlMax = mkVL('color:#ffd600;background:rgba(0,0,0,.75);border:1px solid rgba(255,214,0,.5)');
  const fmtD = v => '$' + (v >= 1e9 ? (v / 1e9).toFixed(2) + 'B' : v >= 1e6 ? (v / 1e6).toFixed(2) + 'M' : v >= 1e3 ? (v / 1e3).toFixed(0) + 'K' : Math.round(v));
  function placeVL(el, b, txt, lift){
    const x = chart.timeScale().timeToCoordinate(b[0]), y = volume.priceToCoordinate(b[5] || 0);
    if (x == null || y == null || x < 0 || x > vlHost.clientWidth - 40) { el.style.display = 'none'; return; }
    el.textContent = txt; el.style.left = x + 'px'; el.style.top = (y - 3 - (lift || 0)) + 'px'; el.style.display = 'block';
  }
  function volLabels(){
    try {
      if (!shown.length) { vlNow.style.display = vlMax.style.display = 'none'; return; }
      const last = shown[shown.length - 1];
      let mi = -1, mv = -1;
      if (tf === 'D') {
        const r = chart.timeScale().getVisibleLogicalRange();
        const a = r ? Math.max(0, Math.floor(r.from)) : 0, z = r ? Math.min(shown.length - 1, Math.ceil(r.to)) : shown.length - 1;
        for (let i = a; i <= z; i++) if ((shown[i][5] || 0) > mv) { mv = shown[i][5] || 0; mi = i; }
      } else {
        const d = dayOf(last[0]);
        for (let i = shown.length - 1; i >= 0 && dayOf(shown[i][0]) === d; i--) if ((shown[i][5] || 0) > mv) { mv = shown[i][5] || 0; mi = i; }
      }
      placeVL(vlNow, last, fmtV(last[5] || 0), 0);
      if (mi >= 0 && mv > 0) {
        const b = shown[mi], px = (b[2] + b[3] + b[4]) / 3;
        placeVL(vlMax, b, 'MAX ' + fmtV(mv) + ' · ' + fmtD(mv * px), mi === shown.length - 1 ? 16 : 0);
      } else vlMax.style.display = 'none';
    } catch (e) {}
  }
  let vlRaf = 0; const volLabelsSoon = () => { if (!vlRaf) vlRaf = requestAnimationFrame(() => { vlRaf = 0; volLabels(); }); };
  chart.timeScale().subscribeVisibleLogicalRangeChange(volLabelsSoon);
  if (chart.timeScale().subscribeSizeChange) chart.timeScale().subscribeSizeChange(volLabelsSoon);
  function scheduleRender(){ clearTimeout(renderTimer); renderTimer = setTimeout(() => render(true), 200); }

  function defaultView(){
    if (!shown.length) return;
    if (tf === 'D') { chart.timeScale().setVisibleLogicalRange({from: shown.length - 130, to: shown.length - 1 + 5}); return; }
    const n = shown.length, last = dayOf(shown[n - 1][0]);
    let i = n - 1; while (i > 0 && dayOf(shown[i - 1][0]) === last) i--;
    const from = Math.max(0, Math.min(i - 4, n - 240));
    chart.timeScale().setVisibleLogicalRange({from: from, to: n - 1 + 12});
  }
  function goTo(t){
    if (!shown.length || t == null) return;
    t = bucketOf(t);
    let lo = 0, hi = shown.length - 1;
    while (lo < hi) { const m = (lo + hi) >> 1; if (shown[m][0] < t) lo = m + 1; else hi = m; }
    chart.timeScale().setVisibleLogicalRange({from: lo - 90, to: lo + 110});
  }
  function findBar(t){
    let lo = 0, hi = shown.length - 1;
    while (lo <= hi) { const m = (lo + hi) >> 1; const v = shown[m][0]; if (v === t) return m; if (v < t) lo = m + 1; else hi = m - 1; }
    return -1;
  }
  function legend(t){
    const el = $('legend');
    if (!shown.length) { el.innerHTML = ''; return; }
    let i = t != null ? findBar(t) : shown.length - 1;
    if (i < 0) i = shown.length - 1;
    const b = shown[i], p = i > 0 ? shown[i - 1] : null;
    const cls = b[4] >= b[1] ? 'up' : 'dn';
    const ch = p ? b[4] - p[4] : 0, chp = p && p[4] ? ch / p[4] * 100 : 0;
    el.innerHTML = `<span class="s">${esc(sym)}</span><span class="k">${tfLabel()}</span>` +
      `<span class="k">O</span><span class="${cls}">${fmtP(b[1])}</span><span class="k">H</span><span class="${cls}">${fmtP(b[2])}</span>` +
      `<span class="k">L</span><span class="${cls}">${fmtP(b[3])}</span><span class="k">C</span><span class="${cls}">${fmtP(b[4])}</span>` +
      `<span class="${ch >= 0 ? 'up' : 'dn'}">${ch >= 0 ? '+' : ''}${fmtP(ch)} (${chp >= 0 ? '+' : ''}${chp.toFixed(2)}%)</span>` +
      `<span class="k">Vol</span><span class="${cls}">${fmtV(b[5])}</span>` +
      (b[7] != null ? `<span class="vw">VWAP ${fmtP(b[7])}</span>` : '') +
      `<span class="k">${tf === 'D' ? fmtDate(b[0]) : fmtFull(b[0]) + ' ET'}</span>`;
  }
  chart.subscribeCrosshairMove(param => {
    hover = (param && param.time !== undefined && param.point) ? param.time : null;
    legend(hover);
  });
  chart.timeScale().subscribeVisibleLogicalRangeChange(() => {
    const pos = chart.timeScale().scrollPosition();
    $('golive').style.display = (shown.length && pos < -15) ? 'block' : 'none';
    olderSoon();
  });
  // 3.10: scroll left / zoom out past the oldest candle -> older candles for THIS chart only (the bot and the
  // watchlist never load them). 1-minute: 5 days at a time; 1D: 2 years at a time. IB pacing is kept by the app.
  let olderTimer = null;
  function olderSoon(){ clearTimeout(olderTimer); olderTimer = setTimeout(loadOlder, 250); }
  function loadOlder(){
    if (histBusy || !sym || !shown.length) return;
    const lr = chart.timeScale().getVisibleLogicalRange();
    if (!lr || lr.from > 40) return;
    const kind = tf === 'D' ? 'D' : '1m';
    if (kind === 'D' ? dailyDone[sym] : histDone[sym]) return;
    if (kind === 'D' && !(daily && dailySym === sym && daily.length)) return;
    if (kind === '1m' && bars.length >= (info.histMax || 150000)) {
      histDone[sym] = true; toast({kind: 'info', text: `${sym}: the chart keeps at most ${(info.histMax || 150000).toLocaleString('en-US')} one-minute candles - switch to 1D for older history`}); return;
    }
    const oldest = kind === 'D' ? daily[0][0] : bars[0][0], want = sym;
    histBusy = true; $('hist-note').classList.remove('hidden');
    api('more_history', want, kind, oldest).then(r => {
      histBusy = false; $('hist-note').classList.add('hidden');
      if (!r || want !== sym) return;
      if (!r.ok) { toast({kind: 'err', text: `Older candles for ${want}: ${r.error}`}); histBusy = true; setTimeout(() => { histBusy = false; }, 10000); return; }
      const rows = (r.rows || []).filter(x => x[0] < oldest);
      if (!rows.length) { if (kind === 'D') dailyDone[want] = true; else histDone[want] = true;
        toast({kind: 'info', text: `${want}: no older ${kind === 'D' ? 'daily' : '1-minute'} candles from IB`}); return; }
      if (kind === 'D') daily = rows.concat(daily); else bars = rows.concat(bars);
      render(true);
      olderSoon();                                     // still at the edge (zoomed far out): keep loading
    });
  }
  $('golive').onclick = () => chart.timeScale().scrollToRealTime();

  function applyMarkers(){                       // 3.10: no text markers, no skipped dots - the drawing layer
    candles.setMarkers([]);
    overlay.refresh();
  }
  let levelsNow = [];
  function setLevels(lv){
    levelsNow = lv || [];
    for (const pl of priceLines) { try { candles.removePriceLine(pl); } catch (e) {} }
    priceLines = [];
    if (tf === 'D') return;                   // intraday levels (HOD, entry, stop, targets) only on intraday charts
    for (const L of levelsNow) {
      if (L.price == null) continue;
      const style = L.style === 'dot' ? LWC.LineStyle.Dotted : L.style === 'solid' ? LWC.LineStyle.Solid : LWC.LineStyle.Dashed;
      priceLines.push(candles.createPriceLine({price: L.price, color: L.color, lineWidth: 1, lineStyle: style,
        axisLabelVisible: true, title: L.title}));
    }
  }

  function liveR(t, last){
    const risk = t.stop - t.entry;
    if (!(risk > 0) || last == null) return t.R;
    const fee = t.entry * (t.fee || 0) / 100;          // R is shown net of the locate fee
    if (t.pT != null) return (t.pfrac * (t.entry - t.pPx) + (1 - t.pfrac) * (t.entry - last) - fee) / risk;
    return (t.entry - last - fee) / risk;
  }
  function card(t){
    const st = t.open ? 'open' : (t.R >= scratch ? 'win' : t.R <= -scratch ? 'loss' : 'flat');
    const status = t.open ? `OPEN <span data-live="${t.t}">${fmtR(t.R)}</span>` : `${esc(t.reason)} ${fmtR(t.R)}`;
    const sqc = t.setup === 'Max squeeze';
    const jrc = String(t.setup || '').startsWith('Jay-read') || sqc;
    const t1 = t.setup === 'VACUUM' ? `Peak <b>${fmtP(t.top)}</b> <i>vacuum</i>` : sqc ? `Top <b>${fmtP(t.top)}</b> <i>squeeze +${t.dip != null ? t.dip.toFixed(0) + '%' : '-'}</i>` : jrc ? `High <b>${fmtP(t.top)}</b> <i>cracked -${t.dip != null ? t.dip.toFixed(0) + '%' : '-'}</i>` : `Top <b>${fmtP(t.top)}</b> <i>dip ${t.dip != null ? t.dip.toFixed(0) + '%' : '-'}</i>`;
    const netTxt = (t.xPx != null && t.fee > 0 && t.net != null)
      ? ` <i title="After the ${t.fee}% locate fee">net ${t.net >= 0 ? '+' : ''}${t.net.toFixed(1)}%</i>` : '';
    const exit = t.xPx != null ? `<span>Exit <b>${fmtP(t.xPx)}</b> <i>${fmtT(t.xT)}</i>${netTxt}</span>` : '';
    const stopTxt = (t.open && t.stopNow !== t.stop) ? `Stop <b class="red">${fmtP(t.stopNow)}</b> <i>${Math.abs(t.stopNow - t.entry) <= 1e-6 * t.entry ? 'breakeven' : 'trail'}</i>` : `Stop <b class="red">${fmtP(t.stop)}</b> <i>${t.risk != null ? t.risk.toFixed(1) + '%' : ''}</i>`;
    return `<div class="card ${st}" data-t="${t.t}"><div class="c-top"><span class="c-n">S${t.n}</span>` +
      `<span class="c-setup">${esc(t.setup)}</span>${t.grade ? `<span class="c-gr g${esc(t.grade)}" title="Setup grade (extension, speed, VWAP stretch, climax volume, overhead supply)">${esc(t.grade)}</span>` : ''}<span class="c-st ${st}">${status}</span></div>` +
      `<div class="c-row"><span><b>${fmtT(t.t)}</b> ET</span><span>Entry <b>${fmtP(t.entry)}</b></span><span>${stopTxt}</span></div>` +
      `<div class="c-row"><span>${t1}</span><span>${t.t1k === 'VWAP' ? 'VWAP' : t.t1k === 'CRACK' ? 'Crack low' : t.t1k === 'LEVEL' ? 'Swing high' : 'Dip low'} <b class="grn">${fmtP(t.t1)}</b> <i title="${jrc ? 'Signal close vs VWAP' : 'Zone vs VWAP at the signal'}">${t.zv != null ? (jrc ? (t.zv >= 0 ? '+' : '') + t.zv.toFixed(0) + '% vs VWAP' : t.zv.toFixed(0) + '% > VWAP') : ''}</i></span>${exit}</div>` +
      `<div class="c-note">${esc(t.note)}</div></div>`;
  }
  function renderPanel(){
    const list = $('sig-list');
    if (!sig) { list.innerHTML = ''; return; }
    if (!trades.length) {
      list.innerHTML = '<div class="empty-sig">No short signal in the loaded week.</div>';
    } else {
      let html = '', cur = null;
      for (const t of trades) {
        if (t.day !== cur) {
          cur = t.day;
          const dayT = trades.filter(x => x.day === cur);
          const closed = dayT.filter(x => !x.open), opn = dayT.length - closed.length;
          const r = closed.reduce((a, x) => a + (x.R || 0), 0);
          const tail = (closed.length ? ' ' + fmtR(r) : '') + (opn ? ` - ${opn} open` : '');
          html += `<div class="dayh"><span>${cur === sig.day && sig.live ? 'Today - ' : ''}${fmtDay(t.t)}</span><span>${plural(dayT.length, 'trade')}${tail}</span></div>`;
        }
        html += card(t);
      }
      list.innerHTML = html;
    }
    if (oldTrades.length) list.insertAdjacentHTML('beforeend', olderHtml());     // 3.11: scrolled-back days
    const w = sig.week, d = sig.today;
    const closedToday = d.trades - (d.open || 0);
    $('p-stats').innerHTML = `${sig.live ? 'Today' : 'Latest day'}: <b>${plural(d.trades, 'trade')}</b>${closedToday ? ' - <b>' + fmtR(d.R) + '</b>' : ''}${d.open ? ' - <b style="color:var(--amber)">' + d.open + ' open</b>' : ''}` +
      (d.jr && info.jr ? `<span class="daytype ${d.gapOk ? '' : 'dump'}" title="High of day vs prior close - the Jay-read short needs ${info.jr.up}%+ and $${info.jr.dollar}M traded">${d.up == null ? 'Up: -' : (d.gapOk ? 'Up +' : 'Up only +') + d.up.toFixed(0) + '%' + (d.dollar != null ? ', $' + (d.dollar / 1e6).toFixed(0) + 'M' : '') + ''}</span><br>` : '') +
      `Loaded week: <b>${plural(w.trades, 'trade')}</b> - ${w.wins}W / ${w.losses}L - <b>${fmtR(w.R) || '0.00R'}</b>`;
    const sk = sig.skips || [];
    $('skip-sum').textContent = `Skipped signals ${sig.live ? 'today' : 'on the latest day'} (${sk.length})`;
    $('d-skip').textContent = sk.length ? ' ' + sk.length : ''; $('m-skip').textContent = sk.length || '';
    $('d-sig').textContent = trades.length ? ' ' + trades.length : ''; $('m-sig').textContent = trades.length || '';
    $('skip-list').innerHTML = sk.slice().reverse().map(s => `<div class="skip"><span>${fmtT(s.t)}</span><span>${esc(s.setup)}</span><span>${esc(s.reason)}</span></div>`).join('');
  }
  $('sig-list').addEventListener('click', e => { const c = e.target.closest('.card'); if (c) goTo(Number(c.dataset.t)); });

  const fmtPx = p => p == null ? '-' : Number(p).toFixed(p < 1 ? 4 : 2);
  const money = (v, sign) => v == null ? '-' : (sign && v > 0 ? '+' : '') + (v < 0 ? '-' : '') + '$' + Math.abs(v).toLocaleString('en-US', {maximumFractionDigits: 0});
