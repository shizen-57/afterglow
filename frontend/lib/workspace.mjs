import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {resolve} from 'node:path';
import {randomUUID} from 'node:crypto';
import {satellites,parseDataset,parseCSV,assignDistricts,districtName,validateBoundaries,selectObservations,selectedEstimate,calendarSummary,passSummary,verdict,toCSV} from '../src/data.js';

export function querySelection(params,areaNames){
  const year=Number(params.get('year')),period=Number(params.get('period'));
  const area=params.get('area')||'Bangladesh',satellite=params.get('satellite')||null;
  if(!params.has('year')||!Number.isInteger(year)||year<2003||year>2100)throw Error('Choose a year from 2003 to 2100.');
  if(!params.has('period')||!Number.isInteger(period)||period<0||period>45)throw Error('Choose a period from 0 to 45.');
  if(!areaNames.includes(area))throw Error('Unknown district.');
  if(satellite&&!satellites.some(s=>s.name===satellite))throw Error('Unknown satellite.');
  const flag=name=>{const value=params.get(name);if(value!==null&&!['true','false'].includes(value))throw Error(`Invalid ${name} filter.`);return value==='true';};
  return{year,period,area,satellite,grounded:flag('grounded'),includeLow:flag('includeLow'),includeExcluded:flag('includeExcluded')};
}

// The entire archive stays on the server. Queries inspect one indexed eight-day period.
export function indexDataset(data,geo,id='default'){
  const observations=data.observations||[],estimates=data.estimates||[],periods=new Map(),modelPeriods=new Map();
  let latest=null;const years=new Set();
  for(const row of [...observations,...estimates]){years.add(row.year);if(!latest||row.year*46+row.period>latest.year*46+latest.period)latest={year:row.year,period:row.period};}
  for(const row of observations){const key=`${row.year}|${row.period}`;if(!periods.has(key))periods.set(key,[]);periods.get(key).push(row);}
  for(const row of estimates){const key=`${row.year}|${row.period}`;if(!modelPeriods.has(key))modelPeriods.set(key,[]);modelPeriods.get(key).push(row);}
  const areaNames=['Bangladesh',...[...new Set([...(geo?.features.map(districtName)||[]),...observations.map(r=>r.district).filter(Boolean),...estimates.map(e=>e.district)])].filter(n=>n!=='Bangladesh').sort((a,b)=>a.localeCompare(b))];
  const held=estimates.filter(e=>e.year>=2023&&e.year<=2026&&e.grounded&&e.coverage>=30);
  const adjustedRetention=held.length?Math.round(held.filter(e=>verdict(e)===verdict({...e,...e.grounded})).length/held.length*100):null;
  const {observations:ignoredRows,estimates:ignoredModels,districts:ignoredGeo,...metadata}=data;
  const manifest={...metadata,id,areaNames,years:[...years].sort((a,b)=>b-a),latest,hasEstimates:estimates.length>0,observationCount:observations.length,estimateCount:estimates.length,maxYear:Math.max(new Date().getUTCFullYear(),...years)};
  const calendars=new Map();
  function selection(state){
    const key=`${state.year}|${state.period}`,source=periods.get(key)||[],models=modelPeriods.get(key)||[];
    const rows=selectObservations(source,state),allRows=selectObservations(source,state,{allSatellites:true,includeRemoved:true});
    const evidenceRows=selectObservations(source,{...state,includeLow:true,includeExcluded:true},{includeRemoved:true});
    const kept=selectObservations(source,{...state,satellite:null}).length,total=selectObservations(source,{...state,grounded:false,satellite:null}).length;
    return{rows,estimate:selectedEstimate(models,state)||null,
      stats:areaNames.filter(name=>name!=='Bangladesh').map(name=>{const s={...state,area:name};return{name,count:selectObservations(source,s).length,estimate:selectedEstimate(models,s)||null};}),
      passes:satellites.map(s=>({...s,...passSummary(allRows,s.name),off:state.grounded&&s.retiring})),
      evidence:{satelliteCounts:Object.fromEntries(satellites.map(s=>[s.name,evidenceRows.filter(r=>r.satellite===s.name).length])),lowConfidenceCount:evidenceRows.filter(r=>r.lowConfidence).length,excludedCount:evidenceRows.filter(r=>r.excluded).length},
      fleet:{kept,total,rawRetention:total?Math.round(kept/total*100):null,held:held.length,adjustedRetention}};
  }
  function calendar(state){
    const key=JSON.stringify([state.area,state.satellite,state.grounded,state.includeLow,state.includeExcluded]);
    if(calendars.has(key))return calendars.get(key);
    const {counts,models}=calendarSummary(observations,estimates,state);
    // The calendar needs presence of a model, not every scientific field in the archive.
    const result={counts:[...counts],models:[...models].filter(([,model])=>model).map(([key])=>key),years:manifest.years};
    if(calendars.size>=16)calendars.delete(calendars.keys().next().value);
    calendars.set(key,result);return result;
  }
  return{manifest,geo,data,selection,calendar};
}

