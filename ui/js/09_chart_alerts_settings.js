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
    if (k === 'strat') ssLoad();
  }
  // ---- 3.15: Settings > Strategies - your changes over the strategy files (saved next to the bot; new signals use them) ----
  let ssK = 'jr2', ssTab = 0, ssView = null, ssEdit = {};
  function ssShown(f, v){ if (v == null || v === '') return ''; if (f.kind === 'bool' || f.kind === 'time' || f.kind.startsWith('opt:')) return v;
    const x = Number(v) / (f.scale || 1); return String(Math.round(x * 10000) / 10000); }
  function ssLoad(k){ if (k) ssK = k; api('strat_view', ssK).then(r => { if (!r || !r.ok) { $('ss-body').innerHTML = `<div class="oempty">${esc((r && r.error) || 'Not available')}</div>`; return; }
    ssView = r; ssEdit = {}; if (ssTab >= r.tabs.length) ssTab = 0; ssRender(); }); }
  function ssVal(f){ return f.key in ssEdit ? ssEdit[f.key] : f.value; }
  function ssRender(bad){
    const r = ssView; if (!r) return;
    const all = r.tabs.flatMap(t => t.groups.flatMap(g => g.fields));
    const diff = all.filter(f => f.key in ssEdit && JSON.stringify(ssEdit[f.key]) !== JSON.stringify(f.value));
    const saved = all.filter(f => f.changed);
    const tab = r.tabs[ssTab], half = Math.ceil(tab.groups.length / 2);
    const fld = f => { const v = ssVal(f), ch = JSON.stringify(v) !== JSON.stringify(f.default), err = bad && bad[f.key];
      let inp;
      if (f.kind === 'bool') inp = `<select data-sk="${esc(f.key)}"><option value="1"${v ? ' selected' : ''}>On</option><option value="0"${v ? '' : ' selected'}>Off</option></select>`;
      else if (f.kind.startsWith('opt:')) inp = `<select data-sk="${esc(f.key)}">${f.kind.slice(4).split('|').map(o => `<option${o === v ? ' selected' : ''} value="${o}">${{hod: 'High of day', rh: 'Regular-hours high', bh: 'Bounce high'}[o] || o}</option>`).join('')}</select>`;
      else inp = `<input data-sk="${esc(f.key)}" value="${esc(ssShown(f, v))}" placeholder="${f.kind === 'num?' ? 'none' : ''}" spellcheck="false">`;
      return `<div class="ss-f${ch ? ' ch' : ''}${err ? ' bad' : ''}"><div class="k">${esc(f.label)}${err ? `<small style="color:var(--neg)">${esc(err)}</small>` : ''}</div>` +
        `<div class="ss-in">${ch ? `<span class="ss-was">was ${esc(ssShown(f, f.default) === '' ? 'none' : f.kind === 'bool' ? (f.default ? 'On' : 'Off') : ssShown(f, f.default))}</span>` : ''}${inp}<em>${esc(f.unit || '')}</em></div></div>`; };
    const col = gs => gs.map(g => `<div class="ss-grp"><div class="mh">${esc(g.name.toUpperCase())}</div>${g.fields.map(fld).join('')}</div>`).join('');
    $('ss-body').innerHTML = `<div class="ss-top"><div class="seg2" id="ss-k">${r.list.map(s => `<button data-v="${s.k}" class="${s.k === ssK ? 'on' : ''}">${esc(s.name)}</button>`).join('')}</div>` +
      `<span class="sm">Trading mode is set in Trading</span></div>` +
      (r.tabs.length > 1 ? `<div class="ss-top"><div class="seg2" id="ss-tab">${r.tabs.map((t, i) => `<button data-v="${i}" class="${i === ssTab ? 'on' : ''}">${esc(t.name)}</button>`).join('')}</div>` +
        `<span class="sm">${esc(tab.note)}</span></div>` : '') +
      (r.loaded ? '' : '<div class="sm jred">This strategy is not loaded in the bot right now - saved values apply when it is.</div>') +
      `<div class="ss-cols"><div>${col(tab.groups.slice(0, half))}</div><div>${col(tab.groups.slice(half))}</div></div>` +
      `<div class="ss-foot"><span class="dot ${diff.length ? 'warn' : 'ok'}"></span><span class="n">${diff.length ? plural(diff.length, 'unsaved change') : saved.length ? plural(saved.length, 'setting') + ' changed from the file' : 'File defaults'}</span>` +
      `<span class="sm">New signals use them at once · open positions keep their stop</span><div class="spacer"></div>` +
      `<button class="sbtn" id="ss-reset">Reset to default</button><button class="sbtn" id="ss-bt">Backtest these settings</button>` +
      `<button class="sbtn" id="ss-discard"${diff.length ? '' : ' disabled'}>Discard</button><button class="sbtn pri" id="ss-save"${diff.length ? '' : ' disabled'}>Save</button></div>`;
  }
  function ssParse(f, raw){
    if (f.kind === 'bool') return raw === '1';
    if (f.kind === 'time' || f.kind.startsWith('opt:')) return raw;
    if (raw.trim() === '' && f.kind === 'num?') return null;
    const x = Number(raw); return isNaN(x) ? raw : x * (f.scale || 1);
  }
  $('ss-body').addEventListener('change', e => { const el = e.target.closest('[data-sk]'); if (!el || !ssView) return;
    const f = ssView.tabs.flatMap(t => t.groups.flatMap(g => g.fields)).find(x => x.key === el.dataset.sk); if (!f) return;
    ssEdit[f.key] = ssParse(f, el.value); ssRender(); });
  $('ss-body').addEventListener('click', e => {
    const k = e.target.closest('#ss-k [data-v]'); if (k) { ssTab = 0; ssLoad(k.dataset.v); return; }
    const t = e.target.closest('#ss-tab [data-v]'); if (t) { ssTab = Number(t.dataset.v); ssRender(); return; }
    if (e.target.closest('#ss-discard')) { ssEdit = {}; ssRender(); return; }
    if (e.target.closest('#ss-save')) { api('strat_save', ssK, ssEdit).then(r => {
      if (r && r.ok) { ssView = Object.assign({}, ssView, r); ssEdit = {}; ssRender(); toast({kind: 'info', text: `${ssView.name}: saved - new signals use them now`}); }
      else { ssRender(r && r.fields); toast({kind: 'err', text: (r && r.error) || 'Not saved'}); } }); return; }
    if (e.target.closest('#ss-reset')) { twoStep($('ss-reset'), 'ssreset', 'Reset to default', `Reset ${ssView.name} to the strategy file's values? Click again.`,
      () => api('strat_save', ssK, {}, true).then(r => { if (r && r.ok) { ssView = Object.assign({}, ssView, r); ssEdit = {}; ssRender(); toast({kind: 'info', text: 'Back to the file defaults'}); } })); return; }
    if (e.target.closest('#ss-bt')) {
      if (Object.keys(ssEdit).length) { toast({kind: 'warn', text: 'Save first - the backtest runs with the saved settings'}); return; }
      const m = {jr2: 'jr2', jr: 'jr', long: 'long'}[ssK]; btGo = {k: m, tk: '', day: ''}; showScreen('bt'); }
  });

  function openSettings(k){ showScreen('set'); if (k) setSection(k); }
  function showScreen(s){
    if (s === 'keys') { s = 'set'; setTimeout(() => setSection('hotkeys'), 0); }
    if (!['chart', 'scan', 'journal', 'bot', 'set', 'fav', 'bt', 'notes', 'ib'].includes(s)) s = 'chart';
    const prev = screen; screen = s;
    document.querySelectorAll('.screen').forEach(el => el.classList.toggle('on', el.id === 'scr-' + s));
    document.querySelectorAll('#rail .rb').forEach(b => b.classList.toggle('on', b.dataset.scr === s));
    if (s === 'scan' && prev !== 'scan') { api('scan_screen', true, scanCfg); renderScan(); }
    if (s === 'journal') loadJournal();
    if (s === 'bot') renderBC();
    if (s === 'set') setSection(setSec);
    if (s === 'fav') renderFav();
    if (s === 'bt') btLoad();
    if (s === 'notes') ntLoad();
    if (s === 'ib') ibLoad();
    if (prev !== s) api('ui_screen', s);
    menu(false);
  }
  $('rail').addEventListener('click', e => { const b = e.target.closest('[data-scr]'); if (b) showScreen(b.dataset.scr); });

