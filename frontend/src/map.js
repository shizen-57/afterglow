import {emptyCollection,districtName,escapeHTML,verdict} from './data.js';
import * as maplibre from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
maplibre.setWorkerUrl(workerUrl);
let map,ready=false,pending=null,onSelect,orbitFrame,angle=0;
const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
function color(value,mode){return mode==='coverage'?value<30?'#a1acc3':'#51cabb':mode==='adjusted'?value>=.8?'#e8f889':value>=.6?'#dfb976':'#51cabb':'#56d8cb';}
function bounds(feature){const coords=feature.geometry.type==='Polygon'?feature.geometry.coordinates.flat():feature.geometry.coordinates.flat(2);return coords.reduce((b,[x,y])=>[[Math.min(b[0][0],x),Math.min(b[0][1],y)],[Math.max(b[1][0],x),Math.max(b[1][1],y)]],[[180,90],[-180,-90]]);}
export function initMap(select,failed){
  onSelect=select;
  try{
    map=new maplibre.Map({container:'map',style:'https://tiles.openfreemap.org/styles/dark',center:[91.65,23.2],zoom:7.1,pitch:49,bearing:-19,maxPitch:60,attributionControl:false,canvasContextAttributes:{antialias:true}});
    map.addControl(new maplibre.AttributionControl({compact:true}),'bottom-right');
    map.on('load',()=>{
      ready=true;map.addSource('districts',{type:'geojson',data:emptyCollection()});map.addSource('columns',{type:'geojson',data:emptyCollection()});map.addSource('fires',{type:'geojson',data:emptyCollection()});
      map.addLayer({id:'district-fill',type:'fill',source:'districts',paint:{'fill-color':['get','color'],'fill-opacity':['case',['get','selected'],.12,.025]}});
      map.addLayer({id:'district-lines',type:'line',source:'districts',paint:{'line-color':['case',['get','selected'],'#e8f889','#799bb0'],'line-width':['case',['get','selected'],2,0.65],'line-opacity':.8}});
      map.addLayer({id:'column-base',type:'fill-extrusion',source:'columns',paint:{'fill-extrusion-color':['get','color'],'fill-extrusion-height':['get','height'],'fill-extrusion-opacity':.85}});
      map.addLayer({id:'column-cap',type:'fill-extrusion',source:'columns',paint:{'fill-extrusion-color':['get','color'],'fill-extrusion-base':['get','height'],'fill-extrusion-height':['get','upperHeight'],'fill-extrusion-opacity':.22}});
      map.addLayer({id:'fire-points',type:'circle',source:'fires',paint:{'circle-color':['match',['get','sensor'],'MODIS','#b4a5ed','#5adacb'],'circle-radius':['interpolate',['linear'],['zoom'],5,2,10,4,15,6],'circle-stroke-color':'#071323','circle-stroke-width':1,'circle-opacity':.95}});
      map.on('click','district-fill',e=>{if(e.features?.[0])onSelect(e.features[0].properties.name);});
      map.on('click','fire-points',e=>{const p=e.features[0].properties;new maplibre.Popup().setLngLat(e.lngLat).setHTML(`<strong>${escapeHTML(p.satellite)}</strong><p>${escapeHTML(p.day)} · ${escapeHTML(p.localTime)} Dhaka<br>FRP ${p.frp==='unknown'?'unknown':escapeHTML(p.frp)+' MW'}<br>Confidence ${escapeHTML(p.confidence||'unknown')}</p>`).addTo(map);});
      for(const layer of ['district-fill','fire-points']){map.on('mouseenter',layer,()=>map.getCanvas().style.cursor='pointer');map.on('mouseleave',layer,()=>map.getCanvas().style.cursor='');}
      if(pending)updateMap(...pending);
      document.querySelector('#map-loading').hidden=true;
    });
    let errors=0;map.on('error',()=>{if(!ready&&++errors===1){failed('Basemap could not load. Check your internet connection; the observation calendar still works.');document.querySelector('#map-loading').hidden=true;}});
    map.on('dragstart',stopOrbit);
    map.getCanvas().addEventListener('webglcontextlost',()=>{failed('3D graphics became unavailable. Switched to the calendar.');});
  }catch{failed('WebGL is unavailable. Switched to the accessible calendar.');}
}
export function updateMap(rows,boundaries,stats,state){
  pending=[rows,boundaries,stats,state];if(!ready)return;
  const districtFeatures=(boundaries?.features||[]).map(f=>{const name=districtName(f),stat=stats.find(s=>s.name===name);return{...f,properties:{name,selected:state.area===name,color:stat?.color||'#6da5b5'}};});
  map.getSource('districts').setData({type:'FeatureCollection',features:districtFeatures});
  const columns=stats.filter(s=>s.count>0||s.estimate).flatMap(s=>{const f=boundaries?.features.find(f=>districtName(f)===s.name);if(!f)return[];const b=bounds(f),x=(b[0][0]+b[1][0])/2,y=(b[0][1]+b[1][1])/2,w=.035;const value=state.lens==='adjusted'&&s.estimate?s.estimate.lower:s.count,upper=state.lens==='adjusted'&&s.estimate?s.estimate.upper:value;
    return[{type:'Feature',properties:{name:s.name,color:s.color,height:Math.log10(1+value)*5500,upperHeight:Math.log10(1+upper)*5500},geometry:{type:'Polygon',coordinates:[[[x-w,y-w],[x+w,y-w],[x+w,y+w],[x-w,y+w],[x-w,y-w]]]}}];});
  map.getSource('columns').setData({type:'FeatureCollection',features:columns});
  map.getSource('fires').setData({type:'FeatureCollection',features:rows.map(r=>({type:'Feature',geometry:{type:'Point',coordinates:[r.longitude,r.latitude]},properties:{...r,frp:r.frp??'unknown',localTime:r.acquisitionTimeKnown===false?'Unknown':new Date(r.date).toLocaleTimeString('en-GB',{timeZone:'Asia/Dhaka',hour:'2-digit',minute:'2-digit'})}}))});
  map.setLayoutProperty('column-base','visibility',state.camera==='top'?'none':'visible');map.setLayoutProperty('column-cap','visibility',state.camera==='top'?'none':'visible');
  if(state.lens==='coverage')map.setPaintProperty('fire-points','circle-opacity',.3);else map.setPaintProperty('fire-points','circle-opacity',.95);
}
export function camera(mode,boundaries,area){if(!map)return;stopOrbit();const opts={duration:reduced?0:650};if(mode==='fit'){const feature=boundaries?.features.find(f=>districtName(f)===area);if(feature)map.fitBounds(bounds(feature),{padding:80,...opts});else map.fitBounds([[88,20.5],[92.8,26.8]],{padding:60,...opts});}else if(mode==='top')map.easeTo({pitch:0,bearing:0,...opts});else if(mode==='overview')map.easeTo({pitch:49,bearing:-19,...opts});else if(mode==='orbit'&&!reduced){angle=map.getBearing();const step=()=>{angle+=.04;map.rotateTo(angle,{duration:0});orbitFrame=requestAnimationFrame(step);};step();}}
export function stopOrbit(){cancelAnimationFrame(orbitFrame);}
export function disposeMap(){stopOrbit();map?.remove();map=null;ready=false;pending=null;}
export function resizeMap(){map?.resize();}
export function moveMap(key){if(!map)return;stopOrbit();const motion={duration:reduced?0:150};if(key==='['||key===']')map.rotateTo(map.getBearing()+(key==='['?-15:15),motion);else if(key==='+'||key==='=')map.zoomIn(motion);else if(key==='-')map.zoomOut(motion);else map.panBy(({ArrowLeft:[-80,0],ArrowRight:[80,0],ArrowUp:[0,-80],ArrowDown:[0,80]})[key],motion);}
export {color};
