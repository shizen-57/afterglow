import {parseCSV,deduplicate,pointInGeometry} from '../src/data.js';
const base='https://firms.modaps.eosdis.nasa.gov/data/active_fire/';
export const feeds=[
  ['MODIS','modis-c6.1/csv/MODIS_C6_1_South_Asia_7d.csv'],
  ['S-NPP','suomi-npp-viirs-c2/csv/SUOMI_VIIRS_C2_South_Asia_7d.csv'],
  ['NOAA-20','noaa-20-viirs-c2/csv/J1_VIIRS_C2_South_Asia_7d.csv'],
  ['NOAA-21','noaa-21-viirs-c2/csv/J2_VIIRS_C2_South_Asia_7d.csv']
];
async function remote(url){const r=await fetch(url,{signal:AbortSignal.timeout(30000),headers:{'User-Agent':'Afterglow/1.0 (NASA FIRMS data viewer)'}});if(!r.ok)throw Error(`Source returned HTTP ${r.status}`);return r;}
export async function loadBoundaries(){
  const metadata=await(await remote('https://www.geoboundaries.org/api/current/gbOpen/BGD/ADM2/')).json();
  const url=new URL(metadata.simplifiedGeometryGeoJSON||metadata.gjDownloadURL);
  if(!['github.com','raw.githubusercontent.com','www.geoboundaries.org'].includes(url.hostname))throw Error('Unrecognized boundary download host');
  const data=await(await remote(url.href)).json();
  if(data.type!=='FeatureCollection'||!Array.isArray(data.features))throw Error('Invalid boundary data');
  return {...data,attribution:'geoBoundaries gbOpen · Bangladesh ADM2',sourceURL:url.href};
}
export async function loadFires(boundaries){
  const results=await Promise.allSettled(feeds.map(async([name,path])=>{const csv=await(await remote(base+path)).text();const parsed=parseCSV(csv);return{name,...parsed,url:base+path};}));
  const successful=results.filter(r=>r.status==='fulfilled').map(r=>r.value);
  if(!successful.length)throw Error('NASA FIRMS could not be reached. Import a FIRMS CSV or retry.');
  const regional=deduplicate(successful.flatMap(r=>r.observations)).filter(r=>r.latitude>=20.5&&r.latitude<=26.8&&r.longitude>=88&&r.longitude<=92.8);
  const observations=boundaries?regional.filter(r=>boundaries.features.some(f=>pointInGeometry([r.longitude,r.latitude],f.geometry))):regional;
  return {version:1,observations,estimates:[],fetchedAt:new Date().toISOString(),provenance:'NASA FIRMS · near-real-time · last 7 days',scope:boundaries?'Bangladesh district boundaries':'Bangladesh bounding box (includes border areas)',sources:successful.map(r=>({name:r.name,url:r.url,count:r.observations.length,rejected:r.rejected})),warnings:results.flatMap((r,i)=>r.status==='rejected'?[`${feeds[i][0]} unavailable: ${r.reason.message}`]:[])};
}
