  // ---------------- 3.10: trading mode (menu), positions tab ----------------
  const MODE_ROWS = [['long', 'Premarket long'], ['jr2', 'Jay-read 2 short'], ['jr', 'Jay-read short v1.2']];   // 3.13.0: + Jay-read 2   // 3.12.2: max squeeze short is backtest-only
  let modesSeen = '';
  function renderModes(){
    const md = (bot && bot.modes) || {}, mon = (bot && bot.modeOn) || {};
    const key = JSON.stringify([md, mon]);
    if (key === modesSeen) return;
    modesSeen = key;
    $('modes').innerHTML = MODE_ROWS.map(([k, nm]) => {
      const m = md[k] || 'trading', on = mon[k] !== false;
      const lab = !on ? 'NOT RUNNING' : {trading: 'TRADING', alert: 'ALERT ONLY', off: 'OFF'}[m];
      return `<div class="mode"><div class="n">${nm}<b class="${on ? m : 'off'}">${lab}</b></div><div class="seg${on ? '' : ' na'}">` +
        [['trading', 'Trading'], ['alert', 'Alert only'], ['off', 'Off']].map(([v, t]) =>
          `<button class="${v}${m === v ? ' on' : ''}" data-mk="${k}" data-mv="${v}">${t}</button>`).join('') + '</div></div>';
    }).join('');
  }
  $('modes').addEventListener('click', e => {
    const b = e.target.closest('[data-mk]'); if (!b) return;
    api('set_mode', b.dataset.mk, b.dataset.mv).then(r => { if (r && !r.ok) toast({kind: 'err', text: r.error}); });
  });
  function renderPos(){
    const ps = (bot && bot.pos) || [], cl = (bot && bot.closed) || [];
    $('pos-n').textContent = ps.length ? ' ' + ps.length : '';
    if (oTab !== 'pos') return;
    $('p-no').textContent = ps.length; $('p-nc').textContent = cl.length;
    const tot = cl.reduce((s, r) => s + (r.pnl || 0), 0);
    $('p-tot').innerHTML = cl.length ? `${cl.filter(r => (r.pnl || 0) > 0).length}/${cl.length} won - <b class="${lPnl(tot)}">${lMoney(tot)}</b>` : '';
    $('p-open').innerHTML = ps.length ? ps.map(r => {
      const k = 'px' + r.sym, armed = armed2[k] && Date.now() - armed2[k] < 5000, lab = r.kind === 'long' ? 'Sell' : 'Cover';
      const pct = r.unreal != null && r.avg ? ` <small>(${(r.unreal / (r.avg * r.qty) * 100).toFixed(1)}%)</small>` : '';
      return `<div class="orow pgrid"><span class="o-s" data-os="${esc(r.sym)}">${esc(r.sym)}</span>` +
        `<span class="p-side ${r.kind === 'long' ? 'l' : 's'}">${esc(r.side)}</span><span class="r">${Number(r.qty).toLocaleString('en-US')}</span>` +
        `<span class="r">${fmtPx(r.avg)}</span><span class="r">${fmtPx(r.last)}</span>` +
        `<span class="r l-pnl ${lPnl(r.unreal)}">${r.unreal == null ? '-' : lMoney(r.unreal)}${pct}</span>` +
        `<span class="r">${r.stop == null ? '<span style="color:#f7525f">none</span>' : fmtPx(r.stop)}</span><span class="r o-t">${esc(r.t)}</span>` +
        `<span class="o-ty">${esc(r.setup)}</span>` +
        `<button class="p-x${armed ? ' arm' : ''}" data-px="${esc(r.sym)}" data-kind="${esc(r.kind)}">${armed ? 'Sure?' : lab}</button></div>`;
    }).join('') : '<div class="oempty">No open position.</div>';
    $('p-cls').innerHTML = cl.length ? cl.slice().reverse().map(r => `<div class="orow pgrid2"><span class="o-s" data-os="${esc(r.sym)}">${esc(r.sym)}</span>` +
        `<span class="p-side ${r.side === 'Long' ? 'l' : 's'}">${esc(r.side)}</span><span class="r">${Number(r.qty).toLocaleString('en-US')}</span>` +
        `<span class="r">${fmtPx(r.avg)}</span><span class="r">${fmtPx(r.exit)}</span>` +
        `<span class="r l-pnl ${lPnl(r.pnl)}">${lMoney(r.pnl)}</span><span class="r o-t">${esc(r.t)}</span>` +
        `<span class="o-ty">${esc(r.setup)}${r.res ? ' <small>' + esc(r.res) + '</small>' : ''}</span></div>`).join('')
      : '<div class="oempty">No closed trade today.</div>';
  }
  $('pos-body').addEventListener('click', e => {
    const s2 = e.target.closest('[data-os]');
    if (s2) { api('load_symbol', s2.dataset.os).then(res => { if (res && res.recent) setRecent(res.recent); }); return; }
    const x = e.target.closest('[data-px]'); if (!x) return;
    const sy = x.dataset.px, lg = x.dataset.kind === 'long', lab = lg ? 'Sell' : 'Cover';
    twoStep(x, 'px' + sy, lab, `${lab} ${sy} at market now? Click again within 5 seconds.`,
      () => api(lg ? 'long_sell' : 'bot_cover', sy).then(r => { if (r && r.ok === false) toast({kind: 'err', text: r.error}); }));
    if (x.classList.contains('arm')) x.textContent = 'Sure?';
  });
  function renderBot(){
    if (!bot) return;
    const tz = bot.tz || {}, a = bot.acct || {};
    $('tz-pill').className = 'pill2 ' + (tz.conn || 'off');
    $('tz-text').textContent = tz.text || '';
    $('t-auto').checked = !!bot.auto;
    $('auto-wrap').classList.toggle('on', !!bot.auto);
    // 3.10: the account in the top bar (no account number anywhere)
    const pn = (el, v) => { el.textContent = v == null ? '-' : money(v, true); el.className = v == null || v === 0 ? '' : v > 0 ? 'grn' : 'red'; };
    $('a-eq').textContent = a.id ? money(a.equity) : '-';
    $('a-bp').textContent = a.id ? money(a.bp) : '-';
    pn($('a-pnl'), a.id ? a.dayPnl : null); pn($('a-un'), a.id ? (a.unreal || 0) : null);
    // trading state chip + what is not trading
    const md = bot.modes || {}, mon = bot.modeOn || {}, NM = {long: 'Long', jr: 'Jay-read', sq: 'Squeeze'};
    const nt = Object.keys(NM).filter(k => mon[k] && md[k] && md[k] !== 'trading');
    const chip = $('trade-chip');
    let ct, ck;
    if (!a.id) { ct = 'TradeZero not connected'; ck = ''; }
    else if (bot.liveBlocked) { ct = 'Live - orders locked'; ck = 'warn'; }
    else if (!bot.auto) { ct = 'Auto-trade OFF'; ck = 'warn'; }
    else if (nt.length) { ct = nt.map(k => NM[k] + ' ' + (md[k] === 'alert' ? 'alert only' : 'off')).join(' · '); ck = 'warn'; }
    else { ct = 'Trading · ' + (a.type ? a.type.charAt(0).toUpperCase() + a.type.slice(1).toLowerCase() : 'TradeZero'); ck = 'ok'; }
    chip.className = 'tchip ' + ck; chip.querySelector('span').textContent = ct;
    let wn = '';
    if (bot.liveBlocked) wn += '<div>LIVE account: orders are locked (ALLOW_LIVE_TRADING = False) - signals only</div>';
    if (bot.reason) wn += `<div>No new shorts: ${esc(bot.reason)}</div>`;
    $('bot-warn').innerHTML = wn;
    renderModes(); renderPos();
    botFills = bot.fills || []; overlay.refresh();
    const dc = bot.dc || {};
    $('dc-pill').className = 'pill2 ' + (dc.conn || 'off');
    $('dc-text').textContent = dc.text || 'Discord: not set';
    const rows = bot.rows || [];
    $('wl-list').innerHTML = rows.length ? rows.map(r => {
      const gap = r.gap == null ? '-' : (r.gap >= 0 ? '+' : '') + r.gap.toFixed(0) + '%';
      const armedCov = armed2['cov' + r.sym] && Date.now() - armed2['cov' + r.sym] < 5000;
      const covBtn = (label) => `<button class="sbtn danger${armedCov ? ' arm' : ''}" data-cover="${esc(r.sym)}" data-label="${label}">${armedCov ? 'Click again' : label}</button>`;
      let act = '';
      if (r.phase === 'short') act = `<div class="w-act"><span>Stop <b>${fmtPx(r.stop)}</b> - you can also change it at TradeZero</span>` +
        `<button class="sbtn" data-stop="${esc(r.sym)}" data-px="${r.stop == null ? '' : r.stop}" data-last="${r.last == null ? '' : r.last}">Stop</button>${covBtn('Cover')}</div>`;
      else if (r.phase === 'working') act = `<div class="w-act"><span>Entry order working</span>${covBtn('Cancel')}</div>`;
      else if (r.phase === 'manual') act = `<div class="w-act"><span>You manage this short - NO stop</span>` +
        `<button class="sbtn" data-stop="${esc(r.sym)}" data-px="" data-last="${r.last == null ? '' : r.last}" title="Place a stop - the bot manages the short again">Stop</button>${covBtn('Cover')}</div>`;
      return `<div class="wrow wgrid k-${esc(r.kind)}${r.sym === sym ? ' sel' : ''}" data-sym="${esc(r.sym)}" title="${esc(r.sym + ' - ' + r.status + ' - click to open the chart')}">` +
        `<span class="w-sym"><b>${esc(r.sym)}</b>${r.halted ? `<i title="${r.ht ? 'halted ' + r.ht + ' at ' + fmtPx(r.hpx) : 'halted'}">HALT${r.hdir === 'UP' ? ' \u25B2' : r.hdir === 'DOWN' ? ' \u25BC' : ''}</i>` : ''}</span><span class="w-last">${fmtPx(r.last)}</span>` +
        `<span class="w-gap${r.gapOk ? ' ok' : ''}">${gap}</span><span class="w-st">${esc(r.status)}</span>` +
        `<button class="w-x" data-x="${esc(r.sym)}" title="Remove from the watchlist">&times;</button>${act}</div>`;
    }).join('') : '<div class="empty-sig">Add the tickers the bot should watch (type a ticker above and press Enter).</div>';
    $('botlog').innerHTML = (bot.log || []).slice().reverse().map(l => `<div class="lg k-${esc(l.k)}"><span>${esc(l.t)}</span>${esc(l.x)}</div>`).join('');
    alerts = bot.alerts || []; renderAlerts();                          // 3.11
    if (screen === 'bot') renderBC();
    const nc = (bot.closed || []).length;
    if (screen === 'journal' && jClosedN >= 0 && nc !== jClosedN) loadJournal();
    jClosedN = nc;
  }
  // ---------------- orders panel (below the chart) ----------------
  let ords = null, oEdit = null, oSeen = {p: '', f: ''};
  const O_CANCEL_MSG = {
    entry: s => `Cancel the bot's short order on ${s}? The bot skips this setup and looks for the next one.`,
    stop: s => `Cancel the bot's stop on ${s}? You take the short over: NO stop, the bot stops managing it.`,
    ystop: s => `Cancel your stop on ${s}? The short has NO stop then and you manage it.`,
    cover: s => `Cancel the bot's cover on ${s}? The short stays open with NO stop.`,
    long: s => `Cancel the premarket long bot's order on ${s}? (A cancelled buy = no entry; an unsold long is offered again by the long bot.)`};
  const oQty = r => r.f > 0 && r.f < r.q ? `${r.f.toLocaleString('en-US')}<small>/${r.q.toLocaleString('en-US')}</small>` : r.q.toLocaleString('en-US');
  const oBy = r => `<span class="o-by ${r.r === 'you' ? 'you' : r.r === 'long' ? 'long' : 'bot'}" title="${esc(r.by + (r.tif ? ' - ' + r.tif : ''))}">${esc(r.by)}</span>`;
  function oPend(r){
    let px;
    if (oEdit && oEdit.c === r.c) px = `<input id="o-in" value="${esc(oEdit.v)}" inputmode="decimal" spellcheck="false" autocomplete="off">`;
    else if (r.ek && !r.op) px = `<button class="ed" data-ed="${esc(r.c)}" data-px="${r.px == null ? '' : r.px}" title="Change the ${r.ek} price">${fmtPx(r.px)}</button>`;
    else px = r.px == null ? 'MKT' : fmtPx(r.px);
    if (r.px2 != null) px += ` <small>lmt ${fmtPx(r.px2)}</small>`;
    const armed = armed2['oc' + r.c] && Date.now() - armed2['oc' + r.c] < 5000;
    const act = r.op ? `<span class="o-busy">${r.op === 'cancel' ? 'cancelling...' : 'changing...'}</span>`
      : `<button class="o-x${armed ? ' arm' : ''}" data-oc="${esc(r.c)}">${armed ? 'Sure?' : 'Cancel'}</button>`;
    const st = r.st && r.st !== 'New' && r.st !== 'PartiallyFilled' ? ` - ${r.st}` : '';
    return `<div class="orow ogp r-${esc(r.r)}" title="${esc(r.s + ' ' + r.sd + ' ' + r.ty + ' - ' + r.by + st + (r.tx ? ' - ' + r.tx : ''))}">` +
      `<span class="o-t">${esc(r.t)}</span><span class="o-s" data-os="${esc(r.s)}">${esc(r.s)}</span>` +
      `<span class="o-sd ${esc(r.sc)}">${esc(r.sd)}</span><span class="o-ty">${esc(r.ty)}</span>` +
      `<span class="r o-q">${oQty(r)}</span><span class="o-px">${px}</span>${oBy(r)}${act}</div>`;
  }
  function oFill(r){
    const done = r.f <= 0;
    const st = done ? `<span class="o-st r${r.st === 'Rejected' ? ' rej' : ''}" title="${esc(r.tx)}">${esc(r.st)}</span>` : `<span class="r">${fmtPx(r.avg)}</span>`;
    return `<div class="orow ogf${done ? ' done' : ''}" title="${esc(r.s + ' ' + r.sd + ' ' + r.ty + ' - ' + r.by + ' - ' + r.st + (r.tx ? ' - ' + r.tx : ''))}">` +
      `<span class="o-t">${esc(r.tu || r.t)}</span><span class="o-s" data-os="${esc(r.s)}">${esc(r.s)}</span>` +
      `<span class="o-sd ${esc(r.sc)}">${esc(r.sd)}</span><span class="r o-q">${done ? r.q.toLocaleString('en-US') : oQty(r)}</span>` +
      `${st}<span class="o-ty">${esc(r.ty)}</span>${oBy(r)}</div>`;
  }
  function renderOrders(force){
    if (!ords) return;
    const pend = ords.pend || [], fill = ords.fill || [], rows2 = ordAll ? fill.concat(ords.done || []) : fill;
    $('o-np').textContent = pend.length; $('o-nf').textContent = fill.length;
    $('o-bp').innerHTML = `Pending <b>${pend.length}</b>`; $('o-bp').classList.toggle('hot', pend.length > 0);
    $('o-bf').innerHTML = `Filled <b>${fill.length}</b>`;
    const m = $('o-meta');
    m.className = 'm o-ord' + (ords.err || !ords.conn ? ' err' : '');
    m.textContent = !ords.conn ? 'TradeZero not connected' + (pend.length + fill.length ? ' - list may be old' : '')
      : ords.err ? ords.err : `TradeZero ${ords.acc || ''} - updated ${ords.at || '-'} ET`;
    if (oEdit && document.activeElement && document.activeElement.id === 'o-in') return;     // typing a price: keep the row
    rows2.sort((a, b) => (b.tu || '').localeCompare(a.tu || ''));
    const hp = pend.length ? pend.map(oPend).join('') : '<div class="oempty">No pending orders.</div>';
    const hf = rows2.length ? rows2.map(oFill).join('') : `<div class="oempty">No ${ordAll ? '' : 'filled '}orders today.</div>`;
    if (force || hp !== oSeen.p) { oSeen.p = hp; $('o-pend').innerHTML = hp; }
    if (force || hf !== oSeen.f) { oSeen.f = hf; $('o-fill').innerHTML = hf; }
  }
  function oFind(c){ return ((ords && ords.pend) || []).find(r => r.c === c); }
  function oStartEdit(c, v){
    oEdit = {c: c, v: v};
    renderOrders(true);
    const i = $('o-in'); if (!i) return;
    i.focus(); i.select();
    i.addEventListener('keydown', e => {
      if (e.key === 'Escape') { oEdit = null; renderOrders(true); }
      if (e.key !== 'Enter') return;
      const v2 = parseFloat(i.value), r = oFind(c);
      if (!(v2 > 0)) { toast({kind: 'warn', text: 'Type a price'}); return; }
      if (!r) { oEdit = null; renderOrders(true); toast({kind: 'err', text: 'That order is not pending any more'}); return; }
      i.disabled = true;
      api('order_modify', c, v2).then(res => {
        oEdit = null;
        if (res && res.ok) toast({kind: 'info', text: `${r.s}: changing the ${r.ek} price to ${fmtPx(res.price)}...`});
        else toast({kind: 'err', text: (res && res.error) || 'Could not change the price'});
        renderOrders(true);
      });
    });
    i.addEventListener('blur', () => setTimeout(() => { if (oEdit && oEdit.c === c && !i.disabled) { oEdit = null; renderOrders(true); } }, 150));
  }
  function oClick(e){
    const s2 = e.target.closest('[data-os]');
    if (s2) { api('load_symbol', s2.dataset.os).then(res => { if (res && res.recent) setRecent(res.recent); }); return; }
    const ed = e.target.closest('[data-ed]');
    if (ed) { oStartEdit(ed.dataset.ed, ed.dataset.px); return; }
    const x = e.target.closest('[data-oc]');
    if (x) {
      const c = x.dataset.oc, r = oFind(c); if (!r) return;
      const msg = (O_CANCEL_MSG[r.r] || (s => `Cancel this ${r.sd} ${r.ty} order on ${s}?`))(r.s) + ' Click again within 5 seconds.';
      twoStep(x, 'oc' + c, 'Cancel', msg, () => {
        api('order_cancel', c).then(res => { if (!(res && res.ok)) toast({kind: 'err', text: (res && res.error) || 'Could not cancel'}); });
      });
      if (x.classList.contains('arm')) x.textContent = 'Sure?';
    }
  }
  $('o-pend').addEventListener('click', oClick);
  $('o-fill').addEventListener('click', oClick);
  $('o-all').addEventListener('change', e => { ordAll = e.target.checked; renderOrders(true); save(); });
  $('o-tog').addEventListener('click', () => {
    const lc = $('leftcol'); lc.classList.toggle('oclosed');
    $('o-tog').innerHTML = lc.classList.contains('oclosed') ? '&#9650;' : '&#9660;';
    applySizes(); save();
  });
  $('orders').querySelector('.oh').addEventListener('dblclick', e => { if (!e.target.closest('button,label')) $('o-tog').click(); });

  // ---------------- premarket long tab (orders panel) ----------------
  const lSetup = s => s === '1m MOMENTUM CHASE' ? 'Momentum' : s === '1m BULL FLAG' ? 'Bull flag' : (s || '');
  const L_RES = {'STOP OUT': 'Stop', 'BREAKEVEN OUT': 'Breakeven', 'TIME STOP (DEAD MONEY)': 'Time stop',
    'TRAILING STOP OUT': 'Trail stop', 'MARKET OPEN FLAT': 'Flatten', 'SOLD FROM APP': 'Sold by you'};
  const lRes = s => { const half = (s || '').includes('(half at target)'), base = (s || '').replace(' (half at target)', '');
    return esc(L_RES[base] || base) + (half ? ' <small>+ half at target</small>' : ''); };
  const lPnl = v => v == null ? '' : (v >= 0 ? 'grn' : 'red');
  const lMoney = v => v == null ? '-' : (v > 0 ? '+' : v < 0 ? '-' : '') + '$' + Math.abs(v).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  function showTab(t){
    oTab = ['long', 'loc', 'pos', 'alr'].includes(t) ? t : 'orders';
    $('orders').classList.toggle('tab-alr', oTab === 'alr'); $('tab-alr').classList.toggle('on', oTab === 'alr');
    $('orders').classList.toggle('tab-long', oTab === 'long');
    $('orders').classList.toggle('tab-loc', oTab === 'loc');
    $('orders').classList.toggle('tab-pos', oTab === 'pos');
    $('tab-ord').classList.toggle('on', oTab === 'orders'); $('tab-long').classList.toggle('on', oTab === 'long');
    $('tab-loc').classList.toggle('on', oTab === 'loc'); $('tab-pos').classList.toggle('on', oTab === 'pos');
    if (oTab === 'pos') renderPos();
    if ($('leftcol').classList.contains('oclosed')) { $('leftcol').classList.remove('oclosed'); $('o-tog').innerHTML = '&#9660;'; applySizes(); }
    renderLong(); if (oTab === 'orders') renderOrders(true);
    if (oTab === 'loc') { renderLoc(); api('loc_refresh'); setTimeout(() => $('lc-sym').focus(), 50); }
    if (oTab === 'alr') { renderAlerts(); if (!$('al-sym').value) $('al-sym').value = sym; }
    save();
  }
  function renderLong(){
    if (!lng) return;
    const act = lng.act || [], cls = lng.cls || [];
    $('lt-n').textContent = act.length ? ' ' + act.length : '';
    $('l-on').checked = !!lng.on;
    const st = {off: 'OFF', waiting: 'waiting', running: 'running', closing: 'selling', done: 'done today'}[lng.st] || lng.st;
    $('l-state').textContent = st;
    $('l-state').className = 'lstate o-lng ' + (lng.st || '');
    $('l-meta').textContent = (lng.note ? lng.note + ' - ' : '') + `${lng.win} ET weekdays` + (lng.st === 'running' ? ` - scanning, ${lng.watch} watched` : '');
    $('l-meta').className = 'm o-lng' + (lng.note ? ' err' : '');
    if (oTab !== 'long') return;
    $('l-na').textContent = act.length; $('l-nc').textContent = cls.length;
    $('l-tot').innerHTML = cls.length ? `${lng.w}/${lng.n} won - <b class="${lPnl(lng.tot)}">${lMoney(lng.tot)}</b>` : '';
    $('l-act').innerHTML = act.length ? act.map(r => {
      const armed = armed2['ls' + r.sym] && Date.now() - armed2['ls' + r.sym] < 5000;
      return `<div class="orow lga" title="${esc(r.sym + ' - ' + r.setup + ' - target ' + fmtPx(r.target) + (r.trail ? ' - half sold, trailing' : ''))}">` +
        `<span class="o-t">${esc(r.t)}</span><span class="o-s" data-os="${esc(r.sym)}">${esc(r.sym)}</span>` +
        `<span class="o-ty">${esc(lSetup(r.setup))}</span>` +
        `<span class="r">${r.sh.toLocaleString('en-US')}${r.sh !== r.init ? `<small>/${r.init.toLocaleString('en-US')}</small>` : ''}</span>` +
        `<span class="r">${fmtPx(r.entry)}</span><span class="r">${fmtPx(r.last)}</span>` +
        `<span class="r" title="${r.trail ? 'trailing stop (half sold at the target)' : 'stop'}">${fmtPx(r.stop)}${r.trail ? '<small> trail</small>' : ''}</span>` +
        `<span class="r l-pnl ${lPnl(r.pnl)}">${lMoney(r.pnl)}</span>` +
        (r.busy ? '<span class="o-busy">order...</span>' : `<button class="o-x${armed ? ' arm' : ''}" data-ls="${esc(r.sym)}" title="Sell this long now">${armed ? 'Sure?' : 'Sell'}</button>`) +
        `</div>`;
    }).join('') : `<div class="oempty">${!lng.on ? 'The long bot is OFF (switch above).' : lng.st === 'running' ? `No open long - the scanner is looking for stocks up ${lng.gap || 30}%+.` : `No open long. The long bot trades ${esc(lng.win)} ET on weekdays.`}</div>`;
    $('l-cls').innerHTML = cls.length ? cls.map(r => `<div class="orow lgc" title="${esc(r.sym + ' - ' + r.setup + ' - ' + r.res + ' - ' + r.r.toFixed(2) + 'R - out ' + r.tx)}">` +
        `<span class="o-t">${esc(r.t)}</span><span class="o-s" data-os="${esc(r.sym)}">${esc(r.sym)}</span>` +
        `<span class="r">${r.sh.toLocaleString('en-US')}</span><span class="r">${fmtPx(r.entry)}</span><span class="r">${fmtPx(r.exit)}</span>` +
        `<span class="o-ty">${lRes(r.res)}</span><span class="r l-pnl ${lPnl(r.pnl)}">${lMoney(r.pnl)}</span></div>`).join('')
      : '<div class="oempty">No closed long trades today.</div>';
  }
  $('tab-ord').addEventListener('click', () => showTab('orders'));
  $('tab-pos').addEventListener('click', () => showTab('pos'));
  $('tab-long').addEventListener('click', () => showTab('long'));
  $('tab-loc').addEventListener('click', () => showTab('loc'));
  $('tab-alr').addEventListener('click', () => showTab('alr'));

  // ---------------- 3.9.0: locate window (orders panel -> Locates) ----------------
  let loc = null, locRecv = 0;
  const lcMoney = v => v == null ? '-' : '$' + Number(v).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  const lcPx = v => v == null ? '-' : '$' + (v < 0.01 ? Number(v).toFixed(5) : Number(v).toFixed(4));
  function renderLoc(){
    if (!loc) return;
    const q = loc.q, rows = loc.rows || [], inv = loc.inv || [];
    $('lc-badge').textContent = rows.length ? ' ' + rows.length : '';
    $('lc-cap').textContent = loc.cap;
    $('lc-hint').textContent = loc.paper ? 'paper account - TradeZero has no locates there' : 'pre-borrow / re-usable and single-use offers';
    const m = $('lc-msg');
    m.textContent = q ? (q.msg || '') : (loc.tz ? 'Type a symbol and the number of shares, then Get prices.' : 'TradeZero is not connected.');
    m.className = 'lcmsg' + (q && q.err ? ' err' : q && q.state === 'done' ? ' ok' : '');
    const age = Date.now() / 1000 - locRecv;
    const offers = q && q.state === 'offers' ? (q.offers || []) : [];
    $('lc-offers').innerHTML = offers.length ? offers.map(o => {
      const left = Math.max(0, Math.round(o.left - age));
      const armed = armed2['lb' + o.id] && Date.now() - armed2['lb' + o.id] < 5000;
      return `<div class="orow lco" title="${esc(o.kind + ': ' + q.qty.toLocaleString('en-US') + ' ' + q.sym + ' x ' + lcPx(o.px) + ' = ' + lcMoney(o.total) + (q.last ? ' (last price ' + fmtPx(q.last) + ')' : ''))}">` +
        `<span class="${o.su ? 'lc-su' : ''}">${esc(o.kind)}</span><span class="r">${lcPx(o.px)}</span><span class="r">${lcMoney(o.total)}</span>` +
        `<span class="r">${o.pct == null ? '-' : o.pct.toFixed(2) + '%'}</span><span class="r">${left ? left + ' s' : 'expired'}</span>` +
        (left ? `<button class="o-buy${armed ? ' arm' : ''}" data-lb="${esc(o.id)}">${armed ? 'Click again' : 'Buy'}</button>` : '<span></span>') + `</div>`;
    }).join('') : `<div class="oempty">${q && q.state === 'asking' ? 'Waiting for TradeZero\'s offer (up to 25 s)...' : q && q.state === 'buying' ? 'Buying...' : 'No offers to show.'}</div>`;
    $('lc-ni').textContent = inv.length;
    $('lc-at').textContent = loc.invAt ? 'as of ' + loc.invAt : '';
    $('lc-inv').innerHTML = inv.length ? inv.map(r => `<div class="orow lci"><span class="o-s" data-os="${esc(r.sym)}">${esc(r.sym)}</span>` +
        `<span class="r">${Number(r.avail).toLocaleString('en-US')}</span><span>${esc(r.type)}</span></div>`).join('')
      : `<div class="oempty">${loc.invAt ? 'No located shares in the account.' : 'Refresh to read TradeZero\'s locate inventory.'}</div>`;
    $('lc-nb').textContent = rows.length;
    $('lc-spent').textContent = rows.length ? 'paid ' + lcMoney(loc.spent) : '';
    $('lc-rows').innerHTML = rows.length ? rows.slice().reverse().map(r => `<div class="orow lcb"><span class="o-t">${esc(r.t)}</span>` +
        `<span class="o-s" data-os="${esc(r.sym)}">${esc(r.sym)}</span><span class="r">${Number(r.qty).toLocaleString('en-US')}</span>` +
        `<span class="r">${lcPx(r.px)}</span><span class="r">${lcMoney(r.total)}</span><span>${esc(r.type)}</span>` +
        `<span>${r.by === 'you' ? 'You' : 'Bot'}</span></div>`).join('') : '<div class="oempty">No locates bought today.</div>';
  }
  function lcGo(){
    const sy = $('lc-sym').value.trim().toUpperCase(), n = parseInt(($('lc-qty').value || '').replace(/[, ]/g, ''), 10);
    if (!/^[A-Z0-9. ]{1,12}$/.test(sy)) { toast({kind: 'warn', text: 'Type a symbol, e.g. XRPN'}); $('lc-sym').focus(); return; }
    if (!(n > 0)) { toast({kind: 'warn', text: 'Type the number of shares'}); $('lc-qty').focus(); return; }
    api('loc_quote', sy, n).then(r => { if (r && !r.ok) toast({kind: 'err', text: r.error}); });
  }
  $('lc-go').addEventListener('click', lcGo);
  ['lc-sym', 'lc-qty'].forEach(id => $(id).addEventListener('keydown', e => { if (e.key === 'Enter') lcGo(); }));
  $('lc-x').addEventListener('click', () => api('loc_cancel'));
  $('lc-ref').addEventListener('click', () => api('loc_refresh'));
  $('lc-body').addEventListener('click', e => {
    const s2 = e.target.closest('[data-os]');
    if (s2) { api('load_symbol', s2.dataset.os).then(res => { if (res && res.recent) setRecent(res.recent); }); return; }
    const b = e.target.closest('[data-lb]');
    if (!b || !loc || !loc.q) return;
    const id = b.dataset.lb, o = (loc.q.offers || []).find(x => x.id === id);
    if (!o) return;
    twoStep(b, 'lb' + id, 'Buy', `Buy ${loc.q.qty.toLocaleString('en-US')} ${loc.q.sym} (${o.kind}) at ${lcPx(o.px)} a share = ${lcMoney(o.total)}? Click again within 5 seconds.`,
      () => api('loc_accept', id).then(r => { if (r && !r.ok) toast({kind: 'err', text: r.error}); }));
  });
  setInterval(() => { if (oTab === 'loc' && loc && loc.q && loc.q.state === 'offers') renderLoc(); }, 1000);

