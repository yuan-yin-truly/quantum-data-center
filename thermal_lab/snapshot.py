"""Regenerate the hosted page's saved Python-engine evidence: uv run python -m thermal_lab.snapshot."""
import json
from datetime import datetime, timezone
from pathlib import Path
from dc_sim.api import list_presets
from dc_sim.replay import build_html
from .bridge import compare, profiles

def export_snapshot(destination=None):
    dest=Path(destination) if destination else Path(__file__).parent/'page'/'snapshots'
    dest.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone.utc).isoformat()
    comparison=compare('ui_demo',7)
    comparison.update(hosted_snapshot=True,generated_at=stamp)
    meta={'presets':['ui_demo'],'profiles':profiles(),'generated_at':stamp,'seed':7,
          'available_live_presets':list_presets(),'mode':'saved-python-engine-results'}
    (dest/'meta.json').write_text(json.dumps(meta,indent=2)+'\n',encoding='utf-8')
    (dest/'comparison.json').write_text(json.dumps(comparison,indent=2)+'\n',encoding='utf-8')
    (dest/'router-replay.html').write_text(build_html(None,'ui_demo','batch',seed=7,every=6),encoding='utf-8')
    print(f'Exported Thermal Lab snapshot to {dest}')
    return dest

if __name__=='__main__':export_snapshot()
