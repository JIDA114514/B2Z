# UC1 host RX & analysis commands (run_id=2701, sha256=7f2c6a04dff011e7...)
# Start both receivers BEFORE sending the board serial command.

# BLE receiver:
python3 python/exadv_rx/receive.py --run-id 2701 --uc1-config python/control_match/configs/uc1_2701.json --channels 3 --control-layout joint --sample-rate 4000000 --lna 16 --vga 10 --duration 60 --save-iq

# IEEE 802.15.4 receiver:
python3 python/zigbee_rx/control_receive.py --run-id 2701 --uc1-config python/control_match/configs/uc1_2701.json --channel 12 --control-layout joint --sample-rate 4000000 --lna 16 --vga 10 --duration 60 --save-iq

# Joint analysis (after both captures and board.board.log are saved):
python3 python/control_match/uc1_analyze.py --experiment-dir python/experiments/<YYYYMMDD>_run2701 --config python/control_match/configs/uc1_2701.json --analysis-id uc1_jc_core
