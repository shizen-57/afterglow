import http from 'node:http';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { resolve, extname, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import {loadBoundaries,loadFires} from './lib/feeds.mjs';

const root = fileURLToPath(new URL('.', import.meta.url));
const port = Number(process.env.PORT || 5173);
const development=process.argv.includes('--dev');
const staticRoot=development?root:resolve(root,'dist');
const vite=development?await(await import('vite')).createServer({server:{middlewareMode:true},appType:'spa'}):null;
const types = { '.html': 'text/html; charset=utf-8', '.css': 'text/css', '.js': 'text/javascript', '.mjs':'text/javascript', '.geojson':'application/json', '.svg': 'image/svg+xml', '.json': 'application/json' };
let boundaryCache=null,fireCache=null,firePromise=null,boundaryPromise=null;
async function cachedFile(name){try{return JSON.parse(await readFile(resolve(root,'data',name),'utf8'));}catch{return null;}}
async function save(name,value){await mkdir(resolve(root,'data'),{recursive:true});await writeFile(resolve(root,'data',name),JSON.stringify(value));}
async function boundaries(){if(boundaryCache)return boundaryCache;if(!boundaryPromise)boundaryPromise=loadBoundaries().then(async data=>{boundaryCache=data;await save('districts.geojson',data);return data;}).catch(async error=>{const saved=await cachedFile('districts.geojson');if(saved){boundaryCache=saved;return saved;}throw error;}).finally(()=>{boundaryPromise=null;});return boundaryPromise;}
async function fires(){if(fireCache&&Date.now()-Date.parse(fireCache.fetchedAt)<15*60000)return fireCache;if(!firePromise)firePromise=(async()=>{let districts;try{districts=await boundaries();}catch{}try{const data=await loadFires(districts);fireCache=data;await save('latest.json',data);return data;}catch(error){const saved=await cachedFile('latest.json');if(saved)return{...saved,stale:true,warnings:[...(saved.warnings||[]),error.message]};throw error;}})().finally(()=>{firePromise=null;});return firePromise;}
boundaryCache=await cachedFile('districts.geojson');
fireCache=await cachedFile('latest.json');
http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, 'http://localhost');
    if(req.method!=='GET'){res.writeHead(405).end('Method not allowed');return;}
    if(url.pathname==='/api/firms'||url.pathname==='/api/boundaries'){
      try{const data=await(url.pathname==='/api/firms'?fires():boundaries());res.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store'}).end(JSON.stringify(data));}
      catch(error){res.writeHead(502,{'Content-Type':'application/json'}).end(JSON.stringify({error:error.message}));}return;
    }
    if(vite){vite.middlewares(req,res);return;}
    if(url.pathname!=='/'&&url.pathname!=='/index.html'&&!['/assets/','/data/'].some(p=>url.pathname.startsWith(p))){res.writeHead(404).end('File not found');return;}
    const path = resolve(staticRoot, '.' + decodeURIComponent(url.pathname === '/' ? '/index.html' : url.pathname));
    if (!path.startsWith(staticRoot.endsWith(sep) ? staticRoot : staticRoot + sep)) { res.writeHead(403).end(); return; }
    const content = await readFile(path);
    res.writeHead(200, { 'Content-Type': types[extname(path)] || 'application/octet-stream', 'Cache-Control': 'no-cache' }).end(content);
  } catch { res.writeHead(404).end('File not found'); }
}).listen(port, '127.0.0.1', () => console.log(`Afterglow ready at http://localhost:${port}`));
