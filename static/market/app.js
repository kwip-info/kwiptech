'use strict';
(() => {
  const $ = s => document.querySelector(s);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money = c => new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(c/100);
  const number = n => Number(n).toLocaleString('en-US');
  const safeURL = s => {try {const u=new URL(s);return ['https:','http:'].includes(u.protocol)?u.href:'#';}catch{return '#';}};
  const notice = text => {const el=$('#notice');el.textContent=text;el.hidden=!text;};
  let identityReady;
  async function identity() {
    if (!identityReady) identityReady = (async()=>{
      for(let i=0;i<80;i++) {if(window.Clerk){await window.Clerk.load({ui:{ClerkUI:window.__internal_ClerkUICtor}});return window.Clerk;}await new Promise(r=>setTimeout(r,100));}
      return null;
    })();
    return identityReady;
  }
  async function api(path, options={}, auth=true) {
    const headers = {'Accept':'application/json',...options.headers};
    if(options.body) headers['Content-Type']='application/json';
    if(auth) {
      const clerk=await identity();
      const token=await clerk?.session?.getToken();
      if(!token) {const error=new Error('Sign in to continue.');error.code='authentication_required';throw error;}
      headers.Authorization='Bearer '+token;
    }
    const response=await fetch(path,{...options,headers,credentials:'same-origin'});
    let data;try{data=await response.json();}catch{throw new Error('The service could not complete the request. Please retry shortly.');}
    if(!response.ok){const error=new Error(data.error?.message || 'The request could not be completed.');error.code=data.error?.code;error.status=response.status;throw error;}
    return data;
  }
  async function action(button, fn) {button.disabled=true;notice('');try{await fn();}catch(e){notice(e.message);}finally{button.disabled=false;}}
  function table(headers, rows) {return `<div class="table-wrap" tabindex="0" role="region" aria-label="Scrollable data table"><table><thead><tr>${headers.map(h=>`<th scope="col">${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>'<tr>'+r.map(c=>'<td>'+c+'</td>').join('')+'</tr>').join('')}</tbody></table></div>`;}
  const screen=document.body.dataset.screen;
  document.querySelectorAll('.header nav a').forEach(a=>{if(new URL(a.href).pathname===location.pathname)a.setAttribute('aria-current','page');});

  async function catalog() {
    let after=null, collected=[];
    async function load(more=false) {
      const params=new URLSearchParams({q:$('#search').value});if(more&&after)params.set('after',after);
      const data=await api('/api/v2/datasets?'+params,{},false);
      collected=more?collected.concat(data.datasets):data.datasets;after=data.next_after;
      $('#catalog-more').hidden=!after;
      $('#catalog-results').innerHTML=collected.length?table(['Dataset','Topic','Cost','Updated'],collected.map(d=>[
        `<a href="/data/${encodeURIComponent(d.slug)}">${esc(d.title)}</a><p class="quiet">${esc(d.description.slice(0,150))}</p>`,
        `<span class="tag">${esc(d.category||'General')}</span>`,`${number(d.credits_per_record)} credit${d.credits_per_record===1?'':'s'} / record`,esc(new Date(d.updated_at).toLocaleDateString())])):
        `<div class="empty"><h3>${$('#search').value?'No matching datasets.':'The catalog is getting ready.'}</h3><p>${$('#search').value?'Try a broader topic or clear your search.':'No datasets have been published yet. You can explore the API and set up access while we prepare the first sources.'}</p><a href="/developers">Read the API guide →</a></div>`;
    }
    $('#search-form').addEventListener('submit',e=>{e.preventDefault();action(e.submitter,()=>load());});
    $('#catalog-more').onclick=e=>action(e.currentTarget,()=>load(true));await load();
  }

  async function dataset() {
    const slug=encodeURIComponent(document.body.dataset.dataset);
    const data=await api('/api/v2/datasets/'+slug,{},false);
    document.title=data.title+' | KWIP Data';$('#dataset-name').textContent=data.title;
    $('#dataset-header').innerHTML=`<p class="eyebrow">${esc(data.category||'DATASET')}</p><h1>${esc(data.title)}</h1><p class="intro">${esc(data.description)}</p>`;
    $('#query-price').textContent=`${number(data.credits_per_record)} credits per returned record. Source and revision details are included.`;
    $('#schema').innerHTML=table(['Field','Type','Required'],Object.entries(data.fields).map(([name,s])=>[esc(name),esc(s.type),s.required?'Yes':'No']));
    $('#sources').innerHTML=data.sources.map(s=>`<div class="panel"><h3><a href="${esc(safeURL(s.url))}" rel="noopener noreferrer">${esc(s.name)} ↗</a></h3><p>${esc(s.attribution)}</p><a href="${esc(safeURL(s.license_url))}" rel="noopener noreferrer">License & evidence ↗</a></div>`).join('');
    for(const [name,s] of Object.entries(data.fields)){const o=document.createElement('option');o.value=name;o.textContent=name+' ('+s.type+')';$('#filter-field').append(o);}
    let cursor=null,query=null,pending=null;
    const estimate=()=>{$('#query-estimate').textContent=`At most ${number(Number($('#page-size').value)*data.credits_per_record)} credits for this page. Only returned records count.`;};
    $('#page-size').onchange=estimate;estimate();
    $('#filter-field').onchange=()=>{$('#filter-value').disabled=!$('#filter-field').value;};
    function buildQuery(){const filters={}, field=$('#filter-field').value;if(field){const kind=data.fields[field].type;let value=$('#filter-value').value;if(['integer','number'].includes(kind)){value=Number(value);if(!Number.isFinite(value))throw new Error('Enter a numeric filter value.');}if(kind==='boolean'){if(!['true','false'].includes(value))throw new Error('Use true or false for a boolean filter.');value=value==='true';}filters[field]=value;}return {filters,limit:Number($('#page-size').value),max_credits:Number($('#page-size').value)*data.credits_per_record};}
    async function retrieve(next=false){
      if(!pending){if(!next){query=buildQuery();cursor=null;}pending={id:crypto.randomUUID(),body:JSON.stringify({...query,...(cursor?{cursor}: {})})};}
      let result;
      try {result=await api(`/api/v2/datasets/${slug}/query`,{method:'POST',headers:{'Idempotency-Key':pending.id},body:pending.body});}
      catch(e){if(e.status&&e.status<500&&e.status!==429){pending=null;$('#query-button').textContent='Retrieve records';$('#page-size').disabled=false;$('#filter-field').disabled=false;$('#filter-value').disabled=!$('#filter-field').value;throw e;}$('#query-button').textContent='Retry same request';$('#page-size').disabled=true;$('#filter-field').disabled=true;$('#filter-value').disabled=true;throw new Error(e.message+' Retry will reuse the same request and credit receipt.');}
      pending=null;$('#query-button').textContent='Retrieve records';$('#page-size').disabled=false;$('#filter-field').disabled=false;$('#filter-value').disabled=!$('#filter-field').value;cursor=result.next_cursor;
      const columns=Object.keys(data.fields);
      $('#records').innerHTML=result.records.length?table([...columns,'Evidence'],result.records.map(r=>[...columns.map(c=>esc(r.data[c]??'—')),`<a href="${esc(safeURL(r.source_url))}" rel="noopener noreferrer">${esc(r.source.name)} ↗</a><br><small>${esc(r.observed_at)}<br>Revision ${esc(r.revision)}</small>`])):'<div class="empty"><h3>No matching records.</h3><p>This query used no credits.</p></div>';
      $('#next-page').hidden=!cursor;notice(`${result.count} records retrieved · ${number(result.usage.credits)} credits · ${number(result.usage.remaining_credits)} included credits remaining.`);
    }
    $('#query-form').onsubmit=e=>{e.preventDefault();action(e.submitter,()=>retrieve());};$('#next-page').onclick=e=>action(e.currentTarget,()=>retrieve(true));
    // Export controls attach after account entitlements are loaded; no automatic queries.
    try {const usage=await api('/api/v2/billing/usage');$('#records').innerHTML='<div class="empty"><h3>Ready to retrieve.</h3><p>Choose filters and a page size, then retrieve records using your included allowance.</p></div>';if(usage.plan==='pro'){$('#export-records').hidden=false;$('#export-records').onclick=e=>action(e.currentTarget,()=>startExport(slug,buildQuery().filters));}}catch(e){if(e.code!=='authentication_required')notice(e.message);}
  }

  async function plans(){const p=await api('/api/v2/plans',{},false);$('#plans').innerHTML=`<section class="panel"><p class="eyebrow">Free</p><h2>${money(0)} <small>/ month</small></h2><p>${number(p.free_credits)} included credits each month</p><p>API access, source evidence, and scoped agent keys.</p><a class="button" href="/account/sign-in">Create your account</a></section><section class="panel"><p class="eyebrow">Pro</p><h2>${money(p.pro_monthly_cents)} <small>/ month</small></h2><p>${number(p.pro_credits)} included credits each month</p><p>Dataset exports and optional overage at ${money(p.overage_cents_per_10000)} per 10,000 credits.</p>${p.purchases_available?'<a class="button" href="/account">Choose Pro</a>':'<p class="tag">Proposed pricing · purchases open when data is available</p>'}</section>`;}

  async function account(){const clerk=await identity();if(!clerk?.user){$('#account-content').innerHTML='<div class="empty"><h2>Your data access starts here.</h2><p>Sign in to create keys and use your free allowance.</p><a class="button" href="/account/sign-in">Sign in</a></div>';return;}
    const [me,u,p]=await Promise.all([api('/api/v2/account'),api('/api/v2/billing/usage'),api('/api/v2/plans',{},false)]);
    $('#account-content').innerHTML=`<div class="stats"><section class="panel"><p class="eyebrow">Plan</p><div class="stat">${esc(u.plan==='pro'?'Pro':'Free')}</div><p class="quiet">${number(u.included_credits)} included credits</p></section><section class="panel"><p class="eyebrow">Credits used</p><div class="stat">${number(u.used_credits)}</div><p class="quiet">Resets ${esc(new Date(u.period_end).toLocaleDateString())}</p></section><section class="panel"><p class="eyebrow">Paid overage</p><div class="stat">${money(u.estimated_overage_cents)}</div><p class="quiet">${u.overage_enabled?'Cap: '+money(u.spend_cap_cents):'Off — no automatic extra charges'}</p></section></div><div class="inline">${u.billing_account_exists?'<button id="manage-billing">Manage billing</button>':''}${u.plan!=='pro'&&p.purchases_available?'<button id="upgrade">Upgrade to Pro</button>':u.plan!=='pro'?'<p class="quiet">Pro purchases open when the catalog has data.</p>':''}<button id="sign-out">Sign out</button></div>${u.plan==='pro'?`<section class="panel"><h2>Overage spending</h2><form id="overage-form"><label for="spend-cap">Monthly overage cap (USD)</label><div class="inline"><input id="spend-cap" type="number" min="0" max="1000" step="1" value="${u.spend_cap_cents/100}"><button type="submit">${u.overage_enabled?'Update cap':'Enable with this cap'}</button><button type="button" id="disable-overage">Keep overage off</button></div><p class="quiet">Setting a positive cap and saving authorizes metered charges up to that amount. Set zero to disable overage.</p></form></section>`:''}${me.operator?'<p class="quiet">Publisher access enabled. <a href="/account/jobs-poc">Review the jobs POC →</a></p>':''}`;
    $('#keys-panel').hidden=false;
    if($('#manage-billing'))$('#manage-billing').onclick=e=>action(e.currentTarget,async()=>{location.href=(await api('/api/v2/billing/portal',{method:'POST'})).url;});
    if($('#upgrade'))$('#upgrade').onclick=e=>action(e.currentTarget,async()=>{location.href=(await api('/api/v2/billing/checkout',{method:'POST'})).url;});
    $('#sign-out').onclick=()=>clerk.signOut({redirectUrl:'/'});
    if($('#overage-form')){$('#overage-form').onsubmit=e=>{e.preventDefault();action(e.submitter,async()=>{const cap=Math.round(Number($('#spend-cap').value)*100);await api('/api/v2/billing/overage',{method:'POST',body:JSON.stringify({enabled:cap>0,spend_cap_cents:cap})});await account();notice('Spending preferences saved.');});};$('#disable-overage').onclick=e=>action(e.currentTarget,async()=>{await api('/api/v2/billing/overage',{method:'POST',body:JSON.stringify({enabled:false,spend_cap_cents:0})});await account();});}
    async function listKeys(){const result=await api('/api/v2/keys');$('#keys-list').innerHTML=table(['Key','Access','Expires',''],result.keys.map(k=>[esc(k.name)+'<br><code>'+esc(k.prefix)+'…</code>',esc(k.scopes.join(', ')),esc(new Date(k.expires_at).toLocaleDateString()),k.revoked?'Revoked':`<button data-revoke="${esc(k.id)}" class="revoke">Revoke</button>`]));document.querySelectorAll('[data-revoke]').forEach(b=>b.onclick=()=>action(b,async()=>{await api('/api/v2/keys/'+b.dataset.revoke,{method:'DELETE'});await listKeys();}));}
    $('#key-form').onsubmit=e=>{e.preventDefault();action(e.submitter,async()=>{const result=await api('/api/v2/keys',{method:'POST',body:JSON.stringify({name:$('#key-name').value,days:Number($('#key-days').value),scopes:['datasets:read','exports:read']})});$('#new-key').hidden=false;$('#new-key').innerHTML=`<div class="key-secret"><strong>Copy your key now. It is shown only once.</strong><p><code>${esc(result.token)}</code></p><button id="copy-key">Copy key</button><button id="dismiss-key">Hide key</button></div>`;$('#copy-key').onclick=async()=>{try{await navigator.clipboard.writeText(result.token);notice('Key copied. Store it securely.');}catch{notice('Copy the displayed key manually.');}};$('#dismiss-key').onclick=()=>{$('#new-key').textContent='';$('#new-key').hidden=true;};$('#key-name').value='';await listKeys();});};await listKeys();if(u.plan==='pro')await listExports();
  }

  async function connect(){ $('#connect-form').onsubmit=e=>{e.preventDefault();action(e.submitter,async()=>{const code=$('#user-code').value;const grant=await api('/api/v2/device/approve?'+new URLSearchParams({user_code:code}));$('#connection-review').innerHTML=`<section class="panel"><h2>${esc(grant.name)}</h2><p>Requested access: <strong>${esc(grant.scopes.join(', '))}</strong></p><p>${esc(grant.notice)}</p><div class="inline"><button id="approve-agent">Approve connection</button><button id="deny-agent">Deny</button></div></section>`;for(const [id,decision] of [['approve-agent','approve'],['deny-agent','deny']])$('#'+id).onclick=e=>action(e.currentTarget,async()=>{await api('/api/v2/device/approve',{method:'POST',body:JSON.stringify({user_code:code,decision})});$('#connection-review').innerHTML=`<div class="panel"><h2>Connection ${decision==='approve'?'approved':'denied'}.</h2><p>${decision==='approve'?'Return to your agent to finish connecting. You can revoke its key from your account.':'No access was granted.'}</p><a href="/account">Back to account →</a></div>`;});});}; }
  async function signin(){const clerk=await identity();if(!clerk){$('#sign-in').innerHTML='<div class="panel"><p>Sign-in is temporarily unavailable. Please try again later.</p><a href="/">Back to datasets →</a></div>';return;}if(clerk.user){location.href='/account';return;}clerk.mountSignIn($('#sign-in'),{forceRedirectUrl:'/account',signUpForceRedirectUrl:'/account'});}
  async function startExport(slug,filters){
    const panel=$('#export-panel');panel.hidden=false;
    panel.innerHTML=`<h3>Prepare an export</h3><p>Export matching records from a consistent snapshot. Credits are charged as pages are prepared; downloading a prepared file is free. Files expire after 24 hours.</p><form id="export-form"><div class="inline"><div><label for="export-format">File format</label><select id="export-format"><option value="jsonl">JSON Lines</option><option value="csv">CSV</option></select></div><div><label for="export-budget">Maximum credits</label><input id="export-budget" type="number" min="1" max="1000000" required value="1000"></div><button type="submit">Prepare export</button></div><p class="quiet">Up to 10,000 records or 10 MB per export. If a limit is reached, the file contains only the prepared portion, clearly marked partial.</p></form>`;
    let pendingExport=null;
    $('#export-form').onsubmit=e=>{e.preventDefault();action(e.submitter,async()=>{if(!pendingExport)pendingExport={id:crypto.randomUUID(),body:JSON.stringify({dataset:decodeURIComponent(slug),filters,format:$('#export-format').value,max_credits:Number($('#export-budget').value)})};const result=await api('/api/v2/exports',{method:'POST',headers:{'Idempotency-Key':pendingExport.id},body:pendingExport.body});pendingExport=null;panel.innerHTML=`<h3>Export queued</h3><p>Your export is being prepared. Review progress and download it from your account.</p><a class="button" href="/account#exports-panel">View exports →</a>`;notice('Export queued: '+result.id);});};panel.scrollIntoView({behavior:'smooth',block:'center'});
  }
  async function listExports(){
    const panel=$('#exports-panel');panel.hidden=false;
    const result=await api('/api/v2/exports');
    $('#exports-list').innerHTML=result.exports.length?table(['Dataset','Progress','Credits','Available until',''],result.exports.map(j=>[esc(j.dataset),esc(j.status)+'<br>'+number(j.rows)+' records'+(j.error_code?'<br><small>'+esc(({export_cap_reached:'Stopped at the export limit or your credit budget',source_unavailable:'Source access changed',budget_exceeded:'Credit budget reached'})[j.error_code]||'Preparation stopped; contact support with the export ID')+'</small>':''),number(j.credits)+' / '+number(j.max_credits),esc(new Date(j.expires_at).toLocaleString()),j.download_ready?`<button data-download="${esc(j.id)}" data-format="${esc(j.format)}">Download ${esc(j.format.toUpperCase())}</button>`:'Preparing…'])):'<p class="quiet">No exports yet. Open a dataset to prepare one.</p>';
    $('#refresh-exports').onclick=e=>action(e.currentTarget,listExports);
    document.querySelectorAll('[data-download]').forEach(b=>b.onclick=()=>action(b,async()=>{const clerk=await identity();const token=await clerk.session.getToken();const response=await fetch('/api/v2/exports/'+b.dataset.download+'/download',{headers:{Authorization:'Bearer '+token}});if(!response.ok){const data=await response.json();throw new Error(data.error?.message||'Download unavailable.');}const blob=await response.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='kwip-export-'+b.dataset.download+'.'+b.dataset.format;a.click();notice('Download prepared. Your credit usage has not changed.');setTimeout(()=>URL.revokeObjectURL(url),1000);}));
  }
  async function jobs_poc(){
    const root=$('#jobs-poc-content');
    let result;
    try {result=await api('/api/v2/operator/jobs-poc');}
    catch(e){root.innerHTML='<div class="empty"><h2>Operator access required.</h2><p>'+esc(e.message)+'</p><a href="/account">Back to account →</a></div>';return;}
    $('#jobs-auth-hint').hidden=true;
    const rows=result.records, summary=result.summary||{records:0,companies:0,with_pay:0};
    root.innerHTML=`<p class="tag">${esc(result.notice)}</p><div class="stats"><section class="panel"><p class="eyebrow">Sample records</p><div class="stat">${number(summary.records)}</div></section><section class="panel"><p class="eyebrow">Companies</p><div class="stat">${number(summary.companies)}</div></section><section class="panel"><p class="eyebrow">With stated pay</p><div class="stat">${number(summary.with_pay)}</div></section></div>
      <section class="panel"><h2>Standardized postings</h2><p>Remote roles explicitly listing US eligibility. This is not a representative US market sample. Missing listings do not indicate closure.</p><label for="jobs-filter">Find a title or company in this sample</label><input id="jobs-filter" type="search" placeholder="Title or company" maxlength="100"><div class="inline"><div><label for="jobs-page-size">Records per page</label><select id="jobs-page-size"><option value="5">5</option><option value="10">10</option><option value="20">20</option></select></div></div><div id="jobs-rows"></div><nav class="inline" aria-label="Job pages"><button id="jobs-prev" type="button">Previous</button><span id="jobs-page-status" role="status"></span><button id="jobs-next" type="button">Next</button></nav><section id="job-details" class="panel" tabindex="-1" aria-label="Selected job details" hidden></section></section>
      <section class="panel"><h2>Sources & update plan</h2><p>Refreshes are manual and limited to once per 24 hours. Next permitted collection: ${result.next_allowed_at?esc(new Date(result.next_allowed_at).toLocaleString()):'Not collected yet'}.</p><p>Source discovery review: ${esc(result.discovery.next_review_on)} · every ${esc(result.discovery.cadence_days)} days. New sources require review before collection.</p>
      ${table(['Source','Status','Attribution or next step'],result.sources.map(s=>[`<a href="${esc(safeURL(s.attribution_url||s.url))}" rel="noopener noreferrer">${esc(s.name)} ↗</a>`,esc(s.status),esc(s.attribution||s.blocker)]))}</section>
      <section class="panel"><h2>Collection receipts</h2>${result.runs.length?table(['Attempt','Result','Accepted / examined','Upstream requests'],result.runs.map(r=>[esc(new Date(r.started_at).toLocaleString()),esc(r.status)+(r.summary.error?'<br>'+esc(r.summary.error):''),`${number(r.summary.accepted||0)} / ${number(r.summary.examined||0)}`,`${number(r.summary.data_requests||0)} data · ${number(r.summary.robots_requests||0)} robots`])):'<p>No collection attempts yet.</p>'}</section>`;
    const salary=d=>{if(!d.salary_currency)return 'Not supplied with currency and period';const amount=d.salary_min!==undefined&&d.salary_max!==undefined?number(d.salary_min)+'–'+number(d.salary_max):d.salary_min!==undefined?'from '+number(d.salary_min):'up to '+number(d.salary_max);return esc(d.salary_currency+' '+amount+' / '+d.salary_period);};
    const dateText=value=>value?new Date(value).toLocaleString():'Not supplied';
    let page=0;
    function showDetails(row,button){
      const d=row.data,panel=$('#job-details');
      panel.hidden=false;
      panel.innerHTML=`<div class="section-heading"><h2>${esc(d.title)}</h2><button id="job-details-close" type="button">Close details</button></div><p>${esc(d.company)} · ${esc(d.employment_type||'Employment type not supplied')}</p>
        <dl class="job-facts"><dt>Published by source</dt><dd>${esc(dateText(d.published_at))}</dd><dt>Source expiry</dt><dd>${esc(dateText(d.expires_at))}</dd><dt>Observed by KWIP</dt><dd>${esc(dateText(row.observed_at))}</dd><dt>Location eligibility</dt><dd>${esc(d.location_restrictions)}</dd><dt>Time zone restrictions</dt><dd>${esc(d.timezone_restrictions||'Not supplied')}</dd><dt>Stated compensation</dt><dd>${salary(d)}</dd></dl>
        <h3>Description</h3>${d.description?`<p class="job-description">${esc(d.description)}</p>${d.description_truncated?'<p class="quiet">Description shortened to 20,000 characters. Read the original for the full text.</p>':''}`:`<p class="quiet">${d.normalization_version<2?'Descriptions were not retained in the initial sample. They can appear after the next permitted refresh.':'The source did not supply a usable description.'}</p>`}
        <p><a href="${esc(safeURL(row.source_url))}" rel="noopener noreferrer">Read the original listing on ${esc(row.source.name)} ↗</a></p><p class="quiet">${esc(row.source.attribution)}</p><p class="quiet">Source expiry does not prove the role was filled. Dates reflect the source and our observation, not a verified hiring outcome.</p>`;
      $('#job-details-close').onclick=()=>{panel.hidden=true;button.focus();};
      panel.focus({preventScroll:true});panel.scrollIntoView({behavior:'smooth',block:'start'});
    }
    function render(){
      const q=$('#jobs-filter').value.toLowerCase(),size=Number($('#jobs-page-size').value);
      const filtered=rows.filter(r=>(r.data.title+' '+r.data.company).toLowerCase().includes(q));
      const pages=Math.max(1,Math.ceil(filtered.length/size));page=Math.min(page,pages-1);
      const visible=filtered.slice(page*size,(page+1)*size);
      $('#job-details').hidden=true;
      $('#jobs-rows').innerHTML=visible.length?table(['Role & company','Eligibility','Stated pay','Dates & source'],visible.map((r,i)=>[
        `<strong>${esc(r.data.title)}</strong><br>${esc(r.data.company)}<br><small>${esc(r.data.employment_type||'')}</small><br><button type="button" class="job-detail-button" data-job-index="${i}" aria-label="View details: ${esc(r.data.title)}">View details</button>`,
        esc(r.data.location_restrictions),salary(r.data),
        `<small>Published ${esc(dateText(r.data.published_at))}<br>Observed ${esc(dateText(r.observed_at))}</small><br><a href="${esc(safeURL(r.source_url))}" rel="noopener noreferrer">${esc(r.source.name)} original listing ↗</a>`])):
        '<div class="empty"><h3>'+(rows.length?'No matching postings.':'No sample available yet.')+'</h3><p>'+(rows.length?'Try another title or company.':'A collection may be pending, expired or awaiting source review.')+'</p></div>';
      $('#jobs-page-status').textContent=filtered.length?`Page ${page+1} of ${pages} · ${page*size+1}–${page*size+visible.length} of ${filtered.length}`:'0 records';
      $('#jobs-prev').disabled=page===0;$('#jobs-next').disabled=page>=pages-1;
      document.querySelectorAll('[data-job-index]').forEach(button=>{button.onclick=()=>showDetails(visible[Number(button.dataset.jobIndex)],button);});
    }
    $('#jobs-filter').oninput=()=>{page=0;render();};
    $('#jobs-page-size').onchange=()=>{page=0;render();};
    $('#jobs-prev').onclick=()=>{page--;render();};$('#jobs-next').onclick=()=>{page++;render();};render();
  }
  const run={catalog,dataset,plans,account,connect,signin,jobs_poc}[screen];if(run)run().catch(e=>notice(e.message));
})();
