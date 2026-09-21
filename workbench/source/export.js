/* Rasam XLSX export. No network calls or third-party runtime dependencies. */
(function (global) {
  'use strict';

  var encoder = new TextEncoder();
  var NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main';
  var XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>';
  var CRC_TABLE = new Uint32Array(256);
  for (var n = 0; n < 256; n += 1) {
    var value = n;
    for (var bit = 0; bit < 8; bit += 1) value = value & 1 ? 0xEDB88320 ^ (value >>> 1) : value >>> 1;
    CRC_TABLE[n] = value >>> 0;
  }

  function clean(value) {
    // Excel limits a cell to 32,767 UTF-16 code units. Replace malformed Unicode
    // and disallowed XML 1.0 code points without changing valid Arabic text.
    return Array.from(String(value == null ? '' : value)).filter(function (character) {
      var cp = character.codePointAt(0);
      return cp === 9 || cp === 10 || cp === 13 ||
        (cp >= 32 && cp <= 0xD7FF) || (cp >= 0xE000 && cp <= 0xFFFD) ||
        (cp >= 0x10000 && cp <= 0x10FFFF);
    }).join('').slice(0, 32767).replace(/[\uD800-\uDBFF]$/, '');
  }

  function escapeXml(value) {
    return clean(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&apos;');
  }

  function textCell(reference, value, style) {
    // inlineStr is deliberate: even values beginning =, +, -, or @ are text.
    return '<c r="' + reference + '" t="inlineStr" s="' + (style || 0) + '"><is><t xml:space="preserve">' + escapeXml(value) + '</t></is></c>';
  }

  function numberCell(reference, value, style) {
    if (value === null || value === undefined || value === '') return textCell(reference, '', style);
    var number = Number(value);
    if (!Number.isFinite(number)) return textCell(reference, value, style);
    return '<c r="' + reference + '" s="' + style + '"><v>' + number + '</v></c>';
  }

  function excelDate(value, isTimestamp) {
    if (!value) return null;
    var timestamp;
    if (isTimestamp) {
      timestamp = Date.parse(value);
    } else {
      var parts = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value));
      if (!parts) return null;
      var year = Number(parts[1]);
      var month = Number(parts[2]);
      var day = Number(parts[3]);
      timestamp = Date.UTC(year, month - 1, day);
      var date = new Date(timestamp);
      if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) return null;
    }
    if (!Number.isFinite(timestamp)) return null;
    var serial = (timestamp - Date.UTC(1899, 11, 30)) / 86400000;
    // Workbooks use the standard Excel 1900 date system, including its leap bug.
    if (serial > 0 && serial < 61) serial -= 1;
    return serial >= 0 && serial < 2958466 ? serial : null;
  }

  function dateCell(reference, value, isTimestamp) {
    var serial = excelDate(value, isTimestamp);
    var style = isTimestamp ? 6 : 5;
    return serial === null ? textCell(reference, value, style) : numberCell(reference, serial, style);
  }

  function crc32(bytes) {
    var crc = 0xFFFFFFFF;
    for (var i = 0; i < bytes.length; i += 1) crc = CRC_TABLE[(crc ^ bytes[i]) & 0xFF] ^ (crc >>> 8);
    return (crc ^ 0xFFFFFFFF) >>> 0;
  }

  function concat(chunks) {
    var length = chunks.reduce(function (sum, chunk) { return sum + chunk.length; }, 0);
    var result = new Uint8Array(length);
    var offset = 0;
    chunks.forEach(function (chunk) { result.set(chunk, offset); offset += chunk.length; });
    return result;
  }

  function zip(files) {
    var localParts = [];
    var centralParts = [];
    var offset = 0;
    files.forEach(function (file) {
      var name = encoder.encode(file.name);
      var data = encoder.encode(file.content);
      var crc = crc32(data);
      var local = new Uint8Array(30 + name.length);
      var view = new DataView(local.buffer);
      view.setUint32(0, 0x04034B50, true);
      view.setUint16(4, 20, true);
      view.setUint16(6, 0x0800, true); // UTF-8 paths; uncompressed ZIP entries.
      view.setUint16(12, 0x5021, true); // 2020-01-01, deterministic archive date.
      view.setUint32(14, crc, true);
      view.setUint32(18, data.length, true);
      view.setUint32(22, data.length, true);
      view.setUint16(26, name.length, true);
      local.set(name, 30);
      localParts.push(local, data);

      var central = new Uint8Array(46 + name.length);
      view = new DataView(central.buffer);
      view.setUint32(0, 0x02014B50, true);
      view.setUint16(4, 20, true);
      view.setUint16(6, 20, true);
      view.setUint16(8, 0x0800, true);
      view.setUint16(14, 0x5021, true);
      view.setUint32(16, crc, true);
      view.setUint32(20, data.length, true);
      view.setUint32(24, data.length, true);
      view.setUint16(28, name.length, true);
      view.setUint32(42, offset, true);
      central.set(name, 46);
      centralParts.push(central);
      offset += local.length + data.length;
    });
    var centralBytes = concat(centralParts);
    var end = new Uint8Array(22);
    var endView = new DataView(end.buffer);
    endView.setUint32(0, 0x06054B50, true);
    endView.setUint16(8, files.length, true);
    endView.setUint16(10, files.length, true);
    endView.setUint32(12, centralBytes.length, true);
    endView.setUint32(16, offset, true);
    return concat(localParts.concat([centralBytes, end]));
  }

  function sheet(invoices) {
    var headers = ['Invoice date', 'Supplier', 'Invoice number', 'Currency', 'Net', 'VAT', 'Total', 'Data origin', 'Source file', 'Approved at (UTC)', 'Notes', 'Record ID', 'VAT rate', 'Supplier VAT number / TRN'];
    var widths = [16, 34, 24, 13, 17, 17, 17, 19, 32, 25, 48, 30, 16, 29];
    var rows = [
      '<row r="1" ht="32" customHeight="1">' + textCell('A1', 'Rasam | Approved invoices', 1) + '</row>',
      '<row r="2" ht="32" customHeight="1">' + textCell('A2', 'Reviewed invoice data, not a posted journal. Sample rows contain fictional data. Amounts are the approved values entered in Rasam.', 2) + '</row>',
      '<row r="4" ht="26" customHeight="1">' + headers.map(function (header, index) { return textCell(String.fromCharCode(65 + index) + '4', header, 3); }).join('') + '</row>'
    ];
    invoices.forEach(function (invoice, index) {
      var row = index + 5;
      var origin = invoice.mode === 'sample' ? 'Sample' : invoice.mode === 'ocr' ? 'OCR-assisted, human reviewed' : invoice.mode === 'ai' ? 'AI-assisted, human reviewed' : invoice.mode === 'manual' ? 'Manual entry' : 'Unspecified';
      var cells = [
        dateCell('A' + row, invoice.date, false),
        textCell('B' + row, invoice.supplier),
        textCell('C' + row, invoice.invoiceNumber),
        textCell('D' + row, invoice.currency),
        numberCell('E' + row, invoice.net, 4),
        numberCell('F' + row, invoice.vat, 4),
        numberCell('G' + row, invoice.total, 4),
        textCell('H' + row, origin),
        textCell('I' + row, invoice.sourceFile),
        dateCell('J' + row, invoice.reviewedAt, true),
        textCell('K' + row, invoice.notes),
        textCell('L' + row, invoice.id),
        numberCell('M' + row, invoice.vatRate == null || String(invoice.vatRate).trim() === '' ? null : Number(invoice.vatRate) / 100, 7),
        textCell('N' + row, invoice.supplierVatNumber)
      ];
      rows.push('<row r="' + row + '">' + cells.join('') + '</row>');
    });
    var lastRow = Math.max(4, invoices.length + 4);
    return XML + '<worksheet xmlns="' + NS + '">' +
      '<dimension ref="A1:N' + lastRow + '"/>' +
      '<sheetViews><sheetView workbookViewId="0" showGridLines="0"><pane ySplit="4" topLeftCell="A5" activePane="bottomLeft" state="frozen"/><selection pane="bottomLeft" activeCell="A5" sqref="A5"/></sheetView></sheetViews>' +
      '<sheetFormatPr defaultRowHeight="22"/>' +
      '<cols>' + widths.map(function (width, index) { return '<col min="' + (index + 1) + '" max="' + (index + 1) + '" width="' + width + '" customWidth="1"/>'; }).join('') + '</cols>' +
      '<sheetData>' + rows.join('') + '</sheetData>' +
      '<autoFilter ref="A4:N' + lastRow + '"/>' +
      '<mergeCells count="2"><mergeCell ref="A1:N1"/><mergeCell ref="A2:N2"/></mergeCells>' +
      '<pageMargins left="0.3" right="0.3" top="0.5" bottom="0.5" header="0.2" footer="0.2"/>' +
      '<pageSetup orientation="landscape" paperSize="9"/>' +
      '</worksheet>';
  }

  function buildXlsx(invoices) {
    if (!Array.isArray(invoices)) throw new TypeError('Expected an array of approved invoices.');
    if (invoices.length > 1048572) throw new RangeError('Too many invoices for a single Excel sheet.');
    invoices.forEach(function (invoice) {
      if (!invoice || typeof invoice !== 'object') throw new TypeError('Each invoice must be an object.');
    });
    var relationshipsNS = 'http://schemas.openxmlformats.org/package/2006/relationships';
    var documentNS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships';
    return zip([
      { name: '[Content_Types].xml', content: XML + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>' },
      { name: '_rels/.rels', content: XML + '<Relationships xmlns="' + relationshipsNS + '"><Relationship Id="rId1" Type="' + documentNS + '/officeDocument" Target="xl/workbook.xml"/></Relationships>' },
      { name: 'xl/workbook.xml', content: XML + '<workbook xmlns="' + NS + '" xmlns:r="' + documentNS + '"><bookViews><workbookView/></bookViews><sheets><sheet name="Approved invoices" sheetId="1" r:id="rId1"/></sheets></workbook>' },
      { name: 'xl/_rels/workbook.xml.rels', content: XML + '<Relationships xmlns="' + relationshipsNS + '"><Relationship Id="rId1" Type="' + documentNS + '/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="' + documentNS + '/styles" Target="styles.xml"/></Relationships>' },
      { name: 'xl/styles.xml', content: XML + '<styleSheet xmlns="' + NS + '">' +
        '<numFmts count="3"><numFmt numFmtId="164" formatCode="#,##0.00"/><numFmt numFmtId="165" formatCode="yyyy-mm-dd"/><numFmt numFmtId="166" formatCode="yyyy-mm-dd hh:mm"/></numFmts>' +
        '<fonts count="4"><font><sz val="11"/><name val="Calibri"/><color rgb="FF20382E"/></font><font><b/><sz val="19"/><name val="Calibri"/><color rgb="FF124C37"/></font><font><sz val="10"/><name val="Calibri"/><color rgb="FF56695F"/></font><font><b/><sz val="11"/><name val="Calibri"/><color rgb="FFFFFFFF"/></font></fonts>' +
        '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF175C43"/><bgColor indexed="64"/></patternFill></fill></fills>' +
        '<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border><border><left/><right/><top/><bottom style="hair"><color rgb="FFDBE7E0"/></bottom><diagonal/></border></borders>' +
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>' +
        '<cellXfs count="8">' +
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>' +
        '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center"/></xf>' +
        '<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>' +
        '<xf numFmtId="0" fontId="3" fillId="2" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center"/></xf>' +
        '<xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1"><alignment vertical="top"/></xf>' +
        '<xf numFmtId="165" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1"><alignment vertical="top"/></xf>' +
        '<xf numFmtId="166" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1"><alignment vertical="top"/></xf>' +
        '<xf numFmtId="10" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1"><alignment vertical="top"/></xf>' +
        '</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>' },
      { name: 'xl/worksheets/sheet1.xml', content: sheet(invoices) }
    ]);
  }

  global.RasamExport = Object.freeze({ buildXlsx: buildXlsx });
})(typeof window !== 'undefined' ? window : globalThis);
