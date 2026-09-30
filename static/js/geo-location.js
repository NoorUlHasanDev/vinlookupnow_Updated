(function (root) {
  'use strict';
  function normalizeCountry(value) {
    const country = String(value || '').trim().toUpperCase();
    if (country === 'UK') return 'GB';
    return /^[A-Z]{2}$/.test(country) && !['XX','ZZ'].includes(country) ? country : '';
  }
  async function lookup(fetcher, url, timeout) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const response = await fetcher(url, {cache:'no-store', credentials:'omit', signal:controller.signal});
      if (!response.ok) throw new Error('HTTP_' + response.status);
      const data = await response.json();
      const country = normalizeCountry(data.country_code || data.country);
      if (data.error || data.success === false || !country) throw new Error('NO_COUNTRY');
      return country;
    } finally { clearTimeout(timer); }
  }
  async function detect(fetcher, timeout = 3000) {
    for (const [source,url] of [['country.is','https://api.country.is/'],['ipapi.co','https://ipapi.co/json/']]) {
      try { return {country:await lookup(fetcher,url,timeout),source,status:'detected'}; }
      catch (error) { /* Try the next independent provider. */ }
    }
    return {country:'',source:'unavailable',status:'unavailable'};
  }
  function market(country, config) {
    country = normalizeCountry(country);
    const currency = (config.countries || {})[country] || 'USD';
    return {country,currency,symbol:(config.symbols || {})[currency] || '$'};
  }
  function sdkUrl(clientId, currency, mode, country) {
    const url = new URL('https://www.paypal.com/sdk/js');
    Object.entries({'client-id':clientId,currency,intent:'capture',components:'buttons,card-fields',
      'enable-funding':'paylater,card',commit:'true'}).forEach(([key,value]) => url.searchParams.set(key,value));
    // Locale is a presentation hint, not a promise to override a hosted billing form.
    const locales = {US:'en_US',GB:'en_GB',CA:'en_CA',AU:'en_AU',NZ:'en_NZ',IE:'en_IE'};
    if (locales[country]) url.searchParams.set('locale',locales[country]);
    if (mode === 'sandbox' && locales[country]) url.searchParams.set('buyer-country',country);
    return url.toString();
  }
  root.VinGeo = {normalizeCountry,detect,market,sdkUrl};
  if (typeof module !== 'undefined' && module.exports) module.exports = root.VinGeo;
  if (root.document) {
    // Share one request sequence across prices, checkout and billing; do not cache location.
    root.VinGeoReady = detect(root.fetch.bind(root)).then(result => {
      if (result.country) {
        root.VinDetectedCountry = result.country;
        root.dispatchEvent(new CustomEvent('vin-country-detected',{detail:{country:result.country}}));
      }
      root.VinLocationState = result;
      return result;
    });
  }
})(typeof window !== 'undefined' ? window : globalThis);
