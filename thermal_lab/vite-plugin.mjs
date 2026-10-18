// Package the workstream's own assets without touching the shared application's logic.
import {readFileSync, readdirSync} from 'node:fs';
import path from 'node:path';
let page, shared;
function* files(dir,relative=''){
  for(const entry of readdirSync(dir,{withFileTypes:true})){
    const rel=path.posix.join(relative,entry.name);
    if(entry.isDirectory())yield* files(path.join(dir,entry.name),rel);
    else if(/\.(html|mjs|css|json)$/.test(entry.name)&&!entry.name.endsWith('.test.mjs'))yield [rel,readFileSync(path.join(dir,entry.name))];
  }
}
export default function thermalLab(){return {
  name:'thermal-lab-workstream',
  configResolved(config){page=path.resolve(config.root,'../thermal_lab/page');shared=path.resolve(config.root,'src/styles.css');},
  configureServer(server){server.middlewares.use((req,res,next)=>{
    let pathname;
    try{pathname=decodeURIComponent(new URL(req.url,'http://localhost').pathname);}catch{return next();}
    if(pathname==='/thermal_lab'){res.writeHead(302,{Location:'./thermal_lab/'});res.end();return;}
    if(!pathname.startsWith('/thermal_lab/'))return next();
    const rel=pathname.slice('/thermal_lab/'.length)||'index.html';
    const body=rel==='shared.css'?readFileSync(shared):new Map(files(page)).get(rel);
    if(!body){res.writeHead(404);res.end('Not found');return;}
    const mime={'.html':'text/html','.mjs':'text/javascript','.css':'text/css','.json':'application/json'}[path.extname(rel)];
    res.writeHead(200,{'Content-Type':`${mime}; charset=utf-8`});res.end(body);
  });},
  generateBundle(){
    for(const [rel,source] of files(page))this.emitFile({type:'asset',fileName:`thermal_lab/${rel}`,source});
    this.emitFile({type:'asset',fileName:'thermal_lab/shared.css',source:readFileSync(shared)});
  }
};}
