#ifndef BLE_TX_ADV_H
#define BLE_TX_ADV_H

#include <stdint.h>

#define BLE_TX_ADV_NAME_MAX_LEN 26u

int32_t ble_tx_adv_init(void);
int32_t ble_tx_adv_start_name(const char *name);
void ble_tx_adv_stop(uint8_t restore_dds);
void ble_tx_adv_task(void *pvParameters);

void ble_tx_adv_name_cmd(double *param, char param_no);
void ble_tx_adv_stop_cmd(double *param, char param_no);

void ble_tx_adv_tx_lock(void);
void ble_tx_adv_tx_unlock(void);

#endif
