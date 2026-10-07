import {useState,useEffect,useMemo,useRef,useCallback} from 'react';
import {satellites,periodDate,periodIndex,parseCSV,parseDataset,assignDistricts,districtName,selectObservations,selectedEstimate,verdict,passSummary,toCSV,validateBoundaries} from './data.js';
import {readSaved,saveDataset} from './storage.js';
import {camera,stopOrbit,color} from './map.js';
const now=new Date();
const initial={year:now.getUTCFullYear(),period:periodIndex(now),area:'Bangladesh',satellite:null,lens:'raw',view:'sky',camera:'overview',grounded:false,includeLow:false,includeExcluded:false,playing:false,speed:1};
export function download(content,name,type){const link=document.createElement('a');link.href=URL.createObjectURL(new Blob([content],{type}));link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000);}
async function request(url){const response=await fetch(url);if(!response.ok){let message;try{message=(await response.json()).error;}catch{}throw Error(message||`Data request failed (${response.status}).`);}return response.json();}
export function useOverpass(notify){
  const[state,setState]=useState(initial),[dataset,setDataset]=useState({observations:[],estimates:[],provenance:'No dataset loaded'}),[boundaries,setBoundaries]=useState(null),[loading,setLoading]=useState(true),[error,setError]=useState('');
  const boundaryRef=useRef(null);boundaryRef.current=boundaries;
  const update=useCallback(change=>setState(s=>({...s,...(typeof change==='function'?change(s):change)})),[]);
  const applyData=useCallback(async(data,geo=boundaryRef.current)=>{
    const active={...data,estimates:data.estimates||[],observations:assignDistricts(data.observations,geo)};
    setDataset(active);if(geo)setBoundaries(geo);
    const available=[...active.observations,...active.estimates];let latest=null;if(available.length)latest=available.reduce((a,b)=>a.year*46+a.period>b.year*46+b.period?a:b);
    setState(s=>({...s,year:latest?.year||s.year,period:latest?.period??s.period,satellite:null,grounded:false,area:'Bangladesh',lens:'raw',playing:false}));setError('');setLoading(false);
    try{await saveDataset({...active,districts:geo});}catch{notify('Dataset loaded. Browser storage is unavailable; this session keeps it in memory.');}
  },[notify]);
  const refresh=useCallback(async()=>{update({playing:false});setLoading(true);setError('');try{const geo=await request('/api/boundaries').catch(()=>boundaryRef.current);const data=await request('/api/firms');await applyData(data,geo);notify(data.warnings?.length?'Loaded available feeds. '+data.warnings.join(' '):`Loaded ${data.observations.length} NASA FIRMS observations.`);}catch(e){try{const geo=await request('./data/districts.geojson').catch(()=>boundaryRef.current);const saved=await request('./data/latest.json');await applyData({...saved,stale:true},geo);notify('Using the saved NASA dataset. Refresh with the local server to update.');}catch{setLoading(false);setError(e.message);notify(e.message);}}},[applyData,notify,update]);
  useEffect(()=>{let cancelled=false;(async()=>{try{const saved=await readSaved();if(saved&&!cancelled){await applyData(saved,saved.districts);return;}}catch{}if(!cancelled)await refresh();})();return()=>{cancelled=true;};},[applyData,refresh]);
  const maxYear=useMemo(()=>[...dataset.observations,...dataset.estimates].reduce((max,r)=>Math.max(max,r.year),Math.max(2026,now.getUTCFullYear())),[dataset]);
  useEffect(()=>{if(!state.playing)return;const interval=setInterval(()=>setState(s=>s.period===45?{...s,playing:false}:{...s,period:s.period+1}),600/state.speed);return()=>clearInterval(interval);},[state.playing,state.speed]);
  const areaNames=useMemo(()=>['Bangladesh',...[...new Set([...(boundaries?.features.map(districtName)||[]),...dataset.observations.map(r=>r.district).filter(Boolean),...dataset.estimates.map(e=>e.district)])].filter(n=>n!=='Bangladesh').sort((a,b)=>a.localeCompare(b))],[dataset,boundaries]);
  const rows=useMemo(()=>selectObservations(dataset.observations,state),[dataset,state]);
  const allRows=useMemo(()=>selectObservations(dataset.observations,state,{allSatellites:true,includeRemoved:true}),[dataset,state]);
  const estimate=useMemo(()=>selectedEstimate(dataset.estimates,state),[dataset,state]);
  const stats=useMemo(()=>areaNames.filter(name=>name!=='Bangladesh').map(name=>{const s={...state,area:name},records=selectObservations(dataset.observations,s),e=selectedEstimate(dataset.estimates,s);return{name,count:records.length,estimate:e,color:color(state.lens==='coverage'?e?.coverage??0:state.lens==='adjusted'?e?.probability??0:records.length,state.lens)};}).sort((a,b)=>state.lens==='adjusted'?(b.estimate?.probability??-1)-(a.estimate?.probability??-1):b.count-a.count),[dataset,state,areaNames]);
  const annualCounts=useMemo(()=>{const counts=new Map();for(const r of dataset.observations){if(r.year!==state.year||(state.satellite&&r.satellite!==state.satellite)||(state.grounded&&satellites.find(s=>s.name===r.satellite)?.retiring)||(!state.includeLow&&r.lowConfidence)||(!state.includeExcluded&&r.excluded))continue;const key=`${r.district}|${r.period}`;counts.set(key,(counts.get(key)||0)+1);}return counts;},[dataset,state.year,state.satellite,state.grounded,state.includeLow,state.includeExcluded]);
  const passes=useMemo(()=>satellites.map(s=>({...s,...passSummary(allRows,s.name),off:state.grounded&&s.retiring})),[allRows,state.grounded]);
  const date=periodDate(state.year,state.period);
  let headline,detail;
  if(loading){headline='Loading the satellite fire record';detail='Connecting to real observations from NASA FIRMS.';}
  else if(error&&!dataset.observations.length){headline='Connect your satellite fire record';detail=error+' Import a FIRMS CSV to continue.';}
  else if(state.lens==='adjusted'&&estimate){headline=`${state.area} · ${verdict(estimate).toLowerCase()}`;detail=`Adjusted activity ${estimate.value} [${estimate.lower}–${estimate.upper}] · baseline median ${estimate.baselineMedian} · Pr(unusual) ${estimate.probability.toFixed(2)} · clear view ${estimate.coverage}%`;}
  else if(state.lens==='coverage'&&estimate){headline=`${state.area} · ${estimate.coverage}% clear-view coverage`;detail=estimate.coverage<30?'Insufficient clear view to judge burning.':'Coverage from the imported model output.';}
  else{headline=`${rows.length} satellite detection${rows.length===1?'':'s'} in ${state.area}`;detail=state.grounded?'Fleet removal simulation: Terra, Aqua, and S-NPP omitted.':rows.length?'Raw observations. A calibrated baseline is needed to assess unusual burning.':'No detections in the loaded record. This is not evidence of no fire.';}
  if(state.grounded&&state.lens==='adjusted'&&!estimate)detail='No grounded model output supplied for this area and period.';
  const fleet=useMemo(()=>{const kept=selectObservations(dataset.observations,{...state,satellite:null}).length,total=selectObservations(dataset.observations,{...state,grounded:false,satellite:null}).length,held=dataset.estimates.filter(e=>e.year>=2023&&e.year<=2026&&e.grounded&&e.coverage>=30);return{kept,total,rawRetention:total?Math.round(kept/total*100):null,held:held.length,adjustedRetention:held.length?Math.round(held.filter(e=>verdict(e)===verdict({...e,...e.grounded})).length/held.length*100):null};},[dataset,state]);
  const selectArea=useCallback(name=>{stopOrbit();update({area:name,satellite:null,playing:false});camera('fit',boundaryRef.current,name);},[update]);
  const step=useCallback(delta=>{stopOrbit();update(s=>{let year=s.year,period=s.period+delta;if(period<0){year=Math.max(2003,year-1);period=45;}else if(period>45){year=Math.min(maxYear,year+1);period=0;}return{year,period,playing:false};});},[update,maxYear]);
  const play=useCallback(()=>{if(matchMedia('(prefers-reduced-motion: reduce)').matches){step(1);return;}update(s=>({playing:!s.playing}));},[update,step]);
  const importFile=useCallback(async(file)=>{try{if(file.size>50*1024*1024)throw Error('This file exceeds 50 MB. Split it into smaller datasets.');const text=await file.text();if(file.name.endsWith('.geojson')){const geo=validateBoundaries(JSON.parse(text));await applyData(dataset,geo);notify('District boundaries loaded.');return;}const parsed=file.name.endsWith('.csv')?{...parseCSV(text),estimates:[],provenance:file.name}:parseDataset(text);await applyData({...parsed,imported:true,scope:'Imported dataset'},parsed.districts||boundaryRef.current);notify(`Loaded ${parsed.observations.length} observations${parsed.rejected?' · '+parsed.rejected+' invalid rows skipped':''}.`);}catch(e){notify('Import failed: '+e.message);}},[applyData,dataset,notify]);
  const exportCSV=useCallback(()=>{download(toCSV(rows),`afterglow-${state.year}-p${state.period+1}.csv`,'text/csv');notify(`Exported ${rows.length} observations.`);},[rows,state.year,state.period,notify]);
  const exportEvidence=useCallback(()=>download(JSON.stringify({version:1,selection:state,provenance:dataset.provenance,fetchedAt:dataset.fetchedAt,observations:rows,estimates:estimate?[estimate]:[],warnings:dataset.warnings||[]},null,2),'afterglow-evidence.json','application/json'),[state,dataset,rows,estimate]);
  return{state,update,dataset,boundaries,loading,error,maxYear,areaNames,rows,allRows,estimate,stats,passes,annualCounts,date,headline,detail,fleet,refresh,selectArea,step,play,importFile,exportCSV,exportEvidence};
}
