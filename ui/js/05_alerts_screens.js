  // ---------------- 3.11: older days (display only), price alerts, screens, hotkeys ----------------
  function olderHtml(){
    let html = '', cur = null;
    for (const t of oldTrades) {
      if (t.day !== cur) {
        cur = t.day;
        const dayT = oldTrades.filter(x => x.day === cur), rr = dayT.reduce((a, x) => a + (x.R || 0), 0);
        html += `<div class="dayh older"><span>${fmtDay(t.t)} - older day, display only</span><span>${plural(dayT.length, 'trade')} ${fmtR(rr)}</span></div>`;
      }
      html += card(t);
    }
    return html;
  }
  let alSeen = '';
  function renderAlertLines(){
    for (const pl of alertLines) { try { candles.removePriceLine(pl); } catch (e) {} }
    alertLines = [];
    for (const a of alerts) if (a.sym === sym) alertLines.push(candles.createPriceLine({price: a.px, color: '#2962ff', lineWidth: 1,
      lineStyle: LWC.LineStyle.Dashed, axisLabelVisible: true, title: 'Alert'}));
  }
  function renderAlerts(){
    $('al-n').textContent = alerts.length ? ' ' + alerts.length : '';
    const key = JSON.stringify(alerts) + '|' + sym;
    if (key !== alSeen) { alSeen = key; renderAlertLines(); }
    if (oTab !== 'alr') return;
    $('al-no').textContent = alerts.length;
    const lastOf = s => { if (s === sym) return lastPx; const rw = ((bot && bot.rows) || []).find(x => x.sym === s); return rw ? rw.last : null; };
    $('al-list').innerHTML = alerts.length ? alerts.slice().reverse().map(a => `<div class="orow algrid"><span class="o-s" data-os="${esc(a.sym)}">${esc(a.sym)}</span>` +
      `<span>${a.dir === 'up' ? 'rises to' : 'falls to'} <b>${fmtPx(a.px)}</b></span><span class="r">${fmtPx(lastOf(a.sym))}</span><span class="o-t">${esc(a.t)}</span>` +
      `<button class="al-x" data-ax="${esc(a.id)}" title="Remove">&times;</button></div>`).join('')
      : '<div class="oempty">No price alerts</div>';
  }
  function alertAdd(s, p){
    api('alert_add', s, p, s === sym ? lastPx : null).then(res => {
      if (res && res.ok) toast({kind: 'info', text: `Alert: ${s} ${res.alert.dir === 'up' ? 'rises to' : 'falls to'} ${fmtPx(res.alert.px)}` +
        (res.watched ? '' : ' - it fires once the stock is on the chart or the watchlist')});
      else toast({kind: 'err', text: (res && res.error) || 'Could not add the alert'});
    });
  }
  $('al-go').addEventListener('click', () => {
    const s = ($('al-sym').value || sym || '').trim().toUpperCase(), p = parseFloat($('al-px').value);
    if (!/^[A-Z0-9. ]{1,12}$/.test(s)) { toast({kind: 'warn', text: 'Type a symbol'}); return; }
    if (!(p > 0)) { toast({kind: 'warn', text: 'Type a price'}); return; }
    $('al-px').value = ''; alertAdd(s, p);
  });
  ['al-sym', 'al-px'].forEach(id => $(id).addEventListener('keydown', e => { if (e.key === 'Enter') $('al-go').click(); }));
  $('al-body').addEventListener('click', e => {
    const s2 = e.target.closest('[data-os]');
    if (s2) { api('load_symbol', s2.dataset.os).then(res => { if (res && res.recent) setRecent(res.recent); }); return; }
    const x = e.target.closest('[data-ax]'); if (x) api('alert_remove', x.dataset.ax);
  });
  $('chart').addEventListener('click', e => {                 // Alt + click = price alert, Ctrl + click = move the stop
    if (!(e.altKey || e.ctrlKey) || !sym || !shown.length) return;
    const rc = $('chart').getBoundingClientRect(), p0 = candles.coordinateToPrice(e.clientY - rc.top);
    if (p0 == null || !(p0 > 0)) return;
    const p = Number(Number(p0).toFixed(precision));
    if (e.altKey) { alertAdd(sym, p); return; }
    if (!hkEnabled) { toast({kind: 'warn', text: 'Ctrl + click moves a stop only with Order hotkeys on (Hotkeys screen)'}); return; }
    const rw = ((bot && bot.rows) || []).find(x => x.sym === sym);
    if (!rw || !['short', 'manual'].includes(rw.phase)) { toast({kind: 'warn', text: `No open bot short on ${sym}`}); return; }
    api('bot_set_stop', sym, p).then(res => toast(res && res.ok ? {kind: 'info', text: `${sym}: moving the stop to ${fmtPx(p)}`}
      : {kind: 'err', text: (res && res.error) || 'Could not move the stop'}));
  });

