"""Export saved A/B/C comparisons using existing dc_sim assumptions (no new measurements)."""
import json
from datetime import datetime, timezone
from pathlib import Path
from dc_sim.replay import build_html
from .bridge import compare, profiles
CASES={'A':'case_A_prompters','B':'case_B_agents','C':'case_C_knowledge'}
def export_snapshot(destination=None):
    dest=Path(destination) if destination else Path(__file__).parent/'page'/'snapshots'
    dest.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone.utc).isoformat()
    meta={'presets':list(CASES.values()),'profiles':profiles(),'generated_at':stamp,'seed':7,'cases':CASES,'mode':'saved-model-results-not-measurements'}
    (dest/'meta.json').write_text(json.dumps(meta,indent=2)+'\n',encoding='utf-8')
    for case,preset in CASES.items():
        print(f'Exporting case {case}: {preset}',flush=True)
        comparison=compare(preset,7)
        comparison.update(hosted_snapshot=True,generated_at=stamp,case=case)
        (dest/f'comparison-{case}.json').write_text(json.dumps(comparison,indent=2)+'\n',encoding='utf-8')
        (dest/f'router-replay-{case}.html').write_text(build_html(None,preset,'batch',seed=7,every=24),encoding='utf-8')
    print(f'Exported A/B/C router references to {dest}',flush=True)
    return dest
if __name__=='__main__':export_snapshot()
