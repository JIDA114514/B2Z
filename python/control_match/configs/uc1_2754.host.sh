# UC1 host RX & analysis commands (run_id=2754, sha256=72be35a89460d1e0...)
# Start both receivers BEFORE sending the board serial command.

# BLE receiver:
python3 python/exadv_rx/receive.py --run-id 2754 --uc1-config python/control_match/configs/uc1_2754.json --channels 3 --control-layout joint --sample-rate 4000000 --lna 16 --vga 16 --duration 330 --no-save-iq --experiment-dir python/experiments/20261124_run2754

# IEEE 802.15.4 receiver:
python3 python/zigbee_rx/control_receive.py --run-id 2754 --uc1-config python/control_match/configs/uc1_2754.json --channel 12 --control-layout joint --sample-rate 4000000 --lna 16 --vga 16 --duration 330 --no-save-iq --experiment-dir python/experiments/20261124_run2754

# Board serial trigger & log saver (run after both receivers start streaming):
python3 python/control_match/uc1_board_send.py --config python/control_match/configs/uc1_2754.json --experiment-dir python/experiments/20261124_run2754

# Joint analysis (after both captures and board.board.log are saved):
python3 python/control_match/uc1_analyze.py --experiment-dir python/experiments/20261124_run2754 --config python/control_match/configs/uc1_2754.json --analysis-id uc1_jc_core
