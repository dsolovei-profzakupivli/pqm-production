/* Full verification instants. Offset-free sheet values are Europe/Kyiv wall time. */
function pqmVerificationDatetime_(value) {
  if (pqmGoogleBlank_(value)) return {kind:'blank', value:null};
  var wall;
  if (Object.prototype.toString.call(value) === '[object Date]') {
    return isNaN(value.getTime()) ? {kind:'invalid', value:null} :
      {kind:'datetime', value:value.getTime()};
  }
  if (typeof value === 'number') {
    if (!isFinite(value) || value < 2 || value > 2958465) return {kind:'invalid', value:null};
    wall = new Date(Math.round((value - 25569) * 86400000)).toISOString().slice(0,23);
  } else if (typeof value === 'string') {
    var text = value.trim();
    var explicit = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(?::(\d{2})(\.\d{1,3})?)?(Z|[+-]\d{2}:\d{2})$/.exec(text);
    if (explicit) {
      var local = explicit[1] + 'T' + explicit[2] + ':' + (explicit[3] || '00') + (explicit[4] || '.000');
      var localMs = Date.parse(local + 'Z');
      if (!isFinite(localMs) || new Date(localMs).toISOString().slice(0,19) !== local.slice(0,19))
        return {kind:'invalid', value:null};
      var offset = explicit[5];
      if (offset !== 'Z' && (Number(offset.slice(1,3)) > 14 || Number(offset.slice(4)) > 59 ||
        (Number(offset.slice(1,3)) === 14 && Number(offset.slice(4)) !== 0))) return {kind:'invalid', value:null};
      var ms = Date.parse(text);
      return isFinite(ms) ? {kind:'datetime', value:ms} : {kind:'invalid', value:null};
    }
    var uk = /^(\d{2})\.(\d{2})\.(\d{4})(?:[ T](\d{2}:\d{2})(?::(\d{2}))?)?$/.exec(text);
    if (uk) wall = uk[3] + '-' + uk[2] + '-' + uk[1] + 'T' + (uk[4] || '00:00') + ':' + (uk[5] || '00') + '.000';
    else if (/^\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,3})?)?)?$/.test(text))
      wall = text.slice(0,10) + 'T' + (text.length > 10 ? text.slice(11) : '00:00:00');
    else return {kind:'invalid', value:null};
  } else return {kind:'invalid', value:null};
  var nominal = Date.parse(wall + 'Z');
  if (!isFinite(nominal)) return {kind:'invalid', value:null};
  var canonical = new Date(nominal).toISOString().slice(0,23);
  if (canonical.slice(0,16) !== wall.slice(0,16)) return {kind:'invalid', value:null};
  var candidates = [];
  // Kyiv's modern offsets are UTC+02/+03. Reject unsupported dates and DST folds/gaps.
  if (Number(canonical.slice(0,4)) < 2000) return {kind:'invalid', value:null};
  [2,3].forEach(function(hours) {
    var instant = nominal - hours * 3600000;
    if (Utilities.formatDate(new Date(instant), 'Europe/Kyiv', "yyyy-MM-dd'T'HH:mm:ss.SSS") === canonical)
      candidates.push(instant);
  });
  return candidates.length === 1 ? {kind:'datetime', value:candidates[0]} : {kind:'invalid', value:null};
}
function pqmVerificationSerial_(instant) {
  var wall = Utilities.formatDate(new Date(instant), 'Europe/Kyiv', "yyyy-MM-dd'T'HH:mm:ss.SSS");
  var parsed = pqmVerificationDatetime_(wall);
  if (parsed.kind !== 'datetime' || parsed.value !== instant)
    throw new Error('PQM: verification instant cannot be represented unambiguously in this sheet.');
  return Date.parse(wall + 'Z') / 86400000 + 25569;
}
