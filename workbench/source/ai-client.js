/* Browser-to-local-reader bridge. API keys remain in the launcher/server. */
(function(global) {
  'use strict';
  function localServer() {
    return !global.RASAM_INLINE_PREVIEW && global.location &&
      ['http:', 'https:'].includes(global.location.protocol) &&
      ['localhost', '127.0.0.1', '[::1]'].includes(global.location.hostname);
  }
  async function jsonRequest(path, options, timeout) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const response = await fetch(path, {...options, signal:controller.signal, credentials:'same-origin', cache:'no-store'});
      let body;
      try {body = await response.json();} catch (_) {throw new Error('Start Rasam with its launcher to enable invoice reading.');}
      if (!response.ok) {
        const error = new Error(typeof body.error === 'string' ? body.error : 'Invoice reading could not finish. Try again or enter the details manually.');
        error.code = body.code || 'request_failed';
        throw error;
      }
      return body;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('Invoice reading timed out. Your file and edits are still here.');
      if (error instanceof TypeError) throw new Error('Cannot reach the Rasam server. Keep the launcher window open and try again.');
      throw error;
    } finally {clearTimeout(timer);}
  }
  function base64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(new Error('This file could not be read. Upload it again.'));
      reader.onload = () => {
        const value = String(reader.result || '');
        const comma = value.indexOf(',');
        if (comma < 0) reject(new Error('This file could not be encoded. Upload it again.'));
        else resolve(value.slice(comma + 1));
      };
      reader.readAsDataURL(file);
    });
  }
  global.RasamAI = {
    async status() {
      if (!localServer()) return {configured:false, localServer:false};
      const data = await jsonRequest('/api/status', {method:'GET'}, 5000);
      if (typeof data.configured !== 'boolean' || typeof data.csrf_token !== 'string' ||
          (data.provider !== undefined && !['ocr','groq','openai'].includes(data.provider)) ||
          (data.data_destination !== undefined && !['local','groq','openai'].includes(data.data_destination))) {
        throw new Error('This server does not have a compatible Rasam reader. Use the updated launcher.');
      }
      // Older local launchers exposed only OpenAI. Preserve that disclosure.
      return {...data, provider:data.provider || 'openai', data_destination:data.data_destination || (data.provider === 'ocr' ? 'local' : data.provider || 'openai'), localServer:true};
    },
    async extract(file, mimeType, token) {
      if (!localServer()) throw new Error('Invoice reading runs in the localhost app. Use manual entry in the website preview or a directly opened file.');
      if (!token) throw new Error('Check the reader connection before reading this invoice.');
      const data = await jsonRequest('/api/extract', {
        method:'POST',
        headers:{'Content-Type':'application/json', 'X-Rasam-Token':token},
        body:JSON.stringify({filename:file.name, mime_type:mimeType, data_base64:await base64(file)})
      }, 300000);
      const item=data.invoice;
      if (!item || typeof item.is_invoice !== 'boolean' || !Array.isArray(item.warnings) || !Array.isArray(item.field_warnings) || !Array.isArray(item.line_items)) throw new Error('The reader returned an unreadable result. Your existing details were kept.');
      for(const field of ['supplier','invoiceNumber','date','currency','net','vat','total']) {
        if(item[field] !== null && typeof item[field] !== 'string') throw new Error('The reader returned an invalid field. Your existing details were kept.');
      }
      if (item.warnings.some(value => typeof value !== 'string') ||
          item.field_warnings.some(value => !value || !['supplier','invoiceNumber','date','currency','net','vat','total'].includes(value.field) || typeof value.message !== 'string') ||
          item.line_items.some(value => !value || typeof value.description !== 'string' || ['quantity','unit_price','net_amount'].some(field => value[field] !== null && typeof value[field] !== 'string'))) {
        throw new Error('The reader returned unreadable review notes. Your existing details were kept.');
      }
      const metadata=data.reading;
      if (metadata !== undefined && (!metadata || !['ocr','groq','openai'].includes(metadata.provider) ||
          typeof metadata.engine !== 'string' || metadata.engine.length > 200 ||
          typeof metadata.source_text !== 'string' || metadata.source_text.length > 60000)) {
        throw new Error('The reader returned invalid reading metadata. Your existing details were kept.');
      }
      return {...item, reading:metadata === undefined ? undefined : {
        provider:metadata.provider, engine:metadata.engine, source_text:metadata.source_text
      }};
    }
  };
})(window);
