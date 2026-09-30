(function (root) {
  'use strict';
  const codes = 'AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW'.split(' ');
  const regions = {
    US: 'AL:Alabama|AK:Alaska|AZ:Arizona|AR:Arkansas|CA:California|CO:Colorado|CT:Connecticut|DE:Delaware|DC:District of Columbia|FL:Florida|GA:Georgia|HI:Hawaii|ID:Idaho|IL:Illinois|IN:Indiana|IA:Iowa|KS:Kansas|KY:Kentucky|LA:Louisiana|ME:Maine|MD:Maryland|MA:Massachusetts|MI:Michigan|MN:Minnesota|MS:Mississippi|MO:Missouri|MT:Montana|NE:Nebraska|NV:Nevada|NH:New Hampshire|NJ:New Jersey|NM:New Mexico|NY:New York|NC:North Carolina|ND:North Dakota|OH:Ohio|OK:Oklahoma|OR:Oregon|PA:Pennsylvania|RI:Rhode Island|SC:South Carolina|SD:South Dakota|TN:Tennessee|TX:Texas|UT:Utah|VT:Vermont|VA:Virginia|WA:Washington|WV:West Virginia|WI:Wisconsin|WY:Wyoming|AS:American Samoa|GU:Guam|MP:Northern Mariana Islands|PR:Puerto Rico|VI:US Virgin Islands',
    CA: 'AB:Alberta|BC:British Columbia|MB:Manitoba|NB:New Brunswick|NL:Newfoundland and Labrador|NS:Nova Scotia|NT:Northwest Territories|NU:Nunavut|ON:Ontario|PE:Prince Edward Island|QC:Quebec|SK:Saskatchewan|YT:Yukon',
    AU: 'ACT:Australian Capital Territory|NSW:New South Wales|NT:Northern Territory|QLD:Queensland|SA:South Australia|TAS:Tasmania|VIC:Victoria|WA:Western Australia'
  };
  function config(country) {
    return {
      regionLabel: country === 'US' ? 'State *' : country === 'CA' ? 'Province / territory *' : country === 'AU' ? 'State / territory *' : country === 'GB' || country === 'IE' ? 'County (optional)' : 'State / province / region (optional)',
      regionRequired: ['US', 'CA', 'AU'].includes(country),
      postalLabel: country === 'US' ? 'ZIP code *' : country === 'GB' ? 'Postcode *' : 'Postal code',
      postalRequired: ['US', 'CA', 'AU', 'NZ', 'GB'].includes(country),
      regions: (regions[country] || '').split('|').filter(Boolean).map(x => x.split(':'))
    };
  }
  function init(doc) {
    const select = doc.getElementById('billing-country');
    const names = typeof Intl.DisplayNames === 'function' ? new Intl.DisplayNames(['en'], {type:'region'}) : null;
    select.replaceChildren(new Option('Select billing country', ''));
    codes.map(code => [code, names ? names.of(code) : code]).sort((a,b) => a[1].localeCompare(b[1]))
      .forEach(([code,name]) => select.add(new Option(name,code)));
    let manuallyChanged = false;
    const updateRegion = () => {
      const c = config(select.value);
      doc.getElementById('billing-region-label').textContent = c.regionLabel;
      doc.getElementById('billing-postal-label').textContent = c.postalLabel;
      const region = doc.getElementById('billing-region');
      region.value = '';
      region.required = c.regionRequired;
      const postal = doc.getElementById('billing-postal');
      postal.value = '';
      postal.required = c.postalRequired;
      doc.getElementById('billing-regions').replaceChildren(...c.regions.map(([code,name]) => { const option = new Option(name,code); return option; }));
    };
    select.addEventListener('change', () => {
      manuallyChanged = true;
      updateRegion();
    });
    const applyDetectedCountry = country => {
      // Location is only a suggestion. Never overwrite the customer's billing choice
      // or clear billing values that were already entered while detection was pending.
      if (manuallyChanged || select.value || !codes.includes(country)) return;
      if (['billing-address','billing-city','billing-region','billing-postal']
          .some(id => doc.getElementById(id).value.trim())) return;
      select.value = country;
      updateRegion();
    };
    if (root.addEventListener) root.addEventListener('vin-country-detected', event => applyDetectedCountry(event.detail.country));
    applyDetectedCountry(root.VinBillingCountry || root.VinDetectedCountry);
  }
  function address(doc) {
    const get = id => doc.getElementById(id).value.trim();
    return {countryCode:get('billing-country'), addressLine1:get('billing-address'),
      adminArea1:get('billing-region'), adminArea2:get('billing-city'), postalCode:get('billing-postal')};
  }
  root.VinCardBilling = {init, address, config};
  if (typeof module !== 'undefined' && module.exports) module.exports = root.VinCardBilling;
})(typeof window !== 'undefined' ? window : globalThis);
