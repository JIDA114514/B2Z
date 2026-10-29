"""Long-lived defaults for the current two-HackRF BlueBee bench.

Edit device assignments and bench settings here; command-line options override
every default. These are project settings, not universal PHY recommendations.
Run ID, payload length and planned packet count belong to each experiment.
"""

COMMON = {
    "sample_rate": 8000000,
    "format": "ci8",
    "lna": 24,
    "vga": 20,
    "amp": False,
    "duration": None,  # resolved to LIVE_DURATION_S live, 0 (EOF) offline
    "block_samples": 65536,
    "queue_blocks": 64,
    "stall_timeout": 10,
    "dc_block_hz": 1000,
    "save_iq": None,  # resolved to True live, False offline
    "quiet": True,
}
LIVE_DURATION_S = 40

BLE = {
    "serial": "000000000000000017c467dc2926a0c3",
    "channels": "39",
    "sync_threshold": .84,
    "timing_retry": True,
    "channel_cutoff_hz": 850000,
    "pair_tolerance_us": 20,
    "diagnostic_pairs": True,
    "diagnostic_pair_window_us": 2000,
}

ZIGBEE = {
    "serial": "000000000000000017c467dc3348a6c3",
    "channel": 26,
    "cutoff_hz": 700000,
    "cfo_hz": 0,
    "demod": "phase",
    "symbol_order": "project",
    "soft_retry": True,
    "preamble_max_distance": 80,
}


def apply_defaults(parser, role):
    parser.set_defaults(**(COMMON | (BLE if role == "ble" else ZIGBEE)))


def resolve_input_defaults(args):
    if args.duration is None:
        args.duration = 0 if args.iq_file else LIVE_DURATION_S
    if args.save_iq is None:
        args.save_iq = not bool(args.iq_file)
    if args.iq_file:
        args.serial = None  # no hardware selected; does not identify the source SDR
