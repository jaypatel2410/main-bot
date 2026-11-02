(function(){
'use strict';
const $ = id => document.getElementById(id);
let impl = null;
const queue = [];
window.App = new Proxy({}, {get(_, name){ return (...args) => {
  if (impl) { if (impl[name]) { try { return impl[name](...args); } catch (e) { console.error('App.' + String(name), e); } } }
  else queue.push([name, args]);
}; }});
window.__bootChart = function(){
  if (impl || !window.LightweightCharts) return;
  impl = createApp();
  for (const [n, a] of queue.splice(0)) { try { impl[n] && impl[n](...a); } catch (e) { console.error(e); } }
};
function api(name, ...args){
  const p = window.pywebview && window.pywebview.api;
  return p && p[name] ? p[name](...args) : Promise.resolve(null);
}
function whenApi(fn){
  if (window.pywebview && window.pywebview.api && window.pywebview.api.get_init) fn();
  else window.addEventListener('pywebviewready', fn, {once: true});
}
whenApi(() => api('get_init').then(cfg => cfg && App.init(cfg)));
setTimeout(() => { if (!impl) { const e = $('empty'); e.classList.remove('hidden');
  e.querySelector('.big').textContent = 'Chart library could not be loaded';
  e.querySelector('.sub').innerHTML = 'Connect this PC to the internet and restart the app once - the chart library is downloaded a single time and then cached.'; } }, 15000);

