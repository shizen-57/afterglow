import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {mkdtemp,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve,join,basename} from 'node:path';
import {indexDataset,createWorkspaceStore,workspaceHandler,querySelection} from '../lib/workspace.mjs';
import {normalizeObservation,selectObservations,selectedEstimate,calendarSummary,passSummary,parseCSV} from '../src/data.js';

const base={latitude:23,longitude:91,acq_date:'2024-01-01',acq_time:'0045',confidence:'nominal',frp:12};
const observations=[
  ...['Terra','Aqua','S-NPP','NOAA-20','NOAA-21'].map(satellite=>normalizeObservation({...base,satellite,district:'Sylhet'})),
  normalizeObservation({...base,satellite:'NOAA-20',district:'Sylhet',latitude:23.1,confidence:'low'}),
  normalizeObservation({...base,satellite:'NOAA-20',district:'Dhaka',latitude:23.2,excluded:true}),
  normalizeObservation({...base,satellite:'NOAA-20',district:'Dhaka',latitude:23.3,acq_time:''}),
  normalizeObservation({...base,satellite:'NOAA-20',district:'Sylhet',acq_date:'2023-12-31'}),
];
const model={year:2024,period:0,value:10,lower:5,upper:15,coverage:60,probability:.9,baselineMedian:4,grounded:{value:4,lower:2,upper:8,probability:.2}};
const data={version:1,observations,estimates:['Bangladesh','Sylhet','Dhaka'].map(district=>({...model,district})),provenance:'Test fixture'};

test('server period queries preserve every filter, district estimate, pass and fleet count',()=>{
  const workspace=indexDataset(data,null);
  for(const area of ['Bangladesh','Sylhet'])for(const grounded of [false,true])for(const satellite of [null,'NOAA-20','Terra'])for(const includeLow of [false,true])for(const includeExcluded of [false,true]){
    const state={year:2024,period:0,area,grounded,satellite,includeLow,includeExcluded},selected=workspace.selection(state);
    assert.deepEqual(selected.rows,selectObservations(observations,state));
    assert.deepEqual(selected.estimate,selectedEstimate(data.estimates,state)||null);
    for(const row of selected.stats){assert.equal(row.count,selectObservations(observations,{...state,area:row.name}).length);assert.deepEqual(row.estimate,selectedEstimate(data.estimates,{...state,area:row.name})||null);}
    const all=selectObservations(observations,state,{allSatellites:true,includeRemoved:true});
    for(const pass of selected.passes)assert.deepEqual(passSummary(all,pass.name),Object.fromEntries(['count','days','time','times','frp'].map(k=>[k,pass[k]])));
    assert.equal(selected.fleet.total,selectObservations(observations,{...state,grounded:false,satellite:null}).length);
    assert.equal(selected.fleet.kept,selectObservations(observations,{...state,satellite:null}).length);
    assert.equal(selected.fleet.adjustedRetention,0);
    const source=selectObservations(observations,{...state,includeLow:true,includeExcluded:true},{includeRemoved:true});
    assert.equal(selected.evidence.lowConfidenceCount,source.filter(r=>r.lowConfidence).length);
    assert.equal(selected.evidence.excludedCount,source.filter(r=>r.excluded).length);
    for(const [name,count] of Object.entries(selected.evidence.satelliteCounts))assert.equal(count,source.filter(r=>r.satellite===name).length);
    const expected=calendarSummary(observations,data.estimates,state),calendar=workspace.calendar(state);
    assert.deepEqual(calendar.counts,[...expected.counts]);
    assert.deepEqual(calendar.models,[...expected.models].filter(([,e])=>e).map(([key])=>key));
  }
});

test('metadata and period results never contain the full archive; missing years remain empty',()=>{
  const workspace=indexDataset(data,null),state={year:2024,period:0,area:'Bangladesh'};
  assert.equal(workspace.manifest.observationCount,9);assert.equal(workspace.manifest.estimateCount,3);
  assert.equal(workspace.manifest.observations,undefined);assert.equal(workspace.manifest.estimates,undefined);
  assert.deepEqual(workspace.manifest.latest,{year:2024,period:0});
  assert.ok(workspace.selection(state).rows.every(r=>r.year===2024&&r.period===0));
  assert.deepEqual(workspace.selection({...state,year:2026}).rows,[]);assert.equal(workspace.selection({...state,year:2026}).estimate,null);
});

