import { Ride } from './engine.mjs';
const $ = id => document.getElementById(id);
let items = [], ride, history = [], position = -1, active = false, busy = false, idleTimer, generation = 0;
const imageCache = new Map();
function node(tag, className, text) { const el = document.createElement(tag); if (className) el.className = className; if (text) el.textContent = text; return el; }
function link(text, url) { const el = node('a', '', text); if (/^https:\/\//.test(url || '')) el.href = url; el.target = '_blank'; el.rel = 'noopener noreferrer'; return el; }
function warm(url) {
  if (!imageCache.has(url)) {
    const promise = new Promise(resolve => { const img = new Image(); let timer = setTimeout(() => resolve(false), 7000); img.onload = () => { clearTimeout(timer); resolve(true); }; img.onerror = () => { clearTimeout(timer); resolve(false); }; img.src = url; });
    imageCache.set(url, promise); if (imageCache.size > 30) imageCache.delete(imageCache.keys().next().value);
  }
  return imageCache.get(url);
}
let upcoming = [];
function fill() { while (upcoming.length < 4) { const slide = ride.next(); upcoming.push(slide); if (slide.item.image) warm(slide.item.image); } }
function render(slide) {
  const { item, palette, layout, style } = slide;
  const el = node('article', `slide ${item.kind} ${palette} layout-${layout} style-${style || "studio"}`);
  el.append(node('div','slide-eyebrow', item.kind === 'image' ? item.generated ? 'Imagined by KWIP / AI-generated illustration' : item.topic + ' / an unexpected exhibit' : item.kind === 'chart' ? 'A hypothetical situation / illustrative data' : 'An invitation to improvise'));
  const body = node('div','body'); const heading = node('h2','',item.title);
  if (item.kind === 'image') {
    const words = node('div'); words.append(heading); if(item.subtitle) words.append(node('p','subtitle',item.subtitle));
    const frame = node('div','image-frame'), img = node('img'); img.src = item.image; img.alt = item.title; img.onerror = () => { frame.replaceChildren(node('p','subtitle','Image unavailable. Keep going →')); }; frame.append(img); body.append(words,frame);
  } else if (item.kind === 'chart') {
    body.append(heading); const chart = node('div','chart-plot'); chart.setAttribute('role','img'); chart.setAttribute('aria-label',item.labels.map((x,i)=>`${x}: ${item.values[i]}%`).join(', '));
    item.values.forEach((value, i) => { const col = node('div','chart-column'); col.append(node('span','',`${value}%`)); const bar = node('div','chart-bar'); bar.style.setProperty('--height',`${value * .82}%`); col.append(bar,node('span','',item.labels[i])); chart.append(col); }); body.append(chart);
  } else { body.append(heading); if(item.subtitle) body.append(node('p','subtitle',item.subtitle)); }
  el.append(body);
  const credit = node('div','credit-line'), main = node('span','credit-main');
  if(item.kind === 'image') { main.append(link(`${item.title} · ${item.creator} · ${item.provider}`, item.source), document.createTextNode(' · '),link(item.license,item.license_url)); }
  else main.textContent = item.kind === 'chart' ? 'KWIP original · Invented numbers for improvisation. Not research.' : 'KWIP original · Improvisation prompt, not a factual assertion.';
  credit.append(main,node('span','',`KWIP / ${String(position+1).padStart(3,'0')}`)); el.append(credit); $('stage').replaceChildren(el); $('counter').textContent=String(position+1).padStart(3,'0'); $('previous').disabled=position===0; requestAnimationFrame(fitSlide);
}
function fitSlide() {
  const title = $('stage').querySelector('h2'), body = $('stage').querySelector('.body');
  if (!title || !body) return;
  title.style.fontSize = '';
  let size = parseFloat(getComputedStyle(title).fontSize);
  for (let step=0; step<25 && (body.scrollHeight > body.clientHeight + 2 || title.scrollWidth > title.clientWidth + 2); step++) { size *= .94; title.style.fontSize = `${size}px`; }
}
new ResizeObserver(fitSlide).observe($('stage'));
async function advance() {
  if(busy || !active || $('sources').open) return; busy = true; const token = generation;
  try {
    if(position < history.length-1) { position++; render(history[position]); return; }
    if(history.length >= 5000) { $('player-status').textContent='5,000 slides! Finish and start a fresh ride to keep going.'; return; }
    fill(); let slide;
    for(let tries=0;tries<8;tries++) { slide=upcoming.shift(); fill(); if(!slide.item.image) break; $('player-status').textContent='Preparing the next slide…'; if(await warm(slide.item.image)) break; slide=null; }
    if(token !== generation || !active) return;
    if(!slide) { $('player-status').textContent='Image sources are unavailable. Try Next again, or start a mixed ride.'; return; }
    history.push(slide); position++; render(slide); $('player-status').textContent='';
  } finally { if(token === generation) busy=false; }
}
function controls() { $('toolbar').classList.remove('idle'); clearTimeout(idleTimer); idleTimer=setTimeout(()=>{ if(active && !$('sources').open) $('toolbar').classList.add('idle'); },2600); }
async function start() { generation++; busy=false; ride=new Ride(items,{mode:$('mode').value,palette:$('palette').value,style:$('style').value,world:$('world').value}); history=[];position=-1;upcoming=[];active=true;$('stage').replaceChildren();$('lobby').hidden=true;$('player').hidden=false;$('start').blur();await advance(); controls(); }
async function fullscreen() { try { if(document.fullscreenElement) await document.exitFullscreen(); else await $('player').requestFullscreen(); } catch { $('player-status').textContent='Fullscreen is unavailable here. The presentation still works in this window.'; } }
function showSources() {
  controls(); const item=history[position]?.item; const box=$('current-source'); box.replaceChildren();
  if(item) { box.append(node('h3','',item.title)); if(item.kind==='image') { box.append(node('p','',`${item.creator} · ${item.provider}`),link('Original source ↗',item.source),document.createTextNode(' · '),link(item.license,item.license_url)); if(item.credit) box.append(node('p','',item.credit)); box.append(node('p','quiet',item.changes)); } else box.append(node('p','',item.kind==='chart'?'Illustrative, invented data. KWIP original.':'Original KWIP improvisation prompt.')); }
  $('sources').showModal();
}
function download(asJson = false) {
  const record={product:'KWIP',created_at:new Date().toISOString(),seed:ride?.seed,mode:ride?.mode,palette:ride?.palette,style:ride?.style,world:ride?.world,slides:history.map((slide,i)=>({number:i+1,...slide}))};
  const credits = ['KWIP presentation credits', record.created_at, '', ...record.slides.flatMap(slide => { const item=slide.item; return [`Slide ${slide.number}: ${item.title}`, `${item.creator} · ${item.provider}`, item.kind === 'image' ? `${item.license}: ${item.license_url}` : 'Original improvisation material; charts contain invented numbers.', item.source, item.credit || '', item.changes || '', '']; })].join('\n');
  const blob=new Blob([asJson ? JSON.stringify(record,null,2) : credits],{type:asJson ? 'application/json' : 'text/plain'});const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=asJson ? 'kwip-session.json' : 'kwip-credits.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
$('start').onclick=start;$('next').onclick=advance;$('previous').onclick=()=>{if(!busy&&position>0){position--;render(history[position]);}};$('fullscreen').onclick=fullscreen;$('credits').onclick=showSources;$('download').onclick=()=>download();$('download-json').onclick=()=>download(true);$('close-sources').onclick=()=>$('sources').close();
$('exit').onclick=async()=>{active=false;generation++;busy=false;if(document.fullscreenElement) await document.exitFullscreen().catch(()=>{});showSources();$('player').hidden=true;$('lobby').hidden=false;$('start').textContent='Present again ↗';};
document.addEventListener('keydown',e=>{ if(!active||$('sources').open||e.altKey||e.ctrlKey||e.metaKey) return; if(['SELECT','INPUT','TEXTAREA'].includes(e.target.tagName))return; if(e.target.tagName==='BUTTON' && [' ','Enter'].includes(e.key))return; if(['ArrowRight','PageDown',' ','Enter'].includes(e.key)){e.preventDefault();advance();}else if(['ArrowLeft','PageUp','Backspace'].includes(e.key)){e.preventDefault();$('previous').click();}else if(e.key.toLowerCase()==='f'){fullscreen();}else if(e.key.toLowerCase()==='s'){showSources();}controls();});
$('player').addEventListener('pointermove',controls);$('player').addEventListener('pointerdown',controls);$('sources').addEventListener('close',controls);
try { const response=await fetch('/api/slides/catalog', {cache:'no-cache'});if(!response.ok)throw new Error('catalog');const catalog=await response.json();items=catalog.items;if(!items.length)throw new Error('empty');$('start').disabled=false;$('start').textContent='Start presenting ↗';$('load-status').textContent=`${items.length} starting points. Endlessly reshuffled. ← → or your clicker to advance.`; }catch{$('load-status').textContent='The slides couldn’t load. Refresh to try again.';$('start').textContent='Slides unavailable';}
