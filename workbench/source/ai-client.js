/* Browser-to-local-server bridge. An API key never enters this file or browser. */
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
      try {body = await response.json();} catch (_) {throw new Error('Start Rasam with its launcher to enable AI reading.');}
      if (!response.ok) {
        const error = new Error(typeof body.error === 'string' ? body.error : 'AI reading could not finish. Try again or enter the details manually.');
        error.code = body.code || 'request_failed';
        throw error;
      }
      return body;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('AI reading timed out. Your file and edits are still here.');
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
      if (typeof data.configured !== 'boolean' || typeof data.csrf_token !== 'string') throw new Error('This server does not have Rasam AI reading. Use the updated launcher.');
      return {...data, localServer:true};
    },
    async extract(file, mimeType, token) {
      if (!localServer()) throw new Error('AI reading runs in the localhost app, not in the chat preview or a directly opened file.');
      if (!token) throw new Error('Check the AI connection before reading this invoice.');
      const data = await jsonRequest('/api/extract', {
        method:'POST',
        headers:{'Content-Type':'application/json', 'X-Rasam-Token':token},
        body:JSON.stringify({filename:file.name, mime_type:mimeType, data_base64:await base64(file)})
      }, 125000);
      const item=data.invoice;
      if (!item || typeof item.is_invoice !== 'boolean' || !Array.isArray(item.warnings) || !Array.isArray(item.field_warnings) || !Array.isArray(item.line_items)) throw new Error('AI returned an unreadable result. Your existing details were kept.');
      for(const field of ['supplier','invoiceNumber','date','currency','net','vat','total']) {
        if(item[field] !== null && typeof item[field] !== 'string') throw new Error('AI returned an invalid field. Your existing details were kept.');
      }
      if (item.warnings.some(value => typeof value !== 'string') ||
          item.field_warnings.some(value => !value || !['supplier','invoiceNumber','date','currency','net','vat','total'].includes(value.field) || typeof value.message !== 'string') ||
          item.line_items.some(value => !value || typeof value.description !== 'string' || ['quantity','unit_price','net_amount'].some(field => value[field] !== null && typeof value[field] !== 'string'))) {
        throw new Error('AI returned unreadable review notes. Your existing details were kept.');
      }
      return item;
    }
  };
})(window);
