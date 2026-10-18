"""Read model parameters and compare policies without modifying dc_sim."""
from functools import lru_cache
from dc_sim import api, report, qfeas
from dc_sim.config import assumptions, clean_json
from dc_sim.costs import budget_power_check
from dc_sim.tasks import default_fallback

NODE_TYPES = ('qpu_cat40k', 'qpu_sc300k', 'qpu_ion40k')
WORKLOADS = ('chemistry_small', 'vqe_50q', 'vqe_20q', 'qla_scalar_explicit_1m')

@lru_cache(maxsize=1)
def profiles():
    rows = []
    for key in NODE_TYPES:
        cfg = assumptions()['node_types'][key]
        for workload in WORKLOADS:
            check = qfeas.gate_check(cfg['architecture'], workload)
            fb = default_fallback(workload)
            runtime = check.get('runtime_s', 0) + 60  # host prep/readout allowance, same as break-even table
            calibration = cfg['calibration']
            availability = max(0, 1-calibration['duration_s']/calibration['interval_s'])
            rows.append(dict(id=f'{key}:{workload}', label=f"{cfg['label']} / {workload}", node=key,
                workload=workload, architecture=cfg['architecture'], reference_year=2035,
                feasible=bool(check['feasible']), reason=check.get('reason',''),
                price_musd=cfg['capex_usd']/1e6, power_mw=check['system_power_w']/1e6,
                standby_mw=check['standby_w']/1e6,
                jobs_per_hour=3600/runtime*check.get('p_accept',0)*availability if check['feasible'] else 0,
                gpu_hours_per_job=fb['module_hours'], availability=availability,
                source='dc_sim assumptions + quantum_arch.gate_check; host overhead 60s; calibration availability; acceptance probability',
                note='Estimated throughput, not an observed queue result. 2035 anchor; no earlier quantum availability inferred.'))
    return clean_json(rows)

def full_service(row):
    values=[row.get('served'), row.get('users_slo'), row.get('tasks_slo')]
    return any(v is not None for v in values) and all(v is None or v >= 100-1e-6 for v in values)

def policy_effect(rows, policy):
    """Separate same-fleet routing from purchase decisions; negative savings are retained."""
    by={r['policy']:r for r in rows}; base=by['fifo']; selected=by[policy]
    return dict(policy=policy, baseline='fifo', energy_fraction=1-selected['energy_mwh']/base['energy_mwh'] if base['energy_mwh'] else 0,
        electricity_cost_fraction=1-selected['energy_usd_day']/base['energy_usd_day'] if base['energy_usd_day'] else 0,
        daily_cost_difference=(base['usd_day_m']-selected['usd_day_m'])*1e6,
        same_fleet_capex=abs(base['capex_usd']-selected['capex_usd'])<1,
        full_service_both=full_service(base) and full_service(selected),
        caps_held=base['never_exceeded'] and selected['never_exceeded'],
        note='Same-fleet policy comparison. A short workload window is not a validated annual saving. No peak-power or capacity gain is inferred.')

@lru_cache(maxsize=8)
def compare(preset='ui_demo', seed=7):
    if preset not in api.list_presets():
        raise ValueError('Unknown preset')
    engines=api.compare_policies(None,preset,seed=seed)
    rows=report.compare_rows(engines)
    return clean_json(dict(preset=preset,seed=seed,horizon_s=engines['fifo'].horizon,
        rows=rows,ranked=report.rank(rows),effects={p:policy_effect(rows,p) for p in ('greedy','batch')},
        budget=budget_power_check(engines['fifo'].fleet),
        metrics={p:e.metrics() for p,e in engines.items()},
        provenance='Fresh deterministic dc_sim run (cached for identical preset and seed). Simulator outputs, not measured hardware.',
        scheduler='Classical greedy or SciPy MILP/LP assigns work to GPU/QPU nodes; this is not a quantum scheduler.'))
