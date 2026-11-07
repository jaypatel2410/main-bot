  // ---------------- 3.9.0: closing the app with a position open ----------------
  let closeWait = null;
  const clText = o => `${esc(o.sym)} - ${esc(o.side)} ${Number(o.qty).toLocaleString('en-US')} sh` + (o.avg ? ` @ ${fmtPx(o.avg)}` : '') +
    (o.side === 'long' ? ` - stop ${o.stop ? fmtPx(o.stop) : '-'} watched by the app only (no stop order at TradeZero)` :
     o.stop ? ` - stop ${fmtPx(o.stop)} at TradeZero` : ' - no stop order');
  function askClose(p){
    clearInterval(closeWait); closeWait = null;
    $('cl-list').innerHTML = (p.items || []).map(o => `<div>${clText(o)}</div>`).join('');
    $('cl-st').textContent = '';
    ['cl-yes', 'cl-no', 'cl-cancel'].forEach(id => $(id).disabled = false);
    $('cl-yes').textContent = 'Yes - close them';
    $('close-ov').classList.remove('hidden');
  }
  $('cl-cancel').addEventListener('click', () => { clearInterval(closeWait); closeWait = null; $('close-ov').classList.add('hidden'); api('close_choice', 'cancel'); });
  $('cl-no').addEventListener('click', () => { $('cl-st').textContent = 'Closing the app - the positions and their stops stay at TradeZero.'; api('close_choice', 'no'); });
  $('cl-yes').addEventListener('click', () => {
    if ($('cl-yes').dataset.force === '1') { api('close_choice', 'exit'); return; }
    ['cl-yes', 'cl-no'].forEach(id => $(id).disabled = true);
    $('cl-st').textContent = 'Cancelling the stops and closing at market...';
    api('close_choice', 'yes');
    const t0 = Date.now();
    closeWait = setInterval(() => {
      api('close_state').then(r => {
        const left = (r && r.open) || [];
        if (!left.length) { clearInterval(closeWait); closeWait = null; $('cl-st').textContent = 'Everything is closed - closing the app.'; api('close_choice', 'exit'); return; }
        $('cl-list').innerHTML = left.map(o => `<div>${clText(o)}</div>`).join('');
        if (Date.now() - t0 > 45000) {
          clearInterval(closeWait); closeWait = null;
          $('cl-st').textContent = 'Still open after 45 s - check TradeZero. Close the app anyway, or Cancel to keep it open.';
          $('cl-yes').disabled = false; $('cl-yes').dataset.force = '1'; $('cl-yes').textContent = 'Close the app anyway';
        }
      });
    }, 1000);
  });

  const armed2 = {};
  function twoStep(btn, key, label, msg, fn){
    if (armed2[key] && Date.now() - armed2[key] < 5000) { armed2[key] = 0; btn.classList.remove('arm'); btn.textContent = label; fn(); return; }
    armed2[key] = Date.now(); btn.classList.add('arm'); btn.textContent = 'Click again'; toast({kind: 'warn', text: msg});
    setTimeout(() => { if (armed2[key]) { armed2[key] = 0; btn.classList.remove('arm'); btn.textContent = label; } }, 5000);
  }
  function wlAdd(){
    const v = $('wl-in').value.trim().toUpperCase();
    if (!/^[A-Z0-9. ]{1,12}$/.test(v)) { toast({kind: 'warn', text: 'Type a ticker, e.g. XRPN'}); return; }
    $('wl-in').value = '';
    api('bot_add', v);
  }
  $('wl-in').addEventListener('keydown', e => { if (e.key === 'Enter') wlAdd(); });
  $('wl-btn').addEventListener('click', wlAdd);
  let stopSym = '';
  function stopDialog(b){
    stopSym = b.dataset.stop;
    $('s-title').textContent = `Move the stop - ${stopSym}`;
    $('s-sub').textContent = `Current stop ${b.dataset.px || '-'}, last ${b.dataset.last || '-'}. The bot cancels its stop and places the new one (buy stop above the last price).`;
    $('s-px').value = b.dataset.px || ''; $('s-st').textContent = '';
    $('stop-ov').classList.remove('hidden'); $('s-px').focus(); $('s-px').select();
  }
  function stopSave(){
    const v = parseFloat($('s-px').value);
    if (!(v > 0)) { $('s-st').textContent = 'Type a price'; return; }
    api('bot_set_stop', stopSym, v).then(r => {
      if (r && r.ok) { $('stop-ov').classList.add('hidden'); toast({kind: 'info', text: `${stopSym}: moving the stop to ${v}`}); }
      else $('s-st').textContent = (r && r.error) || 'Could not move the stop';
    });
  }
  $('s-cancel').addEventListener('click', () => $('stop-ov').classList.add('hidden'));
  $('s-save').addEventListener('click', stopSave);
  $('s-px').addEventListener('keydown', e => { if (e.key === 'Enter') stopSave(); if (e.key === 'Escape') $('stop-ov').classList.add('hidden'); });
  $('wl-list').addEventListener('click', e => {
    const x = e.target.closest('.w-x');
    if (x) { e.stopPropagation(); api('bot_remove', x.dataset.x); return; }
    const sb = e.target.closest('[data-stop]');
    if (sb) { e.stopPropagation(); stopDialog(sb); return; }
    const cb = e.target.closest('[data-cover]');
    if (cb) {
      e.stopPropagation();
      const s2 = cb.dataset.cover, lab = cb.dataset.label;
      twoStep(cb, 'cov' + s2, lab, `${lab} ${s2}: click again within 5 seconds (${lab === 'Cover' ? 'buy to cover at market' : 'cancel the entry order'})`,
        () => api('bot_cover', s2));
      return;
    }
    const r = e.target.closest('.wrow'); if (!r) return;
    document.querySelectorAll('.wrow.sel').forEach(el => el.classList.remove('sel'));
    r.classList.add('sel');
    api('load_symbol', r.dataset.sym).then(res => { if (res && res.recent) setRecent(res.recent); });
  });
  let autoArm = 0;
  $('t-auto').addEventListener('change', e => {
    const on = e.target.checked;
    e.target.checked = !!(bot && bot.auto);
    if (on && bot && bot.acct && String(bot.acct.type).toLowerCase() === 'live' && Date.now() - autoArm > 5000) {
      autoArm = Date.now(); toast({kind: 'warn', text: 'LIVE account: click Auto-trade again within 5 seconds to let the bot place real orders'}); return;
    }
    autoArm = 0;
    api('bot_auto', on);
  });
  $('flat-btn').addEventListener('click', () => twoStep($('flat-btn'), 'flat', 'Flatten all',
    'Flatten all: click again within 5 seconds to cancel every bot order and cover every bot short', () => api('bot_flatten')));
  function keysLoad(){                             // 3.12.1: the keys are shown in Settings > Keys and Discord (no popup)
    api('tz_keys').then(r => {
      r = r || {};
      $('k-id').value = r.id || ''; $('k-sec').value = ''; $('k-acc').value = r.acc || '';
      $('k-file').textContent = r.file || '.env';
      $('k-st').textContent = r.hasSecret ? 'Secret saved' : 'No keys saved yet';
    });
    dcLoad();
    api('news_keys').then(k => { k = k || {}; if (document.activeElement !== $('n-id')) $('n-id').value = k.alpacaId || '';
      if (document.activeElement !== $('n-mail')) $('n-mail').value = k.secMail || '';
      $('n-av').placeholder = k.hasAv ? 'a key is saved - leave empty to keep it' : 'free key: alphavantage.co - 25 lookups a day';
      $('n-sec').placeholder = k.hasSecret ? 'a secret is saved - leave empty to keep it' : 'paste the secret key'; });
    api('turso_keys').then(t => { t = t || {}; if (document.activeElement !== $('t-url')) $('t-url').value = t.url || ''; $('t-tok').placeholder = t.hasToken ? 'a token is saved - leave empty to keep it' : 'paste the auth token'; });
    cloudStatus();
    api('bt_list').then(r => { if (r && r.ok && document.activeElement !== $('bt-vault')) $('bt-vault').value = r.vault || ''; });   // 3.13.1: vault location
  }
  $('tz-keys').addEventListener('click', () => openSettings('env'));
  // 3.14: Turso status line (header pill + the line in Settings) and its credentials
  function cloudStatus(){
    api('turso_status').then(s => {
      s = s || {};
      const p = $('cloud'), ago = s.last_ok == null ? '' : s.last_ok < 90 ? `${s.last_ok}s ago` : `${Math.round(s.last_ok / 60)} min ago`;
      p.className = 'pill' + (s.state === 'ok' ? ' connected' : s.state === 'error' ? ' disconnected' : '');
      p.querySelector('span').textContent = s.state === 'ok' ? 'Cloud synced' : s.state === 'error' ? 'Cloud offline' : 'Cloud off';
      p.title = s.state === 'ok' ? `Turso ${s.host} - last contact ${ago || 'just now'}${s.pending ? `, ${s.pending} change(s) waiting` : ''}`
        : s.state === 'error' ? `Turso: ${s.error || 'not reachable'} - this PC keeps working with its own copy` : 'Turso is not set up - Settings > Keys and Discord';
      $('t-st').textContent = s.state === 'ok' ? `Connected to ${s.host} - last contact ${ago || 'just now'}${s.pending ? `, ${s.pending} change(s) waiting` : ''}`
        : s.state === 'error' ? `Not connected: ${s.error || 'not reachable'}` : 'Not set up - this PC uses its own files only';
    });
  }
  $('cloud').addEventListener('click', () => openSettings('env'));
  $('n-save').addEventListener('click', () => {               // 3.14: Alpaca + SEC (the News tab)
    $('n-st').textContent = 'Saving...';
    api('av_save', $('n-av').value.trim()).then(a => { if (a && !a.ok) toast({kind: 'err', text: a.error}); else $('n-av').value = ''; });
    api('news_save', $('n-id').value.trim(), $('n-sec').value.trim(), $('n-mail').value.trim()).then(r => {
      if (r && r.ok) { $('n-sec').value = ''; $('n-st').textContent = 'Saved - the news feeds reconnect now (status in the News tab)'; toast({kind: 'info', text: 'News keys saved'}); }
      else $('n-st').textContent = (r && r.error) || 'Could not save';
    });
  });
  $('t-save').addEventListener('click', () => {
    $('t-st').textContent = 'Connecting...';
    api('turso_save', $('t-url').value.trim(), $('t-tok').value.trim()).then(r => {
      if (r && r.ok) { $('t-tok').value = ''; toast({kind: 'info', text: 'Turso saved - restart the app once to load your cloud data'}); setTimeout(cloudStatus, 2500); }
      else $('t-st').textContent = (r && r.error) || 'Could not save';
    });
  });
  setInterval(cloudStatus, 15000); whenApi(() => setTimeout(cloudStatus, 1500));
  function dcLoad(){
    api('discord_keys').then(d => {
      d = d || {};
      $('d-url').value = ''; $('d-men').value = d.mention || '';
      $('d-st').textContent = d.has ? (d.ok ? `A webhook is saved (...${d.tail})` : 'The saved webhook URL looks wrong') : 'No Discord webhook saved yet';
    });
  }
  $('k-cancel').addEventListener('click', () => $('keys-ov').classList.add('hidden'));
  $('k-save').addEventListener('click', () => {
    api('tz_save', $('k-id').value.trim(), $('k-sec').value.trim(), $('k-acc').value.trim()).then(r => {
      if (r && r.ok) { $('keys-ov').classList.add('hidden'); toast({kind: 'info', text: 'TradeZero keys saved - connecting...'}); }
      else toast({kind: 'err', text: (r && r.error) || 'Could not save the keys'});
    });
  });
  $('d-save').addEventListener('click', () => {
    api('discord_save', $('d-url').value.trim(), $('d-men').value.trim()).then(r => {
      if (r && r.ok) { $('d-st').textContent = 'Saved'; toast({kind: 'info', text: 'Discord webhook saved'}); dcLoad(); }
      else $('d-st').textContent = (r && r.error) || 'Could not save';
    });
  });
  $('d-test').addEventListener('click', () => {
    $('d-st').textContent = 'Sending...';
    api('discord_test', $('d-url').value.trim(), $('d-men').value.trim()).then(r => {
      if (r && r.ok) { $('d-st').textContent = 'Test message sent - check your Discord channel'; $('d-url').value = ''; }
      else $('d-st').textContent = (r && r.error) || 'Could not send';
    });
  });
  function markTf(){                                  // 3.11: the timeframe drop-down
    $('tf-lab').textContent = tf === 'D' ? '1D' : tf + 'm';
    document.querySelectorAll('#tf-menu button').forEach(b => b.classList.toggle('on', b.dataset.tf === String(tf)));
  }
  function ensureDaily(){
    if (!sym || (daily && dailySym === sym) || dailyLoading === sym) return;
    dailyLoading = sym;
    const want = sym;
    toast({kind: 'info', text: `Loading daily candles for ${want}...`});
    api('get_daily', want).then(r => {
      if (dailyLoading === want) dailyLoading = '';
      if (!r || r.sym !== want || want !== sym) return;
      if (!r.ok) { toast({kind: 'err', text: `Daily chart for ${want}: ${r.error}`}); return; }
      daily = r.rows; dailySym = want;
      if ($('toast').textContent.startsWith('Loading daily')) $('toast').className = 'hidden';
      if (tf === 'D') { render(false); defaultView(); }
    });
  }
  function setTf(v, quiet){
    v = v === 'D' ? 'D' : Number(v);
    if (![1, 2, 5, 15, 30, 'D'].includes(v)) v = 1;
    const prev = tf, range = shown.length ? chart.timeScale().getVisibleRange() : null;
    tf = v; markTf();
    chart.applyOptions({timeScale: {timeVisible: tf !== 'D'}});
    if (tf === 'D') ensureDaily();
    if ((prev === 'D') !== (tf === 'D')) setLevels(levelsNow);
    if (!quiet) save();
    if (!bars.length) return;
    render(false);
    if (tf === 'D' || prev === 'D' || !range) defaultView();
    else { try { chart.timeScale().setVisibleRange(range); } catch (e) { defaultView(); } }
    legend(null);
  }
  $('tf-btn').addEventListener('click', e => { e.stopPropagation(); $('tf-menu').classList.toggle('hidden'); });
  $('tf-menu').addEventListener('click', e => { const b = e.target.closest('[data-tf]'); if (b) { setTf(b.dataset.tf); $('tf-menu').classList.add('hidden'); } });
  document.addEventListener('mousedown', e => { if (!e.target.closest('.tfdd')) $('tf-menu').classList.add('hidden'); });

  // header: when the window is narrow, drop the least important items first (Up, Off HOD and Vol stay longest)
  const HDR = document.querySelector('header'), CHIPS = document.querySelector('.chips'), QUOTE = document.querySelector('.quote');
  const FIT_STEPS = [$('q-name'), 'compact', 'compact2', $('c-hod'), 'compact3', document.querySelector('.brand'), $('c-vwap'), $('acc-bp'), 'compact4', $('c-vol')];
  let fitPending = false;
  function fitHeader(){
    for (const s of FIT_STEPS) typeof s === 'string' ? HDR.classList.remove(s) : s.classList.remove('fh');
    const over = () => CHIPS.scrollWidth > CHIPS.clientWidth + 1 || QUOTE.scrollWidth > QUOTE.clientWidth + 1 || HDR.scrollWidth > HDR.clientWidth + 1;
    for (const s of FIT_STEPS) {
      if (!over()) break;
      typeof s === 'string' ? HDR.classList.add(s) : s.classList.add('fh');
    }
  }
  function fitSoon(){ if (fitPending) return; fitPending = true; requestAnimationFrame(() => { fitPending = false; fitHeader(); }); }
  window.addEventListener('resize', fitSoon);

  function setOverlay(id, on){ $(id).classList.toggle('hidden', !on); }
  function toast(m){
    const el = $('toast'); el.className = m.kind === 'err' ? 'err' : m.kind === 'warn' ? 'warn' : '';
    el.textContent = m.text; clearTimeout(toastTimer); toastTimer = setTimeout(() => el.className = 'hidden', m.kind === 'err' ? 9000 : 6000);
  }
  let newsFrac = 0.38, sideFrac = 0.22, scanFrac = 0.50, ordFrac = 0.28, ordAll = false, oTab = 'orders', lng = null;
  function save(){ api('save_settings', {ext: ext, skipped: showSkip, sound: sound, panel: !$('main').classList.contains('nopanel'),
                                         wside: sideFrac, scanh: scanFrac, newsw: newsFrac, tf: String(tf),
                                         orders: !$('leftcol').classList.contains('oclosed'), ordall: ordAll, ordh: ordFrac,
                                         otab: oTab, ts: !!tsOpen, tsw: tsFrac}); }
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  function applySizes(){
    const mw = $('main').getBoundingClientRect().width || window.innerWidth;
    const px = clamp(sideFrac * mw, 240, mw * 0.45);                 // 3.11: the watchlist (left), at least 240 px
    $('main').style.setProperty('--side-w', Math.round(px) + 'px');
    $('bottom').style.setProperty('--news-w', (newsFrac * 100).toFixed(2) + '%');
    $('side').style.setProperty('--scan-h', ((1 - scanFrac) * 100).toFixed(2) + '%');   // scanner height = what the watchlist leaves
    const lh = $('leftcol').getBoundingClientRect().height || window.innerHeight;
    $('leftcol').style.setProperty('--ord-h', Math.round(clamp(ordFrac * lh, 96, lh * 0.7)) + 'px');
  }
  function dragSplit(el, kind){
    el.addEventListener('mousedown', e => {
      if (e.button !== 0) return;
      e.preventDefault();
      el.classList.add('drag'); document.body.classList.add('resizing', kind);
      const move = ev => {
        if (kind === 'col') {
          const r = $('main').getBoundingClientRect();
          sideFrac = clamp((ev.clientX - r.left) / r.width, 0.12, 0.45);
        } else if (kind === 'ncol') {
          const r = $('bottom').getBoundingClientRect();
          newsFrac = clamp((ev.clientX - r.left) / r.width, 0.15, 0.75);
        } else if (kind === 'orow') {
          const r = $('leftcol').getBoundingClientRect();
          ordFrac = clamp((r.bottom - ev.clientY) / r.height, 0.10, 0.70);
        } else {
          const r = $('side').getBoundingClientRect();
          scanFrac = clamp((ev.clientY - r.top) / r.height, 0.12, 0.88);
        }
        applySizes();
      };
      const up = () => {
        window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up);
        el.classList.remove('drag'); document.body.classList.remove('resizing', kind);
        save();
      };
      window.addEventListener('mousemove', move); window.addEventListener('mouseup', up);
    });
    el.addEventListener('dblclick', () => { if (kind === 'col') sideFrac = 0.22; else if (kind === 'ncol') newsFrac = 0.38; else if (kind === 'orow') ordFrac = 0.28; else scanFrac = 0.50; applySizes(); save(); });
  }
  dragSplit($('vsplit'), 'col'); dragSplit($('hsplit'), 'row'); dragSplit($('osplit'), 'orow'); dragSplit($('nsplit'), 'ncol');
  window.addEventListener('resize', applySizes);
  applySizes();
  function setRecent(list){ $('recent').innerHTML = (list || []).map(s => `<option value="${esc(s)}">`).join(''); }

  const inp = $('sym');
  function submit(){
    const s = inp.value.trim().toUpperCase();
    if (!/^[A-Z0-9. ]{1,12}$/.test(s)) { toast({kind: 'warn', text: 'Enter a ticker symbol, e.g. XRPN'}); return; }
    inp.blur();
    api('load_symbol', s).then(r => { if (r && r.recent) setRecent(r.recent); });
  }
  inp.addEventListener('keydown', e => { if (e.key === 'Enter') submit(); else if (e.key === 'Escape') { inp.value = sym; inp.blur(); } });
  inp.addEventListener('focus', () => inp.select());
  document.addEventListener('keydown', e => {
    const ae = document.activeElement;
    if (ae === inp || (ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA'))) return;
    if (!$('keys-ov').classList.contains('hidden') || !$('stop-ov').classList.contains('hidden') || !$('close-ov').classList.contains('hidden')) return;
    if (hotkey(e)) { e.preventDefault(); return; }                      // 3.11
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (screen === 'chart' && /^[a-zA-Z]$/.test(e.key)) { inp.value = ''; inp.focus(); }
  });
  $('t-ext').addEventListener('change', e => { ext = e.target.checked; render(true); save(); });
  $('t-skip').addEventListener('change', () => { showSkip = false; });
  $('t-sound').addEventListener('change', e => { sound = e.target.checked; save(); });
  $('conn').addEventListener('click', () => api('reconnect'));
  // 3.10: the menu (kebab) and the panels drawer
  function menu(open){
    const m = $('menu'), on = open == null ? m.classList.contains('hidden') : open;
    m.classList.toggle('hidden', !on); $('menu-btn').classList.toggle('on', on);
    if (on) renderModes();
  }
  $('menu-btn').addEventListener('click', e => { e.stopPropagation(); menu(); });
  document.addEventListener('mousedown', e => {
    if (!$('menu').classList.contains('hidden') && !e.target.closest('#menu') && !e.target.closest('#menu-btn')) menu(false);
  });
  function drawer(p){
    const d = $('drawer');
    if (p) { d.classList.add('hidden'); openSettings(p); return; }
    if (!p) { d.classList.add('hidden'); return; }
    d.classList.remove('hidden');
    document.querySelectorAll('#drawer .dt').forEach(b => b.classList.toggle('on', b.dataset.dt === p));
    document.querySelectorAll('#drawer .dp').forEach(s => s.classList.toggle('on', s.id === 'dp-' + p));
  }
  $('menu').addEventListener('click', e => {
    const b = e.target.closest('[data-panel]'); if (!b) return;
    menu(false);
    if (b.dataset.panel === 'keys') $('tz-keys').click(); else if (b.dataset.panel === 'hotkeys') showScreen('keys'); else drawer(b.dataset.panel);
  });
  $('drawer').addEventListener('click', e => { const b = e.target.closest('[data-dt]'); if (b) drawer(b.dataset.dt); });
  $('d-x').addEventListener('click', () => drawer(null));
  document.addEventListener('keydown', e => { if (e.key === 'Escape') { menu(false); drawer(null); } });
  $('banner').addEventListener('click', () => { const b = $('banner'); goTo(Number(b.dataset.t)); b.className = 'hidden'; });
  // 3.15: STOP (top bar, the chart's stock): skip its short signals today / trade the next one again
  $('q-stop').addEventListener('click', () => {
    if (!sym) return;
    const on = !$('q-stop').classList.contains('on');
    if (bot) { const L = new Set(bot.sstops || []); on ? L.add(sym) : L.delete(sym); bot.sstops = [...L]; }
    qStopRender(); api('bot_short_stop', sym, on);
  });
  setInterval(qStopRender, 500);
