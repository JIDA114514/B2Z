# UC1 host RX & analysis commands (run_id=2764, sha256=989f1d416a510039...)
# Start both receivers BEFORE sending the board serial command.

# BLE receiver:
python3 python/exadv_rx/receive.py --run-id 2764 --uc1-config python/control_match/configs/uc1_2764.json --channels 39 --control-layout separate --sample-rate 4000000 --lna 16 --vga 16 --duration 330 --no-save-iq --experiment-dir python/experiments/20261124_run2764

# IEEE 802.15.4 receiver:
python3 python/zigbee_rx/control_receive.py --run-id 2764 --uc1-config python/control_match/configs/uc1_2764.json --channel 12 --control-layout separate --sample-rate 4000000 --lna 16 --vga 16 --duration 330 --no-save-iq --experiment-dir python/experiments/20261124_run2764

# Board serial trigger & log saver (run after both receivers start streaming):
python3 python/control_match/uc1_board_send.py --config python/control_match/configs/uc1_2764.json --experiment-dir python/experiments/20261124_run2764

# Joint analysis (after both captures and board.board.log are saved):
python3 python/control_match/uc1_analyze.py --experiment-dir python/experiments/20261124_run2764 --config python/control_match/configs/uc1_2764.json --analysis-id uc1_lc_core