export function createWorkspaceStore({modelPath,cacheDir,boundaries,fires}){
  let defaultPromise;const workspaces=new Map(),pending=new Map();
  const remember=(id,workspace)=>{if(workspaces.size>=4)workspaces.delete(workspaces.keys().next().value);workspaces.set(id,workspace);return workspace;};
  async function get(id='default'){
    if(id==='default'){
      if(!defaultPromise)defaultPromise=(async()=>{
        const geo=await boundaries().catch(()=>null);let text;
        try{text=await readFile(modelPath,'utf8');}catch(error){if(error.code!=='ENOENT')throw error;}
        if(text!==undefined){const raw=JSON.parse(text),data={...raw,...parseDataset(text),imported:true,scope:'Afterglow backend model'};return indexDataset(data,data.districts||geo);}
        const data=await fires();return indexDataset({...data,observations:assignDistricts(data.observations,geo)},geo);
      })().catch(error=>{defaultPromise=null;throw error;});
      return defaultPromise;
    }
    if(!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(id))throw Error('Unknown workspace.');
    if(workspaces.has(id)){const active=workspaces.get(id);workspaces.delete(id);workspaces.set(id,active);return active;}
    if(!pending.has(id))pending.set(id,(async()=>{try{const text=await readFile(resolve(cacheDir,id+'.json'),'utf8'),raw=JSON.parse(text),parsed=parseDataset(text);return remember(id,indexDataset({...raw,...parsed},parsed.districts,id));}catch{throw Error('Saved workspace is unavailable. Reload the backend record or import the file again.');}})().finally(()=>pending.delete(id)));
    return pending.get(id);
  }
  async function save(data,geo){
    const id=randomUUID(),workspace=indexDataset(data,geo,id);
    await mkdir(cacheDir,{recursive:true});await writeFile(resolve(cacheDir,id+'.json'),JSON.stringify({...data,version:1,districts:geo}));
    return remember(id,workspace);
  }
  async function importFile(text,name,id='default'){
    const active=await get(id);
    if(name.toLowerCase().endsWith('.geojson')){const geo=validateBoundaries(JSON.parse(text));return save({...active.data,observations:assignDistricts(active.data.observations,geo)},geo);}
    let data;
    if(name.toLowerCase().endsWith('.csv'))data={...parseCSV(text),estimates:[],provenance:name};
    else if(name.toLowerCase().endsWith('.json'))data={...JSON.parse(text),...parseDataset(text)};
    else throw Error('Choose a FIRMS CSV, calibrated JSON, or district GeoJSON file.');
    const geo=data.districts||active.geo;
    return save({...data,observations:assignDistricts(data.observations,geo),imported:true,scope:'Imported dataset'},geo);
  }
  async function refresh(){const geo=await boundaries().catch(()=>null),data=await fires();return save({...data,observations:assignDistricts(data.observations,geo)},geo);}
  return{get,importFile,refresh};
}

async function readUpload(req){
  const limit=50*1024*1024;
  if(Number(req.headers['content-length'])>limit)throw Error('This file exceeds 50 MB. Split it into smaller datasets.');
  const chunks=[];let size=0;
  for await(const chunk of req){size+=chunk.length;if(size>limit)throw Error('This file exceeds 50 MB. Split it into smaller datasets.');chunks.push(chunk);}
  return Buffer.concat(chunks).toString('utf8');
}

export function workspaceHandler(store){return async(req,res,url)=>{
  if(!url.pathname.startsWith('/api/workspace/'))return false;
  const route=url.pathname.slice('/api/workspace/'.length),id=url.searchParams.get('dataset')||'default';
  const json=(status,value)=>res.writeHead(status,{'Content-Type':'application/json','Cache-Control':'no-store'}).end(JSON.stringify(value));
  try{
    if(['import','refresh'].includes(route)){
      if(req.method!=='POST'){json(405,{error:'Use POST for this action.'});return true;}
      const workspace=route==='import'?await store.importFile(await readUpload(req),url.searchParams.get('name')||'',id):await store.refresh();
      json(200,workspace.manifest);return true;
    }
    if(req.method!=='GET'){json(405,{error:'Use GET for this query.'});return true;}
    if(!['manifest','boundaries','selection','calendar','export.csv','evidence.json'].includes(route)){json(404,{error:'Unknown workspace route.'});return true;}
    const workspace=await store.get(id);
    if(route==='manifest'){json(200,workspace.manifest);return true;}
    if(route==='boundaries'){json(200,workspace.geo);return true;}
    const state=querySelection(url.searchParams,workspace.manifest.areaNames);
    if(route==='calendar'){json(200,workspace.calendar(state));return true;}
    const selected=workspace.selection(state);
    if(route==='selection'){json(200,selected);return true;}
    if(route==='export.csv'){res.writeHead(200,{'Content-Type':'text/csv; charset=utf-8','Content-Disposition':`attachment; filename="afterglow-${state.year}-p${state.period+1}.csv"`,'Cache-Control':'no-store'}).end(toCSV(selected.rows));return true;}
    res.writeHead(200,{'Content-Type':'application/json','Content-Disposition':'attachment; filename="afterglow-evidence.json"','Cache-Control':'no-store'}).end(JSON.stringify({version:1,selection:state,provenance:workspace.manifest.provenance,fetchedAt:workspace.manifest.fetchedAt,observations:selected.rows,estimates:selected.estimate?[selected.estimate]:[],warnings:workspace.manifest.warnings||[]},null,2));
  }catch(error){json(400,{error:error.message});}
  return true;
};}
