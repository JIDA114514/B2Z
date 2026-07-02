#ifndef BLE_H
#define BLE_H

void ble_rx_service_start(double *param, char param_no);
void ble_rx_service_stop(double *param, char param_no);
void ble_rx_service_poll(void);
void ble_rx_run_example_forever(void);

#endif