test('invalid query parameters are rejected before reading the archive',()=>{
  const params=new URLSearchParams({year:'2024',period:'0',area:'Sylhet'});
  assert.equal(querySelection(params,['Bangladesh','Sylhet']).area,'Sylhet');
  for(const [key,value] of [['year','NaN'],['year','2002'],['period','46'],['period','0.5'],['area','Unknown'],['satellite','Unknown'],['grounded','yes']]){const invalid=new URLSearchParams(params);invalid.set(key,value);assert.throws(()=>querySelection(invalid,['Bangladesh','Sylhet']));}
});

async function setup(t){
  const folder=await mkdtemp(join(tmpdir(),'afterglow-query-'));
  t.after(async()=>{assert.equal(resolve(folder).startsWith(resolve(tmpdir())+ (process.platform==='win32'?'\\':'/')),true);assert.ok(basename(folder).startsWith('afterglow-query-'));await rm(folder,{recursive:true,force:true});});
  const modelPath=join(folder,'model.json'),cacheDir=join(folder,'workspaces');await writeFile(modelPath,JSON.stringify(data));
  const options={modelPath,cacheDir,boundaries:async()=>null,fires:async()=>({...data,estimates:[],scope:'Live fixture'})};
  const store=createWorkspaceStore(options);return{folder,options,store};
}

test('server imports persist, survive reload and cannot read arbitrary filesystem paths',async t=>{
  const {store,options}=await setup(t),csv='latitude,longitude,acq_date,acq_time,satellite\n23,91,2024-01-01,0045,N20';
  const imported=await store.importFile(csv,'actual.csv');assert.equal(imported.manifest.observationCount,1);assert.equal(imported.manifest.hasEstimates,false);
  const restored=await createWorkspaceStore(options).get(imported.manifest.id);assert.deepEqual(restored.data.observations,imported.data.observations);
  await assert.rejects(()=>store.get('../model'),/Unknown workspace/);
  await assert.rejects(()=>store.importFile('{bad','bad.json'),SyntaxError);
  await assert.rejects(()=>store.importFile(csv,'bad.exe'),/Choose a FIRMS/);
  const refreshed=await store.refresh();assert.equal(refreshed.manifest.hasEstimates,false);assert.notEqual(refreshed.manifest.id,imported.manifest.id);
  assert.equal((await store.get()).manifest.hasEstimates,true);
});

test('real HTTP endpoints deliver compact selections, exports and validation errors',async t=>{
  const {store}=await setup(t),handler=workspaceHandler(store);
  const server=http.createServer(async(req,res)=>{if(!await handler(req,res,new URL(req.url,'http://localhost')))res.writeHead(404).end();});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));t.after(()=>new Promise(resolve=>server.close(resolve)));
  const baseURL=`http://127.0.0.1:${server.address().port}`,query='year=2024&period=0&area=Bangladesh';
  const manifest=await(await fetch(baseURL+'/api/workspace/manifest')).json();assert.equal(manifest.observations,undefined);
  const selected=await(await fetch(baseURL+'/api/workspace/selection?'+query)).json();assert.equal(selected.rows.length,6);
  const exported=await fetch(baseURL+'/api/workspace/export.csv?'+query);assert.match(exported.headers.get('content-disposition'),/attachment/);assert.equal(parseCSV(await exported.text()).observations.length,selected.rows.length);
  const evidence=await(await fetch(baseURL+'/api/workspace/evidence.json?'+query)).json();assert.deepEqual(evidence.observations,selected.rows);assert.equal(evidence.estimates.length,1);
  const calendar=await(await fetch(baseURL+'/api/workspace/calendar?'+query)).json();assert.deepEqual(calendar.years,[2024,2023]);
  assert.equal((await fetch(baseURL+'/api/workspace/selection?year=2024&period=99')).status,400);
  assert.equal((await fetch(baseURL+'/api/workspace/import')).status,405);
  assert.equal((await fetch(baseURL+'/api/workspace/unknown')).status,404);
  const imported=await fetch(baseURL+'/api/workspace/import?name=bad.json',{method:'POST',body:'{bad'});assert.equal(imported.status,400);
});
