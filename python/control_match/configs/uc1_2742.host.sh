# UC1 host RX & analysis commands (run_id=2742, sha256=88d2ea2088fb38eb...)
# Start both receivers BEFORE sending the board serial command.

# BLE receiver:
python3 python/exadv_rx/receive.py --run-id 2742 --uc1-config python/control_match/configs/uc1_2742.json --channels 39 --control-layout separate --sample-rate 4000000 --lna 16 --vga 16 --duration 330 --save-iq --experiment-dir python/experiments/20261123_run2742

# IEEE 802.15.4 receiver:
python3 python/zigbee_rx/control_receive.py --run-id 2742 --uc1-config python/control_match/configs/uc1_2742.json --channel 12 --control-layout separate --sample-rate 4000000 --lna 16 --vga 16 --duration 330 --save-iq --experiment-dir python/experiments/20261123_run2742

# Board serial trigger & log saver (run after both receivers start streaming):
python3 python/control_match/uc1_board_send.py --config python/control_match/configs/uc1_2742.json --experiment-dir python/experiments/20261123_run2742

# Joint analysis (after both captures and board.board.log are saved):
python3 python/control_match/uc1_analyze.py --experiment-dir python/experiments/20261123_run2742 --config python/control_match/configs/uc1_2742.json --analysis-id uc1_lc_core
