# UC1 host RX & analysis commands (run_id=2716, sha256=c06a0c357bf555cc...)
# Start both receivers BEFORE sending the board serial command.

# BLE receiver:
python3 python/exadv_rx/receive.py --run-id 2716 --uc1-config python/control_match/configs/uc1_2716.json --channels 3 --control-layout joint --sample-rate 4000000 --lna 16 --vga 10 --duration 180 --save-iq --control-target-id 1

# IEEE 802.15.4 receiver:
python3 python/zigbee_rx/control_receive.py --run-id 2716 --uc1-config python/control_match/configs/uc1_2716.json --channel 12 --control-layout joint --sample-rate 4000000 --lna 16 --vga 10 --duration 180 --save-iq --control-target-id 2

# Joint analysis (after both captures and board.board.log are saved):
python3 python/control_match/uc1_analyze.py --experiment-dir python/experiments/<YYYYMMDD>_run2716 --config python/control_match/configs/uc1_2716.json --analysis-id uc1_jc_time
