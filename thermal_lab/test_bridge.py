import json
from pathlib import Path
import pytest
from thermal_lab.bridge import policy_effect, full_service, profiles, compare

ROOT=Path(__file__).resolve().parents[1]

def test_policy_differences_are_same_fleet():
    rows=json.loads((ROOT/'dc_sim/example_runs/ui_demo/compare.json').read_text())['rows']
    effect=policy_effect(rows,'greedy')
    assert effect['same_fleet_capex']
    assert effect['daily_cost_difference']>0
    assert effect['electricity_cost_fraction']>0
    assert effect['energy_fraction']<0  # cheaper sites can use more energy
    assert not effect['full_service_both']

def test_full_service_cannot_ignore_task_failures():
    assert not full_service({'served':100,'users_slo':100,'tasks_slo':95})
    assert full_service({'served':100,'users_slo':100,'tasks_slo':None})
    assert not full_service({})

def test_imported_profiles_keep_reference_year_and_workload():
    rows=profiles()
    assert len(rows)==12
    for row in rows:
        assert row['reference_year']==2035
        assert row['power_mw']>=row['standby_mw']>0
        assert row['price_musd']>0
        assert row['gpu_hours_per_job']>0
        assert row['jobs_per_hour']>=0

def test_only_known_presets():
    with pytest.raises(ValueError):compare('../anything')
