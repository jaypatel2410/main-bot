  // ---- 3.12.1: favorites ----
  let favs = [];
  const isFav = s => favs.some(f => f.sym === s);
  function favPaint(){ const on = !!sym && isFav(sym); $('q-fav').classList.toggle('on', on);
    $('q-fav').title = on ? 'Remove from favorites' : 'Add to favorites'; }
  function favToggle(s){
    if (!s) return;
    const on = !isFav(s);
    api('fav_set', s, on).then(r => { if (r && r.ok) { favs = r.favs; favPaint(); renderFav(); if (screen === 'scan') renderScan();
      toast({kind: 'info', text: on ? `${s} added to Favorites` : `${s} removed from Favorites`}); } });
  }
  function renderFav(){
    $('fv-meta').textContent = favs.length ? `${favs.length}` : '';
    if (screen !== 'fav') return;
    const lastOf = s => { if (s === sym) return lastPx; const rw = ((bot && bot.rows) || []).find(x => x.sym === s); return rw ? rw.last : null; };
    $('fv-list').innerHTML = favs.length ? favs.map((f, i) => `<div class="fvrow fvgrid" data-fo="${esc(f.sym)}"><span class="o-t">${i + 1}</span>` +
      `<span class="s">${esc(f.sym)}</span><span class="r" style="text-align:right">${fmtPx(lastOf(f.sym))}</span><span class="o-t">${esc(f.t || '')}</span>` +
      `<button class="sbtn" data-fw="${esc(f.sym)}">+ Watch</button><button class="sbtn danger" data-fx="${esc(f.sym)}">Remove</button></div>`).join('')
      : '<div class="oempty">No favorites</div>';
  }
  $('q-fav').addEventListener('click', () => favToggle(sym));
  $('fv-add').addEventListener('click', () => { const s = ($('fv-in').value || '').trim().toUpperCase();
    if (!/^[A-Z0-9. ]{1,12}$/.test(s)) { toast({kind: 'warn', text: 'Type a ticker'}); return; }
    $('fv-in').value = ''; if (!isFav(s)) favToggle(s); });
  $('fv-in').addEventListener('keydown', e => { if (e.key === 'Enter') $('fv-add').click(); });
  $('fv-list').addEventListener('click', e => {
    const x = e.target.closest('[data-fx]'); if (x) { favToggle(x.dataset.fx); return; }
    const w = e.target.closest('[data-fw]'); if (w) { api('bot_add', w.dataset.fw); toast({kind: 'info', text: `${w.dataset.fw} added to the watchlist`}); return; }
    const o = e.target.closest('[data-fo]');
    if (o) { api('load_symbol', o.dataset.fo).then(res => { if (res && res.recent) setRecent(res.recent); }); showScreen('chart'); }
  });
  whenApi(() => api('fav_list').then(r => { if (r && r.ok) { favs = r.favs || []; favPaint(); } }));
  setInterval(favPaint, 1000);

