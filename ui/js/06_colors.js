  // ---- 3.12.1: colors (Settings > Colors) - the app, the chart candles, VWAP, pre / after-hours shading ----
  const COLD = {bg: '#06090e', bg2: '#0a0e15', card: '#121926', line: '#161c28', text: '#cbd5e1', muted: '#8a96aa',   // the new look
    blue: '#6366f1', red: '#f43f5e', green: '#10b981', chartBg: '#000000', chartText: '#9a9ea6', up: UPC, down: DNC,
    wickUp: UPC, wickDown: DNC, vwap: VWC, ext: '#ffffff', grid: '#ffffff', cross: '#6b7078', markShort: '#e8242f', markCover: '#18c93a'};
  const COLROWS = [['APP', [['bg', 'Background'], ['bg2', 'Top bar and side panels'], ['card', 'Cards and buttons'], ['line', 'Lines and borders'],
      ['text', 'Text'], ['muted', 'Secondary text'], ['blue', 'Accent (selected, links)'], ['red', 'Red (losses, short)'], ['green', 'Green (wins)']]],
    ['CHART', [['chartBg', 'Chart background'], ['chartText', 'Axis text'], ['up', 'Up candle'], ['down', 'Down candle'], ['wickUp', 'Up wick'],
      ['wickDown', 'Down wick'], ['vwap', 'VWAP line'], ['ext', 'Pre / after-hours shading'], ['grid', 'Grid lines'], ['cross', 'Crosshair'],
      ['markShort', 'Short / sell triangle'], ['markCover', 'Cover / buy triangle']]]];
  const APPK = ['bg', 'bg2', 'card', 'line', 'text', 'muted', 'blue', 'red', 'green'];
  let COL = Object.assign({}, COLD), extA = 8.5, gridOn = GRID;
  const hexOk = v => /^#[0-9a-fA-F]{6}$/.test(v);
  function colApply(){
    const r = document.documentElement.style;
    [['bg', '--bg'], ['bg2', '--bg2'], ['card', '--card'], ['line', '--line'], ['text', '--text'], ['muted', '--muted'], ['blue', '--blue'],
      ['red', '--red'], ['green', '--green'], ['up', '--up'], ['down', '--down'], ['vwap', '--vwap']].forEach(([k, v]) => r.setProperty(v, COL[k]));
    r.setProperty('--panel', COL.bg2); r.setProperty('--line2', rgba(COL.muted, .16));
    UPC = COL.up; DNC = COL.down; VWC = COL.vwap; VOL_UP = rgba(COL.up, .30); VOL_DN = rgba(COL.down, .50);
    SHADE = rgba(COL.ext, extA / 100); TRI_DN = COL.markShort; TRI_UP = COL.markCover;
    chart.applyOptions({layout: {background: {type: 'solid', color: COL.chartBg}, textColor: COL.chartText},
      grid: {vertLines: {color: rgba(COL.grid, .06), visible: gridOn}, horzLines: {color: rgba(COL.grid, .06), visible: gridOn}},
      crosshair: {vertLine: {color: COL.cross}, horzLine: {color: COL.cross}}});
    candles.applyOptions({upColor: COL.up, downColor: COL.down, borderUpColor: COL.up, borderDownColor: COL.down, wickUpColor: COL.wickUp, wickDownColor: COL.wickDown});
    vwap.applyOptions({color: COL.vwap});
    try { if (btChart) { btChart.applyOptions({layout: {background: {color: COL.chartBg}, textColor: COL.chartText}});
      [btSer, btDSer].forEach(sr => sr && sr.applyOptions({upColor: COL.up, downColor: COL.down, wickUpColor: COL.wickUp, wickDownColor: COL.wickDown}));
      btVw && btVw.applyOptions({color: COL.vwap}); } } catch (e) {}
    try { render(true); } catch (e) {}
  }
  function colRender(){
    $('col-grid').innerHTML = COLROWS.map(([h, rows]) => `<div class="ch">${h}</div>` + rows.map(([k, l]) =>
      `<label class="colrow"><span>${l}</span><input type="color" data-ck="${k}" value="${COL[k]}"><input class="hex" data-ckx="${k}" value="${COL[k]}" spellcheck="false"></label>`).join('')).join('') +
      `<div class="ch">OPTIONS</div><label class="colrow"><span>Pre / after-hours shading strength (%)</span><input class="hex" id="col-exta" value="${extA}"></label>` +
      `<label class="colrow"><span>Show grid lines</span><input type="checkbox" id="col-grid-on" ${gridOn ? 'checked' : ''}></label>`;
  }
  $('col-grid').addEventListener('input', e => {
    const t = e.target, k = t.dataset.ck || t.dataset.ckx;
    if (k) { const v = t.value.trim(); if (!hexOk(v)) return; COL[k] = v.toLowerCase();
      const o = t.dataset.ck ? document.querySelector(`[data-ckx="${k}"]`) : document.querySelector(`[data-ck="${k}"]`); if (o) o.value = COL[k]; colApply(); return; }
    if (t.id === 'col-exta') { const a = parseFloat(t.value); if (a >= 0 && a <= 60) { extA = a; colApply(); } }
    if (t.id === 'col-grid-on') { gridOn = t.checked; colApply(); }
  });
  $('col-grid').addEventListener('change', e => { if (e.target.id === 'col-grid-on') { gridOn = e.target.checked; colApply(); } });
  $('col-save').addEventListener('click', () => api('colors_set', {c: COL, extA, gridOn}).then(r => toast(r && r.ok ? {kind: 'info', text: 'Colors saved'} : {kind: 'err', text: 'Could not save the colors'})));
  $('col-reset').addEventListener('click', () => { COL = Object.assign({}, COLD); extA = 8.5; gridOn = GRID; colApply(); colRender(); api('colors_set', null); toast({kind: 'info', text: 'Colors back to default'}); });
  whenApi(() => api('colors_get').then(r => { const s = r && r.colors; if (!s || !s.c) return;
    const oldLook = [['#0e0f11', '#2962ff'], ['#0c0f13', '#5b6cf2']].some(([b, u]) => (s.c.bg || '').toLowerCase() === b && (s.c.blue || '').toLowerCase() === u);   // saved = an earlier default look
    Object.keys(COLD).forEach(k => { if (oldLook && APPK.includes(k)) return; if (hexOk(s.c[k] || '')) COL[k] = s.c[k]; }); if (s.extA != null) extA = Number(s.extA); if (s.gridOn != null) gridOn = !!s.gridOn; colApply(); }));

