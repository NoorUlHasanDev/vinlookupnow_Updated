(function () {
  'use strict';
  const config = window.VinMarketConfig || {};
  function apply(country, source) {
    const market = window.VinGeo.market(country,config);
    window.VinMarketState = {...market,source};
    document.querySelectorAll('[data-usd-price]').forEach(el => {
      const value = Number(el.dataset.usdPrice).toFixed(2);
      el.textContent = market.currency === 'USD' ? `${market.symbol}${value}` : `${market.symbol}${value} ${market.currency}`;
    });
    document.querySelectorAll('a[href*="/checkout"]').forEach(link => {
      const url = new URL(link.href,location.origin);
      url.searchParams.set('currency',market.currency);
      if (market.country) url.searchParams.set('country',market.country);
      else url.searchParams.delete('country');
      link.href = url.toString();
    });
  }
  const queryCountry = window.VinGeo.normalizeCountry(new URLSearchParams(location.search).get('country'));
  (window.VinGeoReady || Promise.resolve({country:'',status:'unavailable'})).then(result => {
    apply(queryCountry || result.country, queryCountry ? 'checkout-link' : result.source);
  });
})();
