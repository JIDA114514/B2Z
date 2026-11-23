# UC1 host RX & analysis commands (run_id=2738, sha256=d94af6b0e4ed88a1...)
# Start both receivers BEFORE sending the board serial command.

# BLE receiver:
python3 python/exadv_rx/receive.py --run-id 2738 --uc1-config python/control_match/configs/uc1_2738.json --channels 3 --control-layout separate --sample-rate 4000000 --lna 16 --vga 16 --duration 330 --no-save-iq --experiment-dir python/experiments/20261123_run2738

# IEEE 802.15.4 receiver:
python3 python/zigbee_rx/control_receive.py --run-id 2738 --uc1-config python/control_match/configs/uc1_2738.json --channel 12 --control-layout separate --sample-rate 4000000 --lna 16 --vga 16 --duration 330 --no-save-iq --experiment-dir python/experiments/20261123_run2738

# Board serial trigger & log saver (run after both receivers start streaming):
python3 python/control_match/uc1_board_send.py --config python/control_match/configs/uc1_2738.json --experiment-dir python/experiments/20261123_run2738

# Joint analysis (after both captures and board.board.log are saved):
python3 python/control_match/uc1_analyze.py --experiment-dir python/experiments/20261123_run2738 --config python/control_match/configs/uc1_2738.json --analysis-id uc1_sc_core
