import {cp} from 'node:fs/promises';
import {build} from 'vite';
await build();
try{await cp('data','dist/data',{recursive:true});}catch(error){if(error.code!=='ENOENT')throw error;}
console.log('Built frontend/dist with saved observations — ready for static hosting.');
