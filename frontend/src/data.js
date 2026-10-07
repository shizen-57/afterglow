export const satellites = [
  {name:'Terra',sensor:'MODIS',retiring:true}, {name:'NOAA-21',sensor:'VIIRS',retiring:false},
  {name:'NOAA-20',sensor:'VIIRS',retiring:false}, {name:'S-NPP',sensor:'VIIRS',retiring:true}, {name:'Aqua',sensor:'MODIS',retiring:true}
];
export const months=['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'];
export const emptyCollection=()=>({type:'FeatureCollection',features:[]});
export const escapeHTML=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function periodDate(year,period){const start=new Date(Date.UTC(year,0,1+period*8)),end=new Date(Math.min(Date.UTC(year+1,0,1)-86400000,+start+7*86400000));const fmt=d=>d.toLocaleDateString('en-GB',{day:'numeric',month:'short',timeZone:'UTC'});return{start,end,label:`${fmt(start)} – ${fmt(end)} ${year}`,short:`${fmt(start)} – ${fmt(end)}`};}
export function periodIndex(date){const d=new Date(date);return Math.min(45,Math.floor((+d-Date.UTC(d.getUTCFullYear(),0,1))/691200000));}
export function normalizeObservation(r){
  const latitude=Number(r.latitude),longitude=Number(r.longitude);
  if(r.latitude===''||r.longitude===''||!Number.isFinite(latitude)||!Number.isFinite(longitude)||Math.abs(latitude)>90||Math.abs(longitude)>180)throw Error('Invalid coordinates');
  const aliases={T:'Terra',A:'Aqua',N:'S-NPP',NPP:'S-NPP','SUOMI NPP':'S-NPP','S-NPP':'S-NPP','NOAA-20':'NOAA-20',NOAA20:'NOAA-20',J1:'NOAA-20',J2:'NOAA-21',NOAA21:'NOAA-21','NOAA-21':'NOAA-21',TERRA:'Terra',AQUA:'Aqua'};
  aliases.N20='NOAA-20';aliases.N21='NOAA-21';
  const satellite=aliases[String(r.satellite).toUpperCase()];if(!satellite)throw Error('Unsupported satellite');
  const day=String(r.acq_date||r.day||'');if(!/^\d{4}-\d{2}-\d{2}$/.test(day)||!Number.isFinite(Date.parse(day))||new Date(day).toISOString().slice(0,10)!==day)throw Error('Invalid date');
  const suppliedTime=r.acq_time??r.time;
  const acquisitionTimeKnown=r.acquisitionTimeKnown!==false&&suppliedTime!=null&&suppliedTime!=='';
  const time=String(acquisitionTimeKnown?suppliedTime:'0000').padStart(4,'0');if(!/^\d{4}$/.test(time)||+time.slice(0,2)>23||+time.slice(2)>59)throw Error('Invalid time');
  const date=`${day}T${time.slice(0,2)}:${time.slice(2)}:00Z`,frp=r.frp!==''&&r.frp!=null?Number(r.frp):null,confidence=String(r.confidence??'').toLowerCase();
  return{latitude,longitude,satellite,sensor:['Terra','Aqua'].includes(satellite)?'MODIS':'VIIRS',date,day,time,acquisitionTimeKnown,frp:Number.isFinite(frp)?frp:null,confidence,lowConfidence:confidence==='l'||confidence==='low'||(/^\d+$/.test(confidence)&&+confidence<30),district:String(r.district??''),excluded:r.excluded===true||String(r.excluded).toLowerCase()==='true',year:new Date(date).getUTCFullYear(),period:periodIndex(date)};
}
export function deduplicate(rows){return[...new Map(rows.map(r=>[`${r.latitude}|${r.longitude}|${r.satellite}|${r.date}`,r])).values()];}
export function parseCSV(text){
  const rows=[];let row=[],field='',quoted=false;const clean=text.replace(/^\uFEFF/,'');
  for(let i=0;i<clean.length;i++){const c=clean[i];if(c==='"'){if(quoted&&clean[i+1]==='"'){field+='"';i++;}else quoted=!quoted;}else if(c===','&&!quoted){row.push(field);field='';}else if((c==='\n'||c==='\r')&&!quoted){if(c==='\r'&&clean[i+1]==='\n')i++;row.push(field);if(row.some(v=>v.trim()))rows.push(row);row=[];field='';}else field+=c;}
  if(quoted)throw Error('The CSV contains an unclosed quoted field.');if(field||row.length){row.push(field);rows.push(row);}if(!rows.length)throw Error('The CSV is empty.');
  const headers=rows.shift().map(h=>h.trim().toLowerCase());for(const h of ['latitude','longitude','acq_date','satellite'])if(!headers.includes(h))throw Error(`Missing CSV column: ${h}. Use a NASA FIRMS CSV.`);
  const observations=[];let rejected=0;for(const values of rows){if(values.length!==headers.length){rejected++;continue;}try{observations.push(normalizeObservation(Object.fromEntries(headers.map((h,i)=>[h,values[i].trim()]))));}catch{rejected++;}}
  if(rows.length&&!observations.length)throw Error('No valid fire observations found. Check coordinates, dates, and satellite names.');return{observations:deduplicate(observations),rejected};
}
export function parseDataset(text){
  const o=JSON.parse(text);if(o.version!==1||!Array.isArray(o.observations))throw Error('Dataset needs version: 1 and an observations array. See README.');
  const observations=deduplicate(o.observations.map(normalizeObservation));
  const estimates=(o.estimates||[]).map(e=>{if(!e.district||!Number.isInteger(e.year)||e.year<2003||e.year>2100||!Number.isInteger(e.period)||e.period<0||e.period>45)throw Error('Each estimate needs district, year, and period (0–45).');for(const k of ['value','lower','upper','probability','coverage','baselineMedian'])if(!Number.isFinite(e[k]))throw Error(`Estimate requires numeric ${k}.`);if(e.lower<0||e.lower>e.value||e.value>e.upper||e.probability<0||e.probability>1||e.coverage<0||e.coverage>100||e.baselineMedian<0)throw Error('Invalid estimate range, coverage, or probability.');const g=e.grounded;if(g&&(!['value','lower','upper','probability'].every(k=>Number.isFinite(g[k]))||g.lower<0||g.lower>g.value||g.value>g.upper||g.probability<0||g.probability>1))throw Error('Invalid grounded estimate.');return{...e,district:String(e.district)};});
  if(o.districts)validateBoundaries(o.districts);
  return{observations,estimates,districts:o.districts||null,provenance:String(o.provenance||'Imported dataset'),rejected:0};
}
export function pointInRing(p,r){let inside=false;for(let i=0,j=r.length-1;i<r.length;j=i++){const[xi,yi]=r[i],[xj,yj]=r[j];if(((yi>p[1])!==(yj>p[1]))&&(p[0]<(xj-xi)*(p[1]-yi)/(yj-yi)+xi))inside=!inside;}return inside;}
export function pointInGeometry(p,g){const polys=g.type==='Polygon'?[g.coordinates]:g.type==='MultiPolygon'?g.coordinates:[];return polys.some(r=>pointInRing(p,r[0])&&!r.slice(1).some(h=>pointInRing(p,h)));}
export function districtName(f){return String(f.properties?.shapeName||f.properties?.name||f.properties?.district||'Unnamed area');}
export function assignDistricts(rows,boundaries){return rows.map(r=>{const f=boundaries?.features.find(f=>pointInGeometry([r.longitude,r.latitude],f.geometry));return{...r,district:f?districtName(f):r.district};});}
export function selectObservations(rows,s,{allSatellites=false,includeRemoved=false}={}){return rows.filter(r=>r.year===s.year&&r.period===s.period&&(s.area==='Bangladesh'||r.district===s.area)&&(allSatellites||!s.satellite||r.satellite===s.satellite)&&(!s.grounded||includeRemoved||!satellites.find(a=>a.name===r.satellite)?.retiring)&&(s.includeLow||!r.lowConfidence)&&(!r.excluded||s.includeExcluded));}
export function selectedEstimate(estimates,s){if(s.satellite)return null;const e=estimates.find(e=>e.year===s.year&&e.period===s.period&&e.district===s.area);return s.grounded&&e?e.grounded?{...e,...e.grounded}:null:e;}
export function verdict(e){return!e?'Not assessed':e.coverage<30?'Not observed':e.probability>=.8?'Unusually high':e.probability>=.6?'Possibly unusual':'Within usual range';}
export function passSummary(rows,satellite){const own=rows.filter(r=>r.satellite===satellite),dates=[...new Set(own.map(r=>r.day))],times=[...new Set(own.filter(r=>r.acquisitionTimeKnown!==false).map(r=>new Date(r.date).toLocaleTimeString('en-GB',{timeZone:'Asia/Dhaka',hour:'2-digit',minute:'2-digit'})))].sort();return{count:own.length,days:dates.length,time:times[0]||'—',times,frp:own.reduce((sum,r)=>sum+(r.frp||0),0)};}
export function toCSV(rows){const quote=v=>{const s=typeof v==='string'&&/^[=+\-@]/.test(v)?"'"+v:String(v??'');return`"${s.replace(/"/g,'""')}"`;};return[['latitude','longitude','acq_date','acq_time','satellite','instrument','confidence','frp','district','excluded'].join(','),...rows.map(r=>[r.latitude,r.longitude,r.day,r.acquisitionTimeKnown===false?'':r.time,r.satellite,r.sensor,r.confidence,r.frp,r.district,r.excluded].map(quote).join(','))].join('\r\n');}
export function validateBoundaries(geo){
  if(geo?.type!=='FeatureCollection'||!Array.isArray(geo.features))throw Error('Import a GeoJSON FeatureCollection.');
  for(const f of geo.features){const g=f.geometry;if(!g||!['Polygon','MultiPolygon'].includes(g.type)||!Array.isArray(g.coordinates))throw Error('Districts must contain polygon geometries.');const polygons=g.type==='Polygon'?[g.coordinates]:g.coordinates;if(!polygons.length)throw Error('Empty polygon geometry.');for(const rings of polygons){if(!Array.isArray(rings)||!rings.length)throw Error('Missing polygon rings.');for(const ring of rings){if(!Array.isArray(ring)||ring.length<4||ring.some(p=>!Array.isArray(p)||p.length<2||!Number.isFinite(p[0])||!Number.isFinite(p[1])||Math.abs(p[0])>180||Math.abs(p[1])>90))throw Error('Invalid polygon coordinates.');if(ring[0][0]!==ring.at(-1)[0]||ring[0][1]!==ring.at(-1)[1])throw Error('Polygon rings must be closed.');}}}return geo;
}
