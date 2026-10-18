"""Run: uv run python -m thermal_lab --port 5175."""
import argparse
import json
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote
from dc_sim.server import Session, make_handler
from .bridge import profiles, compare

ROOT=Path(__file__).resolve().parents[1]
WEB=ROOT/'web'
PAGE=ROOT/'thermal_lab'/'page'

def make_server(port=5175):
    session=Session()
    session.reset("case_B_agents", "batch", 7)
    base=make_handler(session)
    class Handler(base):
        def _local(self):
            origin=self.headers.get('Origin')
            return self._ok_host() and (not origin or origin in (f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'))
        def do_GET(self):
            if not self._local(): return self._json({'error':'localhost only'},403)
            path=urlparse(self.path).path
            if path=='/api/meta':
                meta=session.meta();meta['presets']=[p for p in meta['presets'] if p['name']=='case_B_agents']
                return self._json(meta)
            if path=='/api/thermal/meta':
                return self._json({'presets':['case_B_agents'],'profiles':profiles()})
            if path in ('/', '/thermal', '/thermal/', '/thermal_lab'):
                self.send_response(302);self.send_header('Location','/thermal_lab/');self.end_headers();return
            if path in ('/router','/router/'):
                return self._static('index.html')
            if path.startswith('/thermal_lab/'):
                rel=unquote(path[len('/thermal_lab/'):]) or 'index.html'
                file=(PAGE/rel).resolve()
                if rel=='shared.css': file=WEB/'src/styles.css'
                if not (file==WEB/'src/styles.css' or PAGE in file.parents) or not file.is_file():
                    return self._json({'error':'not found'},404)
                mime={'.html':'text/html','.mjs':'text/javascript','.css':'text/css','.json':'application/json'}.get(file.suffix)
                if not mime:return self._json({'error':'not found'},404)
                body=file.read_bytes()
                if rel=='index.html':body=body.replace(b'data-mode="static"',b'data-mode="live"')
                return self._send(200,body,mime+'; charset=utf-8')
            return super().do_GET()
        def do_POST(self):
            if not self._local():return self._json({'error':'localhost only'},403)
            if urlparse(self.path).path!='/api/thermal/compare':return super().do_POST()
            try:
                length=int(self.headers.get('Content-Length','0'))
                if length<0 or length>4096:return self._json({'error':'invalid body size'},413)
                body=json.loads(self.rfile.read(length) or '{}')
                if not isinstance(body,dict):raise ValueError('Expected an object')
                seed=int(body.get('seed',7))
                if seed<0 or seed>2**32-1:raise ValueError('Seed outside range')
                preset=body.get('preset','case_B_agents')
                if preset!='case_B_agents':raise ValueError('Thermal Lab focuses on case_B_agents')
                return self._json(compare(preset,seed))
            except (ValueError,TypeError) as e:return self._json({'error':str(e)},400)
            except Exception as e:return self._json({'error':f'Simulation failed: {e}'},500)
    return ThreadingHTTPServer(('127.0.0.1',port),Handler)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=5175)
    args=parser.parse_args();server=make_server(args.port)
    print(f'Thermal + router lab: http://127.0.0.1:{server.server_port}/thermal_lab/',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
if __name__=='__main__':main()
