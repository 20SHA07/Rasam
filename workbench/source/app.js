'use strict';
(() => {
  // Readers run through the local server. Samples and manual entry stay offline.
  const $ = id => document.getElementById(id);
  const paths = {
    inbox: '<path d="M4 4h16l2 12v4H2v-4L4 4Z"/><path d="M2 15h6l2 3h4l2-3h6"/>',
    book: '<path d="M4 3h13a3 3 0 0 1 3 3v15H6a3 3 0 0 1-3-3V5a2 2 0 0 1 1-2Z"/><path d="M3 17h17M7 7h9M7 10h6"/>',
    leaf: '<path d="M20 3c-7 0-15 2-15 9a6 6 0 0 0 6 6c7 0 9-8 9-15Z"/><path d="M3 21 15 9m-9 9v-6m5 1h6"/>',
    sparkles: '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3ZM20 2v4m-2-2h4"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v.1"/>',
    upload: '<path d="M12 16V3m-5 5 5-5 5 5M4 15v5h16v-5"/>',
    download: '<path d="M12 3v13m-5-5 5 5 5-5M4 15v5h16v-5"/>',
    lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3m-4 5v2"/>',
    file: '<path d="M5 3h9l5 5v13H5V3Z"/><path d="M14 3v5h5M8 12h8M8 16h5"/>',
    trash: '<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7"/>',
    pencil: '<path d="m15 4 5 5-11 11-6 1 1-6L15 4Zm-9 10 5 5M13 6l5 5"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    sheet: '<path d="M5 3h10l4 4v14H5V3Z"/><path d="M15 3v5h4M8 11h8M8 15h8M12 11v8M8 19h8"/>',
    close: '<path d="m6 6 12 12M18 6 6 18"/>',
    alert: '<path d="m12 3 10 18H2L12 3Z"/><path d="M12 9v5m0 3v.1"/>'
  };
  const icon = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.file}</svg>`;
  function icons(root = document) { root.querySelectorAll('[data-icon]').forEach(el => { el.innerHTML = icon(el.dataset.icon); }); }
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const format = value => Number(value).toLocaleString('en-GB', {minimumFractionDigits:2,maximumFractionDigits:2});
  const fields = ['supplier', 'invoiceNumber', 'date', 'currency', 'net', 'vat', 'total', 'notes'];
  const samples = [
    {supplier:'Al Noor Stationery LLC',arabic:'مكتبة النور',invoiceNumber:'INV-2026-0481',date:'2026-08-12',currency:'SAR',net:'1950.00',vat:'292.50',total:'2242.50',sourceFile:'al-noor-example',city:'Riyadh',items:[['A4 copy paper · 20 boxes','1,400.00'],['Office stationery set','550.00']]},
    {supplier:'Desert Print Studio',arabic:'استوديو الطباعة',invoiceNumber:'DPS-00286',date:'2026-08-14',currency:'AED',net:'640.00',vat:'32.00',total:'672.00',sourceFile:'desert-print-example',city:'Dubai',items:[['Business cards · 500 pcs','240.00'],['Brochure printing','400.00']]},
    {supplier:'مكتبة الصفحات',arabic:'مكتبة الصفحات',invoiceNumber:'PG-00172',date:'2026-08-15',currency:'SAR',net:'800.00',vat:'120.00',total:'920.00',sourceFile:'arabic-stationery-example',city:'Riyadh',items:[['ورق طباعة · Printing paper','500.00'],['أدوات مكتبية · Stationery','300.00']]}
  ];
  let nextID = 1, sampleIndex = 0, currentID = null, filter = 'all', toastTimer;
  const invoices = [];
  const aiFields = ['supplier','invoiceNumber','date','currency','net','vat','total'];
  const fieldNames = {supplier:'Supplier',invoiceNumber:'Invoice number',date:'Invoice date',currency:'Currency',net:'Net amount',vat:'Tax amount',total:'Invoice total'};
  let aiConnection = {configured:false, localServer:false};
  let pendingRemoveID = null;
  const current = () => invoices.find(item => item.id === currentID);
  const approved = () => invoices.filter(item => item.approved);
  function tell(message, error = false) {
    clearTimeout(toastTimer); $('toast').textContent = message; $('toast').classList.toggle('error', error); $('toast').hidden = false;
    toastTimer = setTimeout(() => { $('toast').hidden = true; }, error ? 7000 : 4200);
  }
  function addSample(silent = false) {
    const sample = samples[sampleIndex++ % samples.length];
    const existing = invoices.find(item => item.mode === 'sample' && item.sample.invoiceNumber === sample.invoiceNumber);
    if (existing) { currentID = existing.id; filter = 'all'; render(); if (!silent) tell('This example is already in your inbox.'); return; }
    const record = {...sample, id: 'RAS-' + String(nextID++).padStart(4,'0'), mode:'sample', approved:false, confirmed:false, reviewedAt:'', notes:'', sample:{...sample}};
    invoices.push(record); currentID = record.id; filter = 'all'; render();
    if (!silent) tell('Sample invoice added. Its details are fictional.');
  }
  const shownInvoices = () => invoices.filter(item => filter === 'all' || (filter === 'approved' ? item.approved : !item.approved));
  function renderList() {
    const selected = current();
    if (selected && ((filter === 'review' && selected.approved) || (filter === 'approved' && !selected.approved))) filter = 'all';
    $('inbox-count').textContent = invoices.length;
    document.querySelectorAll('[data-filter]').forEach(el => el.setAttribute('aria-pressed', String(el.dataset.filter === filter)));
    const shown = shownInvoices();
    $('invoice-list').innerHTML = shown.length ? shown.map(item => `<button class="invoice-item" data-id="${escape(item.id)}" aria-pressed="${item.id === currentID}" aria-label="Select ${escape(item.supplier || item.sourceFile)}">
      <span class="invoice-item-head"><span class="file-tile">${icon('file')}</span><span><span class="invoice-item-name" dir="auto">${escape(item.supplier || 'Enter invoice details')}</span><span class="invoice-item-number">${escape(item.invoiceNumber || item.sourceFile)}</span></span></span>
      <span class="invoice-item-foot"><span class="mini-status ${item.approved ? 'approved' : ''}">${item.approved ? 'Approved' : 'Needs review'}</span><span class="invoice-item-amount">${item.total !== '' && item.currency ? escape(item.currency) + ' ' + format(item.total) : '—'}</span></span></button>`).join('') : `<div class="empty-list">${filter === 'approved' ? 'No approved invoices yet.' : filter === 'review' ? 'All caught up. Nothing to review.' : 'Your invoices will appear here.'}</div>`;
    $('invoice-list').querySelectorAll('[data-id]').forEach(button => button.addEventListener('click', () => {currentID = button.dataset.id; render();}));
  }
  function renderExport() {
    const count = approved().length;
    $('export-button').disabled = count === 0;
    $('export-count').textContent = count;
    $('export-title').textContent = count ? `${count} approved invoice${count === 1 ? '' : 's'}, ready for Excel.` : 'Your Excel file starts here.';
    $('export-description').textContent = count ? 'One row per invoice. Sample rows are clearly labeled.' : 'Approve an invoice to include it in your export.';
  }
  function sourceHTML(sample) {
    return `<article class="paper-invoice" aria-label="Fictional sample invoice. Original values are independent of the editable fields."><div class="paper-top"><div class="paper-mark">${sample.invoiceNumber.startsWith('DPS') ? 'dp.' : 'n.'}</div><span class="paper-arabic" lang="ar" dir="rtl">${escape(sample.arabic)}</span></div><h4 class="paper-supplier" dir="auto">${escape(sample.supplier)}</h4><p class="paper-address">${escape(sample.city)}<br>Fictional supplier · sample document</p><div class="paper-title">INVOICE</div><div class="paper-meta"><span>${escape(sample.invoiceNumber)}</span><span>${escape(new Date(sample.date + 'T12:00:00').toLocaleDateString('en-GB',{day:'2-digit',month:'short',year:'numeric'}))}</span></div><table class="paper-table"><thead><tr><th>DESCRIPTION</th><th>${escape(sample.currency)}</th></tr></thead><tbody>${sample.items.map(item => `<tr><td dir="auto">${escape(item[0])}</td><td>${escape(item[1])}</td></tr>`).join('')}</tbody></table><div class="paper-totals"><div class="paper-total-line"><span>Subtotal</span><span>${format(sample.net)}</span></div><div class="paper-total-line"><span>Tax</span><span>${format(sample.vat)}</span></div><div class="paper-total-line paper-grand-total"><span>Total ${escape(sample.currency)}</span><span>${format(sample.total)}</span></div></div><div class="paper-stamp">SAMPLE ONLY · NOT A REAL INVOICE</div></article>`;
  }
  function renderSource(item) {
    const preview = $('source-preview');
    preview.classList.toggle('has-upload', item.mode !== 'sample');
    $('source-type').textContent = item.mode === 'sample' ? 'SAMPLE' : item.fileType === 'application/pdf' ? 'PDF' : 'IMAGE';
    if (item.mode === 'sample') {
      preview.innerHTML = sourceHTML(item.sample);
      $('source-caption').textContent = 'Fictional example · for trying the workflow';
    } else {
      preview.innerHTML = '';
      if (item.fileType === 'application/pdf') {
        const frame = document.createElement('iframe'); frame.className='source-pdf'; frame.src=item.url; frame.title='Original invoice PDF'; preview.appendChild(frame);
      } else {
        const img = document.createElement('img'); img.className='source-image'; img.src=item.url; img.alt='Uploaded invoice ' + item.sourceFile;
        img.onerror = () => { preview.innerHTML='<p class="source-error">This image could not be displayed. Try a different PDF, JPG, PNG, or WebP file.</p>'; };
        preview.appendChild(img);
      }
      $('source-caption').innerHTML = '';
      const a = document.createElement('a'); a.className='file-open-link'; a.href=item.url; a.target='_blank'; a.rel='noopener'; a.textContent='Open original file ↗';
      $('source-caption').appendChild(a);
    }
  }
  function renderHeader(item) {
    $('selected-supplier').textContent = item.supplier || 'New invoice';
    $('selected-meta').textContent = `${item.invoiceNumber || item.sourceFile} · ${item.mode === 'sample' ? 'Sample invoice' : item.mode === 'ai' ? 'AI-assisted draft · review required' : item.mode === 'ocr' ? 'OCR draft · review required' : 'Manual entry'}`;
    $('selected-status').textContent = item.aiStatus === 'reading' ? 'Reading…' : item.approved ? 'Approved' : 'Needs review';
    $('selected-status').classList.toggle('approved', item.approved);
    $('approve-button').disabled = item.approved || item.aiStatus === 'reading';
    $('approve-button').innerHTML = icon('check') + (item.approved ? 'Approved for export' : 'Approve invoice');
    $('review-confirm').checked = item.confirmed;
    $('approval-hint').textContent = item.approved ? 'Editing a detail will require you to review it again.' : 'Approval adds this invoice to your Excel export.';
    $('currency-prefix').textContent = item.currency || 'CUR';
    renderAi(item);
  }
  function cents(value) {
    // Convert decimal input directly to integer cents, avoiding addition drift.
    const match = String(value).match(/^(\d+)(?:\.(\d{1,2}))?$/);
    if (!match) return null;
    const result = Number(match[1]) * 100 + Number((match[2] || '').padEnd(2,'0'));
    return Number.isSafeInteger(result) && result <= 99999999999900 ? result : null;
  }
  function validDate(value) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    const date = new Date(value + 'T00:00:00Z');
    return !isNaN(date) && date.toISOString().slice(0,10) === value && value >= '1900-01-01' && value <= '9999-12-31';
  }
  function errorsFor(item) {
    const issues = [];
    if (item.aiStatus === 'reading') issues.push(['read-ai-button','Wait for invoice reading to finish before approving.']);
    if (!item.supplier.trim()) issues.push(['supplier','Enter the supplier name.']);
    if (!item.invoiceNumber.trim()) issues.push(['invoiceNumber','Enter the invoice number.']);
    if (!validDate(item.date)) issues.push(['date','Enter a valid invoice date (1900 or later).']);
    if (!['SAR','AED','USD','EUR','GBP'].includes(item.currency)) issues.push(['currency','Choose the invoice currency.']);
    for (const [key, label] of [['net','net amount'],['vat','tax amount'],['total','invoice total']]) {
      const value = cents(item[key]);
      if (value === null) issues.push([key,`Enter a non-negative ${label} with no more than two decimal places.`]);
      else if (key === 'total' && value <= 0) issues.push([key,'Invoice total must be greater than zero.']);
    }
    const n = cents(item.net), v = cents(item.vat), t = cents(item.total);
    if (n !== null && v !== null && t !== null && n + v !== t) issues.push(['total','Net amount + tax must equal the invoice total.']);
    if (item.invoiceNumber.trim() && item.supplier.trim()) {
      const duplicate = invoices.some(other => other.id !== item.id && other.supplier.trim().toLocaleLowerCase() === item.supplier.trim().toLocaleLowerCase() && other.invoiceNumber.trim().toLocaleLowerCase() === item.invoiceNumber.trim().toLocaleLowerCase());
      if (duplicate) issues.push(['invoiceNumber','This supplier and invoice number already exist in the inbox. Check for a duplicate.']);
    }
    if (!item.confirmed) issues.push(['review-confirm','Confirm that you checked the details against the invoice.']);
    return issues;
  }
  function updateAmountCheck(item) {
    const n=cents(item.net),v=cents(item.vat),t=cents(item.total), el=$('amount-check');
    el.className='amount-check';
    if (n === null || v === null || t === null) {el.classList.add('neutral');el.textContent='Enter all three amounts to check the total.';}
    else if (n + v === t) {el.innerHTML=icon('check')+'<span>Amounts add up · tax rules are not checked</span>';}
    else {el.classList.add('warning');el.innerHTML=icon('alert')+`<span>Net + tax is ${escape(item.currency)} ${format((n+v)/100)}. Check the total.</span>`;}
  }
  function clearErrors() { $('form-errors').hidden=true; fields.forEach(key => $(key).removeAttribute('aria-invalid')); $('review-confirm').removeAttribute('aria-invalid'); }
  function renderAi(item) {
    const reading=item.aiStatus==='reading';
    $('read-ai-button').disabled=reading || item.mode==='sample' || !aiConnection.configured;
    $('read-ai-button').innerHTML=icon('sparkles')+(reading?'Reading invoice…':item.aiResult?'Read again':'Read invoice');
    $('remove-button').disabled=reading;
    $('ai-read-state').textContent=reading?'Reading the document. Your edits will be kept.':item.mode==='sample'?'Samples are prefilled. Upload your own file to try the reader.':!aiConnection.configured?'Set up the reader above, or use manual entry.':item.aiResult?'Review the draft and any notes below.':'Arabic and English · PDF or image';
    renderReaderDisclosure();
    $('reading-text').hidden=!item.reading?.source_text;
    $('reading-source-text').textContent=item.reading?.source_text || '';
    $('reading-text-detail').textContent=item.reading?.source_text ? `${item.reading.engine}. Compare this recognized text with the original; it can contain mistakes.` : '';
    const feedback=$('ai-feedback');
    const result=item.aiResult;
    const messages=[];
    if(item.aiError) messages.push(item.aiError);
    if(item.aiMessage) messages.push(item.aiMessage);
    if(result) messages.push(...result.warnings);
    feedback.hidden=!messages.length;
    feedback.classList.toggle('error',!!item.aiError);
    feedback.innerHTML=messages.length?'<ul>'+messages.map(message=>'<li>'+escape(message)+'</li>').join('')+'</ul>':'';
    $('ai-insights').hidden=!result;
    if(!result) {$('ai-insight-body').innerHTML='';return;}
    const candidates=aiFields.filter(field=>result[field]!==null && String(result[field])!==String(item[field]));
    const warningList=result.field_warnings.length?'<h4>Fields to double-check</h4><ul>'+result.field_warnings.map(w=>'<li><strong>'+escape(fieldNames[w.field]||w.field)+':</strong> '+escape(w.message)+'</li>').join('')+'</ul>':'';
    const suggestions=candidates.length&&result.is_invoice?'<h4>Suggestions kept separate from your edits</h4><div class="ai-candidates">'+candidates.map(field=>`<div><span><strong>${escape(fieldNames[field])}</strong><span dir="auto">${escape(result[field])}</span></span><button type="button" class="button secondary" data-apply-ai="${field}" ${reading?'disabled':''}>Use value</button></div>`).join('')+'</div>':'';
    const lines=result.line_items.length?'<h4>Extracted line items</h4><p class="ai-line-note">Reference only. Excel exports the invoice totals, not these individual lines.</p><div class="ai-line-items">'+result.line_items.map(line=>`<div><strong dir="auto">${escape(line.description)}</strong><p>Qty: ${escape(line.quantity??'Not clear')} · Unit price: ${escape(line.unit_price??'Not clear')} · Net: ${escape(line.net_amount??'Not clear')}</p></div>`).join('')+'</div>':'<p>No individual line items were clearly extracted.</p>';
    $('ai-insight-body').innerHTML=warningList+suggestions+lines;
    $('ai-insight-body').querySelectorAll('[data-apply-ai]').forEach(button=>button.addEventListener('click',()=>{
      const selected=current();
      if(!selected || selected.id!==item.id || selected.aiStatus==='reading') return;
      const field=button.dataset.applyAi;
      if(!aiFields.includes(field))return;
      selected[field]=String(result[field]);selected.revision=(selected.revision||0)+1;
      selected.approved=false;selected.confirmed=false;selected.reviewedAt='';
      render();tell('Reading suggestion applied. Check it against the invoice.');
    }));
  }
  function renderReaderDisclosure() {
    let detail='Use the local app for invoice reading. Uploading alone does not send your file.';
    let footer='Website preview · samples and manual entry';
    if(aiConnection.localServer) {
      const destination=aiConnection.data_destination || (aiConnection.provider==='ocr'?'local':aiConnection.provider || 'openai');
      if(destination==='local') {
        detail='Local OCR reads on this computer. Your invoice and recognized text stay on this device. No API key or per-read API charge.';
        footer='Local OCR · invoice reading stays on this device';
      } else if(destination==='groq') {
        detail='Read invoice recognizes text locally, then sends that text to Groq for AI assistance. The image or PDF stays on this device. Groq usage limits apply. Uploading alone does not send anything.';
        footer='Groq AI · recognized text is sent only when you click Read';
      } else {
        detail='Read invoice sends this image or PDF to OpenAI. API usage charges apply. Uploading alone does not send it.';
        footer='OpenAI AI · files are sent only when you click Read';
      }
    }
    $('reader-disclosure').textContent=detail;
    $('reader-footer').textContent=footer;
  }
  async function refreshConnection() {
    $('ai-check-connection').disabled=true;
    try {
      aiConnection=window.RasamAI?await window.RasamAI.status():{configured:false,localServer:false};
      const provider=aiConnection.provider || 'openai';
      $('ai-connection-title').textContent=aiConnection.configured?(provider==='ocr'?'Local OCR ready':provider==='groq'?'Groq AI key configured':'OpenAI AI key configured'):aiConnection.localServer?(provider==='ocr'?'Set up local text recognition':'Set up '+(provider==='groq'?'Groq AI':'OpenAI AI')+' in the launcher'):'Open the local app for free invoice reading';
      const message=typeof aiConnection.message==='string'?aiConnection.message:'';
      $('ai-connection-detail').textContent=aiConnection.configured?(provider==='ocr'?(message || 'Read a PDF or image with local text recognition. Review every field before approval.'):`${message || 'Upload a file, then choose Read invoice. Your first read tests the key.'}${aiConnection.model ? ' Model: '+aiConnection.model+'.' : ''}`):aiConnection.localServer?(message || 'Follow the local app setup guide, then restart the launcher. Samples and manual entry remain available.'):'Install the free local reader and run the launcher on your computer. This website preview supports samples and manual entry.';
    } catch(error) {
      aiConnection={configured:false,localServer:false};
      $('ai-connection-title').textContent='The local reader is not connected';
      $('ai-connection-detail').textContent=error.message;
    } finally {
      $('ai-check-connection').disabled=false;
      $('reader-setup-link').hidden=!!aiConnection.configured;
      renderReaderDisclosure();
      if(current())renderAi(current());
    }
  }
  async function readWithAI() {
    const item=current();
    if(!item || !item.file || item.mode==='sample' || item.aiStatus==='reading')return;
    if(!aiConnection.configured){tell('Set up the invoice reader in the local launcher first.',true);return;}
    const revision=item.revision||0;
    const requestProvider=aiConnection.provider || 'openai';
    item.aiStatus='reading';item.aiError='';item.aiMessage='';item.approved=false;item.confirmed=false;item.reviewedAt='';
    renderHeader(item);renderList();renderExport();
    try {
      const result=await window.RasamAI.extract(item.file,item.fileType,aiConnection.csrf_token);
      if(!invoices.includes(item))return;
      item.aiResult=result;
      item.reading=result.reading || {provider:requestProvider,engine:requestProvider==='ocr'?'Local OCR':'AI invoice reader',source_text:''};
      if(!result.is_invoice) {
        item.aiStatus='error';
        item.aiError='This file could not be treated as a single invoice. Try a clearer invoice or enter the details manually.';
      } else {
        let count=0;
        if((item.revision||0)===revision) {
          aiFields.forEach(field=>{if(!String(item[field]??'').trim() && result[field]!==null){item[field]=result[field];count++;}});
        }
        // A later OCR read must not erase earlier AI assistance from provenance.
        item.mode=item.mode==='ai' || item.reading.provider!=='ocr'?'ai':'ocr';item.aiStatus='done';
        item.aiMessage=count?`${count} empty field${count===1?'':'s'} filled. Existing values were kept. Review the draft before approval.`:'Your existing values were kept. Open reading suggestions below to compare the result.';
      }
    } catch(error) {
      item.aiStatus='error';item.aiError=error.message||'Invoice reading failed. Your existing details were kept.';
      if(['not_configured','ocr_unavailable','authentication','authentication_failed','invalid_api_key'].includes(error.code)) {
        aiConnection.configured=false;
        $('ai-connection-title').textContent=requestProvider==='ocr'?'Local OCR needs attention':(requestProvider==='groq'?'Groq AI':'OpenAI AI')+' key needs attention';
        $('ai-connection-detail').textContent=item.aiError;
        $('reader-setup-link').hidden=false;
      }
    } finally {
      item.approved=false;item.confirmed=false;item.reviewedAt='';
      if(currentID===item.id){render();if(item.aiResult&&item.aiResult.field_warnings.length)$('ai-insights').open=true;}
      else {renderList();renderExport();if(current())renderAi(current());}
      tell(item.aiError || 'Invoice reading finished. Review the draft.',!!item.aiError);
    }
  }
  function render() {
    renderList(); renderExport();
    const item=current();
    $('review-panel').hidden=!item; $('empty-panel').hidden=!!item;
    if (!item) return;
    clearErrors(); renderHeader(item); renderSource(item);
    fields.forEach(key => { $(key).value=item[key] ?? ''; });
    $('entry-description').textContent=item.mode === 'sample' ? 'Example values are filled in. Compare them with the invoice.' : item.mode === 'ai' ? 'AI helped draft these details. Check every field against the source.' : item.mode === 'ocr' ? 'Local text recognition drafted these details. Check every field against the source.' : 'Read this invoice, or enter its details manually.';
    updateAmountCheck(item);
  }
  fields.forEach(key => {
    $(key).addEventListener('input', () => {
      const item=current(); if (!item) return;
      const newValue=$(key).value;
      if (newValue === item[key]) return;
      const wasApproved=item.approved;
      item[key]=newValue;item.approved=false;item.confirmed=false;item.reviewedAt='';item.revision=(item.revision||0)+1;
      clearErrors();renderHeader(item);updateAmountCheck(item);renderList();renderExport();
      if (wasApproved) tell('Details changed. Review this invoice again before exporting.');
    });
  });
  $('review-confirm').addEventListener('change', () => {
    const item=current(); if (!item) return;
    item.confirmed=$('review-confirm').checked;
    if (!item.confirmed) {item.approved=false;item.reviewedAt='';}
    clearErrors();renderHeader(item);renderList();renderExport();
  });
  $('invoice-form').addEventListener('submit', event => {
    event.preventDefault();const item=current();if (!item) return;
    clearErrors();const issues=errorsFor(item);
    if (issues.length) {
      $('form-errors').innerHTML='<ul>'+issues.map(([,message])=>'<li>'+escape(message)+'</li>').join('')+'</ul>';
      $('form-errors').hidden=false;
      issues.forEach(([field])=>$(field).setAttribute('aria-invalid','true'));
      $(issues[0][0]).focus();tell('A few details need your attention.',true);return;
    }
    item.supplier=item.supplier.trim();item.invoiceNumber=item.invoiceNumber.trim();item.approved=true;item.reviewedAt=new Date().toISOString();
    renderHeader(item);renderList();renderExport();tell('Invoice approved. You can now export it to Excel.');
  });
  function downloadFile(bytes, filename, mime) {
    const blob=bytes instanceof Blob ? bytes : new Blob([bytes],{type:mime});
    const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=filename;document.body.appendChild(a);a.click();a.remove();
    setTimeout(()=>URL.revokeObjectURL(url),30000);
  }
  $('export-button').addEventListener('click', () => {
    const rows=approved();if (!rows.length) return;
    // Re-check records at export as well as at approval.
    const bad=rows.find(item=>errorsFor(item).length);
    if (bad) {bad.approved=false;bad.confirmed=false;bad.reviewedAt='';currentID=bad.id;filter='all';render();tell('An approved invoice needs another review before export.',true);return;}
    try {
      const data=rows.map(item=>({...item,net:Number(item.net),vat:Number(item.vat),total:Number(item.total)}));
      const bytes=window.RasamExport.buildXlsx(data);
      const date=new Date().toISOString().slice(0,10);
      downloadFile(bytes,`rasam-invoices-${date}.xlsx`,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
      tell(`Excel export prepared with ${rows.length} approved invoice${rows.length===1?'':'s'}.`);
    } catch (error) {console.error('Export failed',error);tell('Excel export could not be created. Your invoice details are still here.',true);}
  });
  async function detectFileType(file) {
    const b=new Uint8Array(await file.slice(0,12).arrayBuffer());
    if(b[0]===0x25&&b[1]===0x50&&b[2]===0x44&&b[3]===0x46&&b[4]===0x2d)return 'application/pdf';
    if(b[0]===0xff&&b[1]===0xd8&&b[2]===0xff)return 'image/jpeg';
    if(b[0]===0x89&&b[1]===0x50&&b[2]===0x4e&&b[3]===0x47&&b[4]===0x0d&&b[5]===0x0a&&b[6]===0x1a&&b[7]===0x0a)return 'image/png';
    if(b[0]===0x52&&b[1]===0x49&&b[2]===0x46&&b[3]===0x46&&b[8]===0x57&&b[9]===0x45&&b[10]===0x42&&b[11]===0x50)return 'image/webp';
    return null;
  }
  let importInProgress=false;
  async function addFiles(fileList) {
    if(importInProgress){tell('Please wait for the current files to finish loading.');return;}
    importInProgress=true;
    let added=0,skipped=[];
    try {
      for (const file of Array.from(fileList)) {
        if(invoices.length>=50){skipped.push('This prototype supports up to 50 invoices per session.');break;}
        if(file.size>20*1024*1024){skipped.push(file.name+': exceeds the 20 MB limit.');continue;}
        if(invoices.some(i=>i.fileKey===`${file.name}:${file.size}:${file.lastModified}`)){skipped.push(file.name+': already in the inbox.');continue;}
        const type=await detectFileType(file);
        if(!type){skipped.push(file.name+': choose a valid PDF, JPG, PNG, or WebP file.');continue;}
        const item={id:'RAS-'+String(nextID++).padStart(4,'0'),supplier:'',invoiceNumber:'',date:'',currency:'',net:'',vat:'',total:'',notes:'',mode:'manual',approved:false,confirmed:false,reviewedAt:'',revision:0,file,sourceFile:file.name,fileType:type,fileKey:`${file.name}:${file.size}:${file.lastModified}`,url:URL.createObjectURL(file)};
        invoices.push(item);currentID=item.id;added++;
      }
      if(added){filter='all';render();tell(`${added} file${added===1?'':'s'} added. Choose Read invoice or enter details manually.`);}
      if(skipped.length)tell((added?`${added} file${added===1?'':'s'} added. `:'')+skipped.slice(0,2).join(' '),true);
    } catch(error){console.error('Import failed',error);tell('A file could not be opened. Try uploading it again.',true);if(added)render();}
    finally {importInProgress=false;$('file-input').value='';}
  }
  function chooseFiles() {$('file-input').click();}
  ['upload-button','drop-zone'].forEach(id=>$(id).addEventListener('click',chooseFiles));
  $('file-input').addEventListener('change',event=>addFiles(event.target.files));
  const drop=$('drop-zone');
  ['dragenter','dragover'].forEach(type=>drop.addEventListener(type,event=>{event.preventDefault();drop.classList.add('drag-over');}));
  ['dragleave','drop'].forEach(type=>drop.addEventListener(type,event=>{event.preventDefault();drop.classList.remove('drag-over');}));
  drop.addEventListener('drop',event=>addFiles(event.dataTransfer.files));
  // Prevent dropping a file elsewhere from navigating away and clearing this session.
  window.addEventListener('dragover',event=>{if(event.dataTransfer.types.includes('Files'))event.preventDefault();});
  window.addEventListener('drop',event=>{if(event.dataTransfer.types.includes('Files'))event.preventDefault();});
  ['sample-button','sidebar-sample','empty-sample'].forEach(id=>$(id).addEventListener('click',()=>addSample()));
  document.querySelectorAll('[data-filter]').forEach(button=>button.addEventListener('click',()=>{
    filter=button.dataset.filter;const shown=shownInvoices();
    if(!shown.some(item=>item.id===currentID))currentID=shown[0]?.id??null;
    render();
  }));
  ['guide-button','top-guide','note-guide'].forEach(id=>$(id).addEventListener('click',()=>$('guide-dialog').showModal()));
  ['close-guide','guide-done'].forEach(id=>$(id).addEventListener('click',()=>$('guide-dialog').close()));
  $('remove-button').addEventListener('click',()=>{
    const item=current();if(!item)return;pendingRemoveID=item.id;
    $('remove-description').textContent=`“${item.supplier||item.sourceFile}” and its details will be removed from this session.`;
    $('remove-dialog').showModal();
  });
  ['cancel-remove','cancel-remove-icon'].forEach(id=>$(id).addEventListener('click',()=>$('remove-dialog').close()));
  $('confirm-remove').addEventListener('click',()=>{
    const index=invoices.findIndex(item=>item.id===pendingRemoveID);
    if(index>=0){const [removed]=invoices.splice(index,1);if(removed.url)URL.revokeObjectURL(removed.url);}
    $('remove-dialog').close();pendingRemoveID=null;currentID=shownInvoices()[0]?.id??null;render();tell('Invoice removed from this session.');
  });
  window.addEventListener('beforeunload',event=>{if(invoices.some(i=>i.mode!=='sample'||i.approved)){event.preventDefault();event.returnValue='';}});
  $('read-ai-button').addEventListener('click',readWithAI);
  $('ai-check-connection').addEventListener('click',refreshConnection);
  icons();addSample(true);refreshConnection();
})();
