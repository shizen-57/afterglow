import {mkdir,writeFile} from 'node:fs/promises';
import {loadBoundaries,loadFires} from './lib/feeds.mjs';
await mkdir('data',{recursive:true});
const districts=await loadBoundaries();
await writeFile('data/districts.geojson',JSON.stringify(districts));
const dataset=await loadFires(districts);
await writeFile('data/latest.json',JSON.stringify(dataset));
console.log(JSON.stringify({districts:districts.features.length,observations:dataset.observations.length,fetchedAt:dataset.fetchedAt,sources:dataset.sources,warnings:dataset.warnings},null,2));
