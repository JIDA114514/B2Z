#ifndef BLUEBEE_PERF_H_
#define BLUEBEE_PERF_H_

#include <stdint.h>

#define BLUEBEE_PERF_HEADER_LEN  10u
#define BLUEBEE_PERF_MIN_PAYLOAD BLUEBEE_PERF_HEADER_LEN
#define BLUEBEE_PERF_MAX_PAYLOAD 46u

/* Build the common Phase-1 payload header and deterministic trailing bytes. */
void bluebee_perf_build_payload(uint8_t *payload, uint32_t payload_len,
				uint16_t run_id, uint32_t sequence);

#ifdef FREERTOS_INTEGRATION
/* Dedicated performance worker. It blocks until a start command is accepted. */
void bluebee_perf_task(void *pvParameters);

/* Strict decimal-only command handlers used by command_dispatch_line(). */
int32_t bluebee_pure_perf_start_cmdline(const char *args);
int32_t bluebee_exadv_perf_start_cmdline(const char *args);
int32_t bluebee_perf_stop_cmdline(const char *args);
int32_t bluebee_perf_status_cmdline(const char *args);
#endif

#endif
