# UC1 host RX & analysis commands (run_id=2717, sha256=8e00e72a67ec6b4e...)
# Start both receivers BEFORE sending the board serial command.

# BLE receiver:
python3 python/exadv_rx/receive.py --run-id 2717 --uc1-config python/control_match/configs/uc1_2717.json --channels 3 --control-layout joint --sample-rate 4000000 --lna 16 --vga 10 --duration 180 --save-iq --control-target-id 1

# IEEE 802.15.4 receiver:
python3 python/zigbee_rx/control_receive.py --run-id 2717 --uc1-config python/control_match/configs/uc1_2717.json --channel 12 --control-layout joint --sample-rate 4000000 --lna 16 --vga 10 --duration 180 --save-iq --control-target-id 2

# Joint analysis (after both captures and board.board.log are saved):
python3 python/control_match/uc1_analyze.py --experiment-dir python/experiments/<YYYYMMDD>_run2717 --config python/control_match/configs/uc1_2717.json --analysis-id uc1_jc_time
