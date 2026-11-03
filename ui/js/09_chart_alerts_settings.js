  // ---- 3.12.1: right click on the chart = price alert above / below that price (fires once, Discord) ----
  function ctxClose(){ $('ctxm').classList.add('hidden'); }
  // 3.14: the chart's right-click menu (Add note + these alerts) is built in 09b_chart_notes.js
  $('ctxm').addEventListener('click', e => {
    const b = e.target.closest('[data-cd]'); if (!b) return;
    const d = b.dataset.cd, p = Number(b.dataset.cp), s = sym; ctxClose();
    api('alert_add', s, p, s === sym ? lastPx : null, d).then(res => {
      if (res && res.ok) toast({kind: 'info', text: `Alert set: ${s} ${d === 'up' ? 'above' : 'below'} ${fmtPx(res.alert.px)} - fires once`});
      else toast({kind: 'err', text: (res && res.error) || 'Could not add the alert'});
    });
  });
  document.addEventListener('mousedown', e => { if (!e.target.closest('#ctxm')) ctxClose(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') ctxClose(); });
  window.addEventListener('blur', ctxClose);

  // 3.13: Settings screen - the menu's switches / modes / connection, the drawer's panels and the Hotkeys screen move in
  (function buildSettings(){
    const tr = $('set-trading');
    ['auto-wrap'].forEach(id => tr.appendChild($(id)));
    tr.appendChild($('t-ext').closest('label')); tr.appendChild($('t-sound').closest('label'));
    const mh = document.createElement('div'); mh.className = 'mh'; mh.textContent = 'TRADING MODE'; tr.appendChild(mh);
    tr.appendChild($('modes'));
    $('set-sig').appendChild($('dp-sig')); $('set-skip').appendChild($('dp-skip')); $('set-log').appendChild($('dp-log'));
    const hk = $('set-hotkeys'); while ($('scr-keys').firstChild) hk.appendChild($('scr-keys').firstChild);
    $('set-conn').appendChild(document.querySelector('#menu .mconn'));
    $('set-env-box').appendChild(document.querySelector('#keys-ov .kbox'));
    $('set-nav').addEventListener('click', e => { const b = e.target.closest('[data-sec]'); if (b) setSection(b.dataset.sec); });
    const mirror = (from, to) => { const a = $(from), b = $(to); if (!a || !b) return;
      new MutationObserver(() => { b.textContent = a.textContent; }).observe(a, {childList: true, characterData: true, subtree: true}); b.textContent = a.textContent; };
    mirror('m-sig', 's-sig'); mirror('m-skip', 's-skip');
  })();
  let setSec = 'trading';
  function setSection(k){
    setSec = k;
    document.querySelectorAll('#set-nav [data-sec]').forEach(b => b.classList.toggle('on', b.dataset.sec === k));
    document.querySelectorAll('#scr-set .setsec').forEach(el => el.classList.toggle('on', el.id === 'set-' + k));
    if (k === 'trading') { modesSeen = null; renderModes(); }
    if (k === 'hotkeys') renderHK();
    if (k === 'env') keysLoad();
    if (k === 'colors') colRender();
  }
  function openSettings(k){ showScreen('set'); if (k) setSection(k); }
  function showScreen(s){
    if (s === 'keys') { s = 'set'; setTimeout(() => setSection('hotkeys'), 0); }
    if (!['chart', 'scan', 'journal', 'bot', 'set', 'fav', 'bt'].includes(s)) s = 'chart';
    const prev = screen; screen = s;
    document.querySelectorAll('.screen').forEach(el => el.classList.toggle('on', el.id === 'scr-' + s));
    document.querySelectorAll('#rail .rb').forEach(b => b.classList.toggle('on', b.dataset.scr === s));
    if (s === 'scan' && prev !== 'scan') { api('scan_screen', true, scanCfg); renderScan(); }
    if (s === 'journal') loadJournal();
    if (s === 'bot') renderBC();
    if (s === 'set') setSection(setSec);
    if (s === 'fav') renderFav();
    if (s === 'bt') btLoad();
    if (prev !== s) api('ui_screen', s);
    menu(false);
  }
  $('rail').addEventListener('click', e => { const b = e.target.closest('[data-scr]'); if (b) showScreen(b.dataset.scr); });

