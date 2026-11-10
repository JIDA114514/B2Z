"""Import independently decoded BLE hop evidence without inventing sample times."""
from datetime import datetime
import json
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from std_ble.ble_exadv_hackrf_sniffer import parse_ext_adv_payload
from std_ble.verify_board_exadv import validate_primary, validate_secondary
from exadv_rx.protocol import crc24


def load_flow(path: Path, run_id: int) -> dict:
    summary_path = path.with_name('flow.summary.json')
    summary = json.loads(summary_path.read_text())
    if (summary.get('schema') != 'board_std_ble_flow_v1' or
            summary.get('mode') != 'live_hop' or summary.get('run_id') != run_id or
            summary.get('status') != 'complete' or summary.get('interrupted')):
        raise ValueError('flow must be a complete same-run live hop capture')
    args = SimpleNamespace(**{k: summary[k] for k in
        ('run_id', 'command_id', 'expected_attempts', 'period_ms', 'primary_channel', 'secondary_channel')})
    args.aux_offset_us = summary['advertised_aux_offset_us']
    args.expected_adva = summary.get('expected_adva', 'C1:A2:A3:A4:A5:A6')
    primary, followed, by_slot = set(), set(), {}
    active = None
    active_secondary = None
    counts = {'duplicates': 0, 'crc_recomputed': 0, 'legacy_crc_assertions': 0}
    for line_no, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        kind = row['event']
        if kind in ('primary_valid', 'secondary_valid'):
            pdu = bytes.fromhex(row['pdu_hex'])
            if 'crc_hex' in row:
                if row.get('crc_ok') is not True or bytes.fromhex(row['crc_hex']) != crc24(pdu):
                    raise ValueError(f'flow BLE CRC mismatch at line {line_no}')
                counts['crc_recomputed'] += 1
            else:
                # Old verifier only emitted *_valid after checking BLE CRC.
                # Preserve that assertion as such; do not fabricate received CRC bytes.
                if row.get('crc_ok') is False:
                    raise ValueError('invalid CRC assertion')
                counts['legacy_crc_assertions'] += 1
            packet = {'pdu': pdu, 'channel': row['channel'], 'crc_ok': True,
                      'kind': 'primary' if kind == 'primary_valid' else 'secondary',
                      'ext': parse_ext_adv_payload(list(pdu[2:]))}
            detail = (validate_primary if kind == 'primary_valid' else validate_secondary)(packet, args)
            did = detail['did']
            if row['did'] != did:
                raise ValueError('flow DID disagrees with raw PDU')
            if kind == 'primary_valid':
                primary.add(did)
                active = did
                active_secondary = None
            else:
                active_secondary = did
                record = detail['control']
                if row.get('control') != record:
                    raise ValueError('flow control record disagrees with raw PDU')
                slot = record['slot_index']
                if slot in by_slot:
                    counts['duplicates'] += 1
                    if by_slot[slot]['record'] != record:
                        raise ValueError('conflicting flow records')
                by_slot[slot] = {'record': record, 'line_no': line_no,
                                 'sample_start': None, 'sample_time_s': None}
        elif kind == 'followed_event':
            did = row['did']
            if active != did or active_secondary != did or did not in by_slot:
                raise ValueError('follow event lacks preceding matching primary and secondary')
            followed.add(did)
            active = None
        elif kind == 'follow_window_miss':
            active = None
    if (primary != set(summary['primary_dids']) or set(by_slot) != set(summary['secondary_dids']) or
            followed != set(summary['paired_dids'])):
        raise ValueError('flow summary disagrees with event evidence')
    interval = None
    if summary.get('start_utc') and summary.get('end_utc'):
        interval = tuple(datetime.fromisoformat(summary[k]) for k in ('start_utc', 'end_utc'))
        if any(t.tzinfo is None for t in interval) or interval[0] >= interval[1]:
            raise ValueError('invalid flow capture interval')
    return {'path': path, 'by_slot': by_slot, 'counts': counts, 'live': None,
            'live_path': None, 'summary_path': summary_path, 'interval': interval,
            'followed_slots': followed, 'primary_slots': primary,
            'expected_attempts': args.expected_attempts, 'period_ms': args.period_ms}
