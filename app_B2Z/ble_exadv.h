#ifndef BLE_EXADV

#define BLE_EXADV

#include <stdint.h>
#include "../../../../../../python/std_ble/ble_exadv_waveform_30_72M.h"

/* Primary: BLE advertising channel 37 */
#define BLE_EXADV_PRIMARY_CH37_FREQ_HZ (2402000000ULL)
#define BLE_EXADV_PRIMARY_CH38_FREQ_HZ (2426000000ULL)
#define BLE_EXADV_PRIMARY_CH39_FREQ_HZ (2480000000ULL)
/* Same-channel diagnostic: secondary waveform is transmitted on ch39. */
#define BLE_EXADV_PRIMARY_FREQ_HZ BLE_EXADV_PRIMARY_CH39_FREQ_HZ
#define BLE_EXADV_SECONDARY_FREQ_HZ BLE_EXADV_PRIMARY_CH39_FREQ_HZ
#define BLE_EXADV_AUX_OFFSET_US (600u)
#define BLE_EXADV_INTERVAL_US (10000u)
#define BLE_EXADV_PRIMARY_SPACING_US (9000u)
#define BLE_EXADV_PRIMARY_AIR_US (136u)

int ble_exadv_start(uint32_t aux_offset_us, uint32_t interval_us);
int ble_exadv_start_with_timing(uint32_t aux_offset_us, uint32_t interval_us,
                                uint32_t secondary_start_lead_us);
void ble_exadv_stop(uint8_t restore_dds);
void ble_exadv_task_tick(void);
void ble_exadv_tx_demo(double *param, char param_no);

#endif
