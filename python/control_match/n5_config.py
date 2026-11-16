"""Generate immutable N5 registration, including the existing N3 replay policies."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from datetime import datetime, timezone
from .n3_holdover import default_config, validate_config


def digest(c):
    return hashlib.sha256(json.dumps({k:v for k,v in c.items() if k != 'sha256'}, sort_keys=True).encode()).hexdigest()


def generate(run, provenance=True):
    if type(run) is not int or not 1 <= run <= 65535:
        raise ValueError("invalid run ID")
    c = default_config()
    c.update(n5_version=1, run_id=run, protocol_version=1,
             candidates={side:[s for s in c['slots'] if s % 2 == parity and s not in c['probes']]
                         for parity,side in enumerate(('ble','zigbee'))},
             observation_policy=dict(history=8, span_ms=4000, update_interval_ms=1000, holdover_ms=2000, stale_ms=10000),
             tasks=[dict(command_id=i, first_slot=s, attempts=k, execute_at_ms=t,
                         valid_until_ms=t-1000, ble_target=1, zigbee_target=2,
                         ble_opcode=op, zigbee_opcode=op, ble_arg=i-50, zigbee_arg=i-50)
                    for i,s,k,t,op in ((51,70,1,40000,1),(52,90,3,50000,1),
                                      (53,150,3,80000,2),(54,190,5,100000,1),
                                      (55,240,3,125000,2),(56,270,3,140000,1))],
             intervention_windows=[], intervention_description='no intentional intervention',
             missing_policy='no replacement of preregistered probes or frozen training slots',
             quality_policy='unknown_reference_strict_rejection')
    if provenance:
        root = Path(__file__).resolve().parents[2]
        c['created_utc'] = datetime.now(timezone.utc).isoformat()
        c['code_version'] = subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
        c['source_sha256'] = {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
                              for folder in ('control_match','exadv_rx','zigbee_rx')
                              for p in (root/'python'/folder).glob('*.py')}
    c['sha256'] = digest(c)
    return c


def validate(c, run):
    validate_config(c)
    expected = generate(run, provenance=False)
    if c.get('sha256') != digest(c) or c.get('run_id') != run:
        raise ValueError('N5 registration hash/run mismatch')
    for key in ('n5_version','protocol_version','candidates','observation_policy','tasks','quality_policy','period_ms','slots','probes','policies','missing_policy'):
        if c.get(key) != expected[key]:
            raise ValueError('unsupported N5 registration: '+key)
    if not c.get('source_sha256') or not c.get('code_version') or not c.get('created_utc'):
        raise ValueError('missing registration provenance')
    if not isinstance(c.get('intervention_description'), str) or not c['intervention_description'].strip():
        raise ValueError('missing intervention description')
    for window in c['intervention_windows']:
        if (not isinstance(window, list) or len(window) != 2 or
                any(type(v) is not int for v in window) or not 0 <= window[0] <= window[1] < 300):
            raise ValueError('invalid intervention window')
    return c


def load(path, run):
    return validate(json.loads(Path(path).read_text()), run)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--run-id', required=True, type=int)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument("--intervention-description", default="no intentional intervention")
    p.add_argument("--intervention-window", nargs=2, type=int, action="append", default=[])
    a = p.parse_args()
    if not 1 <= a.run_id <= 65535:
        p.error('run-id must be 1..65535')
    c = generate(a.run_id)
    c.update(intervention_description=a.intervention_description, intervention_windows=a.intervention_window)
    c['sha256'] = digest(c)
    validate(c, a.run_id)
    with a.output.open('x') as f:
        json.dump(c, f, indent=2)
