import {useState,useEffect,useMemo,useRef,useCallback} from 'react';
import {satellites,periodDate,periodIndex,parseCSV,parseDataset,assignDistricts,districtName,selectObservations,selectedEstimate,verdict,passSummary,toCSV,validateBoundaries} from './data.js';
import {readSaved,saveDataset} from './storage.js';
import {camera,stopOrbit,color} from './map.js';
const now=new Date();
const initial={year:now.getUTCFullYear(),period:periodIndex(now),area:'Bangladesh',satellite:null,lens:'raw',view:'sky',camera:'overview',grounded:false,includeLow:false,includeExcluded:false,playing:false,speed:1};
export function download(content,name,type){const link=document.createElement('a');link.href=URL.createObjectURL(new Blob([content],{type}));link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000);}
async function request(url,options){const response=await fetch(url,options);if(!response.ok){let message;try{message=(await response.json()).error;}catch{}throw Error(message||`Data request failed (${response.status}).`);}return response.json();}
function workspaceQuery(id,state){return new URLSearchParams({dataset:id,year:String(state.year),period:String(state.period),area:state.area,satellite:state.satellite||'',grounded:String(state.grounded),includeLow:String(state.includeLow),includeExcluded:String(state.includeExcluded)}).toString();}
const emptySelection={rows:[],stats:[],passes:[],estimate:null,fleet:{kept:0,total:0,rawRetention:null,held:0,adjustedRetention:null},evidence:{satelliteCounts:{},lowConfidenceCount:0,excludedCount:0}};
export function useOverpass(notify){
  const[state,setState]=useState(initial),[dataset,setDataset]=useState({observations:[],estimates:[],provenance:'No dataset loaded'}),[boundaries,setBoundaries]=useState(null),[loading,setLoading]=useState(true),[error,setError]=useState('');
  const[remoteMode,setRemoteMode]=useState(false),[remoteResult,setRemoteResult]=useState(null),[remoteCalendar,setRemoteCalendar]=useState(null);
  const boundaryRef=useRef(null);boundaryRef.current=boundaries;
  const update=useCallback(change=>setState(s=>({...s,...(typeof change==='function'?change(s):change)})),[]);
  const applyData=useCallback(async(data,geo=boundaryRef.current,assign=true)=>{
    setRemoteMode(false);setRemoteResult(null);setRemoteCalendar(null);
    const active={...data,estimates:data.estimates||[],observations:assign?assignDistricts(data.observations,geo):data.observations};
    setDataset(active);if(geo)setBoundaries(geo);
    const available=[...active.observations,...active.estimates];let latest=null;if(available.length)latest=available.reduce((a,b)=>a.year*46+a.period>b.year*46+b.period?a:b);
    setState(s=>({...s,year:latest?.year||s.year,period:latest?.period??s.period,satellite:null,grounded:false,area:'Bangladesh',lens:'raw',playing:false}));setError('');setLoading(false);
    try{await saveDataset({...active,districts:geo});}catch{notify('Dataset loaded. Browser storage is unavailable; this session keeps it in memory.');}
  },[notify]);
  const applyManifest=useCallback(async manifest=>{
    const geo=await request(`/api/workspace/boundaries?dataset=${encodeURIComponent(manifest.id)}`).catch(()=>null);
    setDataset({...manifest,observations:[],estimates:[]});setBoundaries(geo);setRemoteMode(true);setRemoteResult(null);setRemoteCalendar(null);
    setState(s=>({...s,year:manifest.latest?.year||s.year,period:manifest.latest?.period??s.period,satellite:null,grounded:false,area:'Bangladesh',lens:'raw',playing:false}));
    setError('');setLoading(false);try{localStorage.setItem('afterglow-workspace',manifest.id);}catch{}
  },[]);
  const refresh=useCallback(async()=>{update({playing:false});setLoading(true);setError('');try{const manifest=await request('/api/workspace/refresh',{method:'POST'});await applyManifest(manifest);notify(manifest.warnings?.length?'Loaded available feeds. '+manifest.warnings.join(' '):`Loaded ${manifest.observationCount} NASA FIRMS observations.`);}catch(e){if(remoteMode){setLoading(false);setError(e.message);notify(e.message);return;}try{const geo=await request('./data/districts.geojson').catch(()=>boundaryRef.current);const saved=await request('./data/latest.json');await applyData({...saved,stale:true},geo);notify('Using the saved NASA dataset. Refresh with the local server to update.');}catch{setLoading(false);setError(e.message);notify(e.message);}}},[applyData,applyManifest,notify,update,remoteMode]);
  useEffect(()=>{let cancelled=false;(async()=>{
    try{let id;try{id=localStorage.getItem('afterglow-workspace');}catch{}const manifest=await request(`/api/workspace/manifest?dataset=${encodeURIComponent(id||'default')}`).catch(()=>request('/api/workspace/manifest'));if(!cancelled){await applyManifest(manifest);return;}}
    catch{}
    try{const saved=await readSaved();if(saved&&!cancelled){await applyData(saved,saved.districts);return;}}catch{}
    if(!cancelled){try{const geo=await request('./data/districts.geojson').catch(()=>null),saved=await request('./data/latest.json');await applyData({...saved,stale:true},geo);}catch(e){setLoading(false);setError(e.message);}}
  })();return()=>{cancelled=true;};},[applyData,applyManifest]);
  const query=useMemo(()=>workspaceQuery(dataset.id||'default',state),[dataset.id,state.year,state.period,state.area,state.satellite,state.grounded,state.includeLow,state.includeExcluded]);
  useEffect(()=>{if(!remoteMode)return;const controller=new AbortController();setError('');
    request(`/api/workspace/selection?${query}`,{signal:controller.signal}).then(value=>setRemoteResult({query,value})).catch(e=>{if(e.name!=='AbortError'){setError(e.message);setRemoteResult({query,value:emptySelection});}});
    return()=>controller.abort();
  },[remoteMode,query]);
  const calendarKey=JSON.stringify([dataset.id,state.area,state.satellite,state.grounded,state.includeLow,state.includeExcluded]);
  useEffect(()=>{if(!remoteMode||state.view!=='grid')return;const controller=new AbortController();
    request(`/api/workspace/calendar?${query}`,{signal:controller.signal}).then(value=>setRemoteCalendar({key:calendarKey,value})).catch(e=>{if(e.name!=='AbortError'){setError(e.message);setRemoteCalendar({key:calendarKey,value:{counts:[],models:[],years:dataset.years||[]}});}});
    return()=>controller.abort();
  },[remoteMode,state.view,calendarKey]);
  const activeSelection=remoteResult?.query===query?remoteResult.value:emptySelection;
  const queryLoading=loading||(remoteMode&&remoteResult?.query!==query);
  const calendarData=remoteCalendar?.key===calendarKey?remoteCalendar.value:{counts:[],models:[],years:dataset.years||[]};
  const calendar=useMemo(()=>({counts:new Map(calendarData.counts),models:new Map(calendarData.models.map(key=>[key,true]))}),[remoteCalendar,calendarKey]);
  const maxYear=useMemo(()=>remoteMode?dataset.maxYear:[...dataset.observations,...dataset.estimates].reduce((max,r)=>Math.max(max,r.year),Math.max(2026,now.getUTCFullYear())),[dataset,remoteMode]);
  useEffect(()=>{if(!state.playing)return;const interval=setInterval(()=>setState(s=>s.period===45?{...s,playing:false}:{...s,period:s.period+1}),600/state.speed);return()=>clearInterval(interval);},[state.playing,state.speed]);
  const areaNames=useMemo(()=>remoteMode?dataset.areaNames:['Bangladesh',...[...new Set([...(boundaries?.features.map(districtName)||[]),...dataset.observations.map(r=>r.district).filter(Boolean),...dataset.estimates.map(e=>e.district)])].filter(n=>n!=='Bangladesh').sort((a,b)=>a.localeCompare(b))],[dataset,boundaries,remoteMode]);
  const rows=useMemo(()=>remoteMode?activeSelection.rows:selectObservations(dataset.observations,state),[dataset,state,remoteMode,activeSelection]);
  const allRows=useMemo(()=>selectObservations(dataset.observations,state,{allSatellites:true,includeRemoved:true}),[dataset,state]);
  const estimate=useMemo(()=>remoteMode?activeSelection.estimate:selectedEstimate(dataset.estimates,state),[dataset,state,remoteMode,activeSelection]);
  const stats=useMemo(()=>(remoteMode?activeSelection.stats:areaNames.filter(name=>name!=='Bangladesh').map(name=>{const s={...state,area:name},records=selectObservations(dataset.observations,s);return{name,count:records.length,estimate:selectedEstimate(dataset.estimates,s)};})).map(row=>({...row,color:color(state.lens==='coverage'?row.estimate?.coverage??0:state.lens==='adjusted'?row.estimate?.probability??0:row.count,state.lens)})).sort((a,b)=>state.lens==='adjusted'?(b.estimate?.probability??-1)-(a.estimate?.probability??-1):b.count-a.count),[dataset,state,areaNames,remoteMode,activeSelection]);
  const passes=useMemo(()=>remoteMode?activeSelection.passes:satellites.map(s=>({...s,...passSummary(allRows,s.name),off:state.grounded&&s.retiring})),[allRows,state.grounded,remoteMode,activeSelection]);
  const date=periodDate(state.year,state.period);
  let headline,detail;
  if(queryLoading){headline='Loading the satellite fire record';detail='Connecting to real observations from NASA FIRMS.';}
  else if(error&&!dataset.observations.length){headline='Connect your satellite fire record';detail=error+' Import a FIRMS CSV to continue.';}
  else if(state.lens==='adjusted'&&estimate){headline=`${state.area} · ${verdict(estimate).toLowerCase()}`;detail=`Adjusted activity ${estimate.value} [${estimate.lower}–${estimate.upper}] · baseline median ${estimate.baselineMedian} · Pr(unusual) ${estimate.probability.toFixed(2)} · clear view ${estimate.coverage}%`;}
  else if(state.lens==='coverage'&&estimate){headline=`${state.area} · ${estimate.coverage}% clear-view coverage`;detail=estimate.coverage<30?'Insufficient clear view to judge burning.':'Coverage from the imported model output.';}
  else{headline=`${rows.length} satellite detection${rows.length===1?'':'s'} in ${state.area}`;detail=state.grounded?'Fleet removal simulation: Terra, Aqua, and S-NPP omitted.':rows.length?'Raw observations. A calibrated baseline is needed to assess unusual burning.':'No detections in the loaded record. This is not evidence of no fire.';}
  if(state.grounded&&state.lens==='adjusted'&&!estimate)detail='No grounded model output supplied for this area and period.';
  const fleet=useMemo(()=>{if(remoteMode)return activeSelection.fleet;const kept=selectObservations(dataset.observations,{...state,satellite:null}).length,total=selectObservations(dataset.observations,{...state,grounded:false,satellite:null}).length,held=dataset.estimates.filter(e=>e.year>=2023&&e.year<=2026&&e.grounded&&e.coverage>=30);return{kept,total,rawRetention:total?Math.round(kept/total*100):null,held:held.length,adjustedRetention:held.length?Math.round(held.filter(e=>verdict(e)===verdict({...e,...e.grounded})).length/held.length*100):null};},[dataset,state,remoteMode,activeSelection]);
  const evidence=useMemo(()=>{if(remoteMode)return activeSelection.evidence;const all=selectObservations(dataset.observations,{...state,includeLow:true,includeExcluded:true},{includeRemoved:true});return{satelliteCounts:Object.fromEntries(satellites.map(s=>[s.name,all.filter(r=>r.satellite===s.name).length])),lowConfidenceCount:all.filter(r=>r.lowConfidence).length,excludedCount:all.filter(r=>r.excluded).length};},[remoteMode,activeSelection,dataset,state]);
  const selectArea=useCallback(name=>{stopOrbit();update({area:name,satellite:null,playing:false});camera('fit',boundaryRef.current,name);},[update]);
  const step=useCallback(delta=>{stopOrbit();update(s=>{let year=s.year,period=s.period+delta;if(period<0){year=Math.max(2003,year-1);period=45;}else if(period>45){year=Math.min(maxYear,year+1);period=0;}return{year,period,playing:false};});},[update,maxYear]);
  const play=useCallback(()=>{if(matchMedia('(prefers-reduced-motion: reduce)').matches){step(1);return;}update(s=>({playing:!s.playing}));},[update,step]);
  const importFile=useCallback(async(file)=>{try{if(file.size>50*1024*1024)throw Error('This file exceeds 50 MB. Split it into smaller datasets.');if(remoteMode){setLoading(true);update({playing:false});const manifest=await request(`/api/workspace/import?dataset=${encodeURIComponent(dataset.id)}&name=${encodeURIComponent(file.name)}`,{method:'POST',body:file});await applyManifest(manifest);notify(`Loaded ${manifest.observationCount} observations${manifest.rejected?' · '+manifest.rejected+' invalid rows skipped':''}.`);return;}const text=await file.text();if(file.name.endsWith('.geojson')){const geo=validateBoundaries(JSON.parse(text));await applyData(dataset,geo);notify('District boundaries loaded.');return;}const parsed=file.name.endsWith('.csv')?{...parseCSV(text),estimates:[],provenance:file.name}:parseDataset(text);await applyData({...parsed,imported:true,scope:'Imported dataset'},parsed.districts||boundaryRef.current);notify(`Loaded ${parsed.observations.length} observations${parsed.rejected?' · '+parsed.rejected+' invalid rows skipped':''}.`);}catch(e){setLoading(false);notify('Import failed: '+e.message);}},[applyData,applyManifest,dataset,notify,remoteMode,update]);
  const serverDownload=useCallback(async(route,name,type)=>{try{const response=await fetch(`/api/workspace/${route}?${query}`);if(!response.ok)throw Error((await response.json()).error||'Export failed.');download(await response.text(),name,type);}catch(e){notify(e.message);}},[query,notify]);
  const exportCSV=useCallback(()=>{if(remoteMode)return serverDownload('export.csv',`afterglow-${state.year}-p${state.period+1}.csv`,'text/csv');download(toCSV(rows),`afterglow-${state.year}-p${state.period+1}.csv`,'text/csv');notify(`Exported ${rows.length} observations.`);},[rows,state.year,state.period,notify,remoteMode,serverDownload]);
  const exportEvidence=useCallback(()=>{if(remoteMode)return serverDownload('evidence.json','afterglow-evidence.json','application/json');download(JSON.stringify({version:1,selection:state,provenance:dataset.provenance,fetchedAt:dataset.fetchedAt,observations:rows,estimates:estimate?[estimate]:[],warnings:dataset.warnings||[]},null,2),'afterglow-evidence.json','application/json');},[state,dataset,rows,estimate,remoteMode,serverDownload]);
  return{state,update,dataset,boundaries,loading:queryLoading,error,maxYear,areaNames,rows,allRows,estimate,stats,passes,date,headline,detail,fleet,evidence,remoteMode,calendar,calendarYears:calendarData.years,calendarLoading:remoteMode&&remoteCalendar?.key!==calendarKey,hasEstimates:remoteMode?dataset.hasEstimates:dataset.estimates.length>0,refresh,selectArea,step,play,importFile,exportCSV,exportEvidence};
}
