# UC1 host RX & analysis commands (run_id=2753, sha256=33640b158a228a1e...)
# Start both receivers BEFORE sending the board serial command.

# BLE receiver:
python3 python/exadv_rx/receive.py --run-id 2753 --uc1-config python/control_match/configs/uc1_2753.json --channels 3 --control-layout separate --sample-rate 4000000 --lna 16 --vga 16 --duration 330 --no-save-iq --experiment-dir python/experiments/20261124_run2753

# IEEE 802.15.4 receiver:
python3 python/zigbee_rx/control_receive.py --run-id 2753 --uc1-config python/control_match/configs/uc1_2753.json --channel 12 --control-layout separate --sample-rate 4000000 --lna 16 --vga 16 --duration 330 --no-save-iq --experiment-dir python/experiments/20261124_run2753

# Board serial trigger & log saver (run after both receivers start streaming):
python3 python/control_match/uc1_board_send.py --config python/control_match/configs/uc1_2753.json --experiment-dir python/experiments/20261124_run2753

# Joint analysis (after both captures and board.board.log are saved):
python3 python/control_match/uc1_analyze.py --experiment-dir python/experiments/20261124_run2753 --config python/control_match/configs/uc1_2753.json --analysis-id uc1_sc_core
