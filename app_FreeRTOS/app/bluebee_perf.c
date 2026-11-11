#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "app_config.h"
#include "bluebee_perf.h"

#define BLUEBEE_PERF_MAGIC0  0xB2u
#define BLUEBEE_PERF_MAGIC1  0x5Au
#define BLUEBEE_PERF_VERSION 1u
#define BLUEBEE_PERF_FILL_SEED 0xB25A5A2Du

void bluebee_perf_build_payload(uint8_t *payload, uint32_t payload_len,
				uint16_t run_id, uint32_t sequence)
{
	uint32_t state;

	if (!payload || payload_len < BLUEBEE_PERF_HEADER_LEN)
		return;

	payload[0] = BLUEBEE_PERF_MAGIC0;
	payload[1] = BLUEBEE_PERF_MAGIC1;
	payload[2] = BLUEBEE_PERF_VERSION;
	payload[3] = BLUEBEE_PERF_HEADER_LEN;
	payload[4] = (uint8_t)(run_id & 0xFFu);
	payload[5] = (uint8_t)(run_id >> 8);
	payload[6] = (uint8_t)(sequence & 0xFFu);
	payload[7] = (uint8_t)((sequence >> 8) & 0xFFu);
	payload[8] = (uint8_t)((sequence >> 16) & 0xFFu);
	payload[9] = (uint8_t)((sequence >> 24) & 0xFFu);

	state = BLUEBEE_PERF_FILL_SEED ^ ((uint32_t)run_id << 16) ^ sequence;
	for (uint32_t i = BLUEBEE_PERF_HEADER_LEN; i < payload_len; i++) {
		state = state * 1664525u + 1013904223u;
		payload[i] = (uint8_t)(state >> 24);
	}
}

#ifdef FREERTOS_INTEGRATION

#include "FreeRTOS.h"
#include "task.h"
#include "xtime_l.h"

#include "ad9361_api.h"
#include "axi_dac_core.h"
#include "axi_dmac.h"
#include "ble_exadv_secondary_gen.h"
#include "ble_tx_adv.h"
#include "bluebee_gen.h"
#include "console.h"
#include "dma_tx_waveforms/dma_tx_ble_exadv_waveform_30_72M.h"
#include "no_os_axi_io.h"
#include "no_os_gpio.h"

#ifdef XILINX_PLATFORM
#include <xil_cache.h>
#endif

#define BLUEBEE_PERF_MAX_ARGS             13u
#define BLUEBEE_PERF_LEGACY_ARGS          6u
#define BLUEBEE_PERF_MAX_DURATION_S       600u
#define BLUEBEE_PERF_DMA_MARGIN_US        5000u
#define BLUEBEE_PERF_PRIMARY_TIMEOUT_US   10000u
#define BLUEBEE_PERF_AUX_OFFSET_US        30000u
#define BLUEBEE_PERF_WAIT_SLEEP_US        2000u
#define BLUEBEE_PERF_WAIT_SPIN_US         500u
#define BLUEBEE_PERF_MAX_SLEEP_MS         10u
#define BLUEBEE_PERF_AXI_DAC_SYNC_CONTROL 0x44u
#define BLUEBEE_PERF_AXI_DAC_SYNC         0x1u
#define BLUEBEE_PERF_BATCH_MAX_SIZE      8u
#define BLUEBEE_PERF_BATCH_DEFAULT_SIZE  4u
#define BLUEBEE_PERF_IQ_WORD_CAPACITY    230000u
#define B2Z_PLAN_MAX_ENTRIES             16u
#define B2Z_PLAN_MAX_SLOTS               1024u
#define B2Z_SLOT_GENERATED               0x01u
#define B2Z_SLOT_PRIMARY_STARTED         0x02u
#define B2Z_SLOT_PRIMARY_COMPLETED       0x04u
#define B2Z_SLOT_TX_STARTED              0x08u
#define B2Z_SLOT_TX_COMPLETED            0x10u
#define B2Z_SLOT_DEADLINE_MISS           0x20u
#define B2Z_SLOT_DMA_TIMEOUT             0x40u
#define B2Z_SLOT_AUXPTR_DMA_MISS          0x80u
#define B2Z_STANDARD_MIN_PERIOD_MS       500u
#define B2Z_AUXPTR_WINDOW_US             300u
#define B2Z_AUX_WAIT_SPIN_US             1000u


enum bluebee_perf_test {
	BLUEBEE_PERF_TEST_PURE = 0,
	BLUEBEE_PERF_TEST_EXADV,
	BLUEBEE_PERF_TEST_CONTROL,
};

enum bluebee_perf_state {
	BLUEBEE_PERF_STATE_IDLE = 0,
	BLUEBEE_PERF_STATE_ARMED,
	BLUEBEE_PERF_STATE_RUNNING,
	BLUEBEE_PERF_STATE_STOPPING,
	BLUEBEE_PERF_STATE_COMPLETE,
	BLUEBEE_PERF_STATE_STOPPED,
	BLUEBEE_PERF_STATE_ERROR,
};

struct b2z_plan_entry {
	struct b2z_control_packet packet;
	uint16_t repeats;
	uint16_t first_slot;
};

struct bluebee_perf_config {
	enum bluebee_perf_test test;
	uint32_t payload_len;
	uint32_t interval_us;
	uint32_t duration_s;
	uint16_t run_id;
	uint8_t mode;
	uint32_t batch_size;
	uint32_t expected_packets;
	struct b2z_control_packet control;
	uint8_t planned;
	uint8_t control_rf_mode;
	uint8_t plan_count;
	struct b2z_plan_entry plan[B2Z_PLAN_MAX_ENTRIES];
};

struct bluebee_perf_counters {
	uint32_t scheduled;
	uint32_t generated;
	uint32_t primary_started;
	uint32_t primary_completed;
	uint32_t tx_started;
	uint32_t tx_completed;
	uint32_t deadline_miss;
	uint32_t dma_timeout;
	uint32_t secondary_dma_late_samples;
	uint32_t secondary_dma_late_max_us;
	uint64_t secondary_dma_late_sum_us;
	uint32_t auxptr_dma_window_miss;
	uint32_t auxptr_dma_delta_samples;
	uint32_t auxptr_dma_delta_min_us;
	uint32_t auxptr_dma_delta_max_us;
	uint64_t auxptr_dma_delta_sum_us;
	uint32_t retune_failure;
	uint32_t retune_secondary_samples;
	uint32_t retune_secondary_max_us;
	uint64_t retune_secondary_sum_us;
};

struct bluebee_perf_time_stats {
	uint32_t samples;
	uint32_t min_us;
	uint32_t max_us;
	uint64_t sum_us;
};

struct bluebee_perf_gen_timing {
	uint32_t frame_us;
	uint32_t mapping_us;
	uint32_t gfsk_us;
	uint32_t total_us;
};

struct bluebee_perf_prepared {
	uint32_t *iq_words;
	uint32_t iq_byte_count;
	uint32_t tx_time_us;
	uint32_t sequence;
	struct bluebee_perf_gen_timing timing;
	uint8_t valid;
};

struct bluebee_perf_runtime {
	struct bluebee_perf_config config;
	struct bluebee_perf_counters counters;
	struct bluebee_perf_time_stats frame_time;
	struct bluebee_perf_time_stats mapping_time;
	struct bluebee_perf_time_stats gfsk_time;
	struct bluebee_perf_time_stats total_time;
	enum bluebee_perf_state state;
	uint8_t stop_requested;
	XTime start_time;
	XTime end_time;
};

extern struct ad9361_rf_phy *ad9361_phy;
extern struct axi_dmac *tx_dmac;

static struct bluebee_perf_runtime g_perf;
static TaskHandle_t g_perf_task;
static uint8_t g_perf_reporting;
static struct b2z_plan_entry g_plan_draft[B2Z_PLAN_MAX_ENTRIES];
static uint8_t g_plan_draft_count;
static uint8_t g_control_slot_flags[B2Z_PLAN_MAX_SLOTS];
static uint32_t g_control_slot_late_us[B2Z_PLAN_MAX_SLOTS];
static uint32_t g_control_slot_aux_delta_us[B2Z_PLAN_MAX_SLOTS];
static uint32_t g_control_slot_retune_us[B2Z_PLAN_MAX_SLOTS];

/* Buffered until final reporting: no UART traffic is added to the RF path.
 * All times bracket software DMA calls; none is an RF start measurement. */
struct b2z_burst_observation {
	uint32_t iq_bytes, air_us, pad_us;
	uint32_t prepared_us, submit_before_us, submit_after_us, finish_us;
	uint8_t generated, attempted, started, completed, timeout;
};
static struct b2z_burst_observation g_control_bursts[B2Z_PLAN_MAX_SLOTS][3];

#ifndef B2Z_N3_TRACE_ENABLED
#define B2Z_N3_TRACE_ENABLED 1
#endif
enum b2z_trace_stage {
	N3_CALL, N3_STOP_CLEAR, N3_CACHE, N3_DAC_SYNC, N3_SUBMIT, N3_POLL,
	N3_GENERATE, N3_RETUNE_SECONDARY, N3_RETUNE_PRIMARY, N3_STAGE_COUNT
};
struct b2z_trace {
	XTime tick[N3_STAGE_COUNT][2];
	uint32_t valid;
	int32_t status[N3_STAGE_COUNT];
	uint32_t remaining_bytes;
	uint32_t frame_us, mapping_us, gfsk_us;
};
/* kind 0/1/2 = primary/secondary/IEEE, kind 3 = slot preparation/retune. */
static struct b2z_trace g_n3_trace[B2Z_PLAN_MAX_SLOTS][4];
static XTime g_n3_primary_anchor[B2Z_PLAN_MAX_SLOTS];
static uint32_t g_n3_overflow, g_n3_timer_min, g_n3_timer_max;

static struct b2z_trace *b2z_trace_for(uint32_t slot, uint32_t kind)
{
	if (!B2Z_N3_TRACE_ENABLED || !g_perf.config.planned) return NULL;
	if (slot >= B2Z_PLAN_MAX_SLOTS || kind >= 4u) {
		g_n3_overflow++;
		return NULL;
	}
	return &g_n3_trace[slot][kind];
}

static void b2z_trace_mark(struct b2z_trace *t, uint32_t stage,
			   uint32_t after, int32_t status)
{
	if (!t) return;
	XTime_GetTime(&t->tick[stage][after]);
	t->valid |= 1u << (2u * stage + after);
	if (after) t->status[stage] = status;
}

static void b2z_submit_mark(void *context, uint8_t after, int32_t status)
{
	b2z_trace_mark(context, N3_SUBMIT, after, status);
}

static void b2z_timer_probe(void)
{
	g_n3_timer_min = UINT32_MAX;
	g_n3_timer_max = 0u;
	for (uint32_t i = 0u; i < 32u; i++) {
		XTime a, b;
		XTime_GetTime(&a); XTime_GetTime(&b);
		uint32_t dt = (uint32_t)(b - a);
		if (dt < g_n3_timer_min) g_n3_timer_min = dt;
		if (dt > g_n3_timer_max) g_n3_timer_max = dt;
	}
}



/* Dedicated DDR BSS arena; independent of the 1 MB FreeRTOS heap. */
static uint32_t
g_perf_iq_arena[BLUEBEE_PERF_BATCH_MAX_SIZE][BLUEBEE_PERF_IQ_WORD_CAPACITY]
	__attribute__((aligned(64)));

static const char *bluebee_perf_test_name(enum bluebee_perf_test test)
{
	switch (test) {
	case BLUEBEE_PERF_TEST_PURE:
		return "pure";
	case BLUEBEE_PERF_TEST_EXADV:
		return "exadv";
	case BLUEBEE_PERF_TEST_CONTROL:
		return "control";
	default:
		return "unknown";
	}
}

static const char *b2z_rf_mode_name(uint8_t mode)
{
	return mode == B2Z_CONTROL_RF_SEPARATE_CH3 ? "separate_secondary_ch3" :
		(mode == B2Z_CONTROL_RF_STANDARD_CH3 ?
		 "standard_secondary_ch3" : "same_channel_diagnostic");
}

static uint32_t b2z_aux_offset_us(uint8_t mode)
{
	return mode != B2Z_CONTROL_RF_SAME_CHANNEL ?
		B2Z_CONTROL_STANDARD_AUX_OFFSET_US :
		B2Z_CONTROL_DIAGNOSTIC_AUX_OFFSET_US;
}

static const char *bluebee_perf_state_name(enum bluebee_perf_state state)
{
	switch (state) {
	case BLUEBEE_PERF_STATE_IDLE:
		return "idle";
	case BLUEBEE_PERF_STATE_ARMED:
		return "armed";
	case BLUEBEE_PERF_STATE_RUNNING:
		return "running";
	case BLUEBEE_PERF_STATE_STOPPING:
		return "stopping";
	case BLUEBEE_PERF_STATE_COMPLETE:
		return "complete";
	case BLUEBEE_PERF_STATE_STOPPED:
		return "stopped";
	case BLUEBEE_PERF_STATE_ERROR:
		return "error";
	default:
		return "unknown";
	}
}

static const char *bluebee_perf_mode_name(uint8_t mode)
{
	switch (mode) {
	case 0u:
		return "realtime";
	case 1u:
		return "batch";
	case 2u:
		return "double";
	default:
		return "invalid";
	}
}

static uint8_t bluebee_perf_is_line_end(char c)
{
	return (uint8_t)(c == '\0' || c == '\r' || c == '\n');
}

static uint8_t bluebee_perf_is_busy(enum bluebee_perf_state state)
{
	return (uint8_t)(state == BLUEBEE_PERF_STATE_ARMED ||
			 state == BLUEBEE_PERF_STATE_RUNNING ||
			 state == BLUEBEE_PERF_STATE_STOPPING);
}

uint8_t bluebee_perf_is_active(void)
{
	uint8_t active;

	taskENTER_CRITICAL();
	active = bluebee_perf_is_busy(g_perf.state) || g_perf_reporting;
	taskEXIT_CRITICAL();
	return active;
}

static XTime bluebee_perf_ticks_from_us(uint32_t us)
{
	return (XTime)(((uint64_t)COUNTS_PER_SECOND * us + 999999ULL) /
			1000000ULL);
}

static uint32_t bluebee_perf_slots_arrived(
	const struct bluebee_perf_config *config, XTime start_time, XTime now)
{
	XTime interval_ticks = bluebee_perf_ticks_from_us(config->interval_us);
	uint64_t arrived;

	if (now < start_time || interval_ticks == 0u)
		return 0u;

	arrived = ((uint64_t)(now - start_time) / interval_ticks) + 1ULL;
	if (config->duration_s != 0u && arrived > config->expected_packets)
		arrived = config->expected_packets;
	if (arrived > 0xFFFFFFFFULL)
		arrived = 0xFFFFFFFFULL;

	return (uint32_t)arrived;
}

static uint32_t bluebee_perf_ticks_to_us(XTime ticks)
{
	uint64_t us = ((uint64_t)ticks * 1000000ULL) / COUNTS_PER_SECOND;

	return us > 0xFFFFFFFFULL ? 0xFFFFFFFFu : (uint32_t)us;
}

static uint32_t bluebee_perf_elapsed_us(const struct bluebee_perf_runtime *perf)
{
	XTime end;

	if (perf->start_time == 0)
		return 0u;
	if (bluebee_perf_is_busy(perf->state))
		XTime_GetTime(&end);
	else
		end = perf->end_time;
	if (end <= perf->start_time)
		return 0u;

	return bluebee_perf_ticks_to_us(end - perf->start_time);
}

static void bluebee_perf_snapshot(struct bluebee_perf_runtime *snapshot)
{
	taskENTER_CRITICAL();
	*snapshot = g_perf;
	taskEXIT_CRITICAL();
}

static const struct b2z_plan_entry *b2z_plan_entry_for_slot(
	const struct bluebee_perf_config *config, uint32_t slot)
{
	for (uint32_t i = 0u; i < config->plan_count; i++) {
		const struct b2z_plan_entry *entry = &config->plan[i];

		if (slot >= entry->first_slot &&
		    slot - entry->first_slot < entry->repeats)
			return entry;
	}
	return NULL;
}

static void b2z_plan_slot_flag(uint32_t slot, uint8_t flag)
{
	if (slot >= B2Z_PLAN_MAX_SLOTS || !g_perf.config.planned)
		return;
	taskENTER_CRITICAL();
	g_control_slot_flags[slot] |= flag;
	taskEXIT_CRITICAL();
}

/* console_print only supports signed long; format raw 64-bit ticks ourselves. */
static const char *b2z_tick_hex(XTime value, char out[17])
{
	static const char digits[] = "0123456789abcdef";
	for (uint32_t i = 0; i < 16u; i++)
		out[i] = digits[(value >> ((15u - i) * 4u)) & 15u];
	out[16] = 0;
	return out;
}

static int32_t b2z_signed_us(XTime event, XTime target)
{
	return event >= target ? (int32_t)bluebee_perf_ticks_to_us(event - target) :
		-(int32_t)bluebee_perf_ticks_to_us(target - event);
}

static void b2z_print_trace(const struct bluebee_perf_runtime *snapshot)
{
	char hex[3][17];
	static const char *names[N3_STAGE_COUNT] = {
		"call", "stop_clear", "cache_flush", "dac_sync", "submit_write", "poll",
		"generation", "retune_secondary", "retune_primary"
	};
	console_print("CONTROL_TIME_META run_id=%d schema=1 enabled=%d tick_hz=%d "
		"epoch_ticks=%s slots_capacity=%d overflow=%d "
		"timer_probe_n=%d timer_probe_min_ticks=%d timer_probe_max_ticks=%d "
		"reference=software_counter not_rf=1 submit_scope=first_write\r\n",
		(long)snapshot->config.run_id, (long)B2Z_N3_TRACE_ENABLED,
		(long)COUNTS_PER_SECOND, (char *)b2z_tick_hex(snapshot->start_time, hex[0]), (long)B2Z_PLAN_MAX_SLOTS,
		(long)g_n3_overflow, (long)(B2Z_N3_TRACE_ENABLED ? 32u : 0u),
		(long)g_n3_timer_min, (long)g_n3_timer_max);
	if (!B2Z_N3_TRACE_ENABLED) return;
	for (uint32_t slot = 0; slot < snapshot->config.expected_packets; slot++) {
		XTime planned = snapshot->start_time +
			bluebee_perf_ticks_from_us(snapshot->config.interval_us) * slot;
		XTime anchor = g_n3_primary_anchor[slot];
		XTime target = anchor ? anchor + bluebee_perf_ticks_from_us(
			b2z_aux_offset_us(snapshot->config.control_rf_mode)) : 0;
		const struct b2z_trace *prep = &g_n3_trace[slot][3];
		console_print("CONTROL_TIME_SLOT run_id=%d slot=%d planned_ticks=%s "
			"anchor_valid=%d anchor_ticks=%s target_ticks=%s "
			"frame_us=%d mapping_us=%d gfsk_us=%d\r\n",
			(long)snapshot->config.run_id, (long)slot,
			(char *)b2z_tick_hex(planned, hex[0]), (long)(anchor != 0),
			(char *)b2z_tick_hex(anchor, hex[1]), (char *)b2z_tick_hex(target, hex[2]),
			(long)prep->frame_us, (long)prep->mapping_us, (long)prep->gfsk_us);
		const struct b2z_trace *sec = &g_n3_trace[slot][1];
		uint32_t call_valid = anchor && (sec->valid & (1u << (2u * N3_CALL)));
		uint32_t submit_valid = anchor && (sec->valid & (1u << (2u * N3_SUBMIT)));
		uint32_t return_valid = anchor && (sec->valid & (1u << (2u * N3_CALL + 1u)));
		console_print("CONTROL_TIME_LATE run_id=%d slot=%d reference=legacy_primary_call_anchor "
			"call_valid=%d submit_valid=%d return_valid=%d "
			"pre_call_us=%d pre_submit_us=%d post_return_us=%d window_us=%d\r\n",
			(long)snapshot->config.run_id, (long)slot,
			(long)!!call_valid, (long)!!submit_valid, (long)!!return_valid,
			(long)(call_valid ? b2z_signed_us(sec->tick[N3_CALL][0], target) : 0),
			(long)(submit_valid ? b2z_signed_us(sec->tick[N3_SUBMIT][0], target) : 0),
			(long)(return_valid ? b2z_signed_us(sec->tick[N3_CALL][1], target) : 0),
			(long)B2Z_AUXPTR_WINDOW_US);

		for (uint32_t kind = 0; kind < 4u; kind++) {
			if (kind == 2u && snapshot->config.control_rf_mode != B2Z_CONTROL_RF_SEPARATE_CH3) continue;
			const struct b2z_trace *t = &g_n3_trace[slot][kind];
			for (uint32_t stage = (kind == 3u ? N3_GENERATE : N3_CALL);
			     stage < (kind == 3u ? N3_STAGE_COUNT : N3_GENERATE); stage++) {
				uint32_t valid = (t->valid >> (2u * stage)) & 3u;
				console_print("CONTROL_TIME_STAGE run_id=%d slot=%d kind=%d stage=%s valid=%d "
					"before_ticks=%s after_ticks=%s "
					"status=%d remaining_bytes=%d\r\n",
					(long)snapshot->config.run_id, (long)slot, (long)kind, (char *)names[stage],
					(long)valid, (char *)b2z_tick_hex(t->tick[stage][0], hex[0]),
					(char *)b2z_tick_hex(t->tick[stage][1], hex[1]),
					(long)t->status[stage], (long)t->remaining_bytes);
			}
		}
	}
	console_print("CONTROL_TIME_END run_id=%d slots=%d overflow=%d\r\n",
		(long)snapshot->config.run_id, (long)snapshot->config.expected_packets, (long)g_n3_overflow);
}

static void b2z_plan_print_stats(const struct bluebee_perf_runtime *snapshot,
				 uint8_t final)
{
	uint32_t reached = snapshot->counters.scheduled;

	if (reached > snapshot->config.expected_packets)
		reached = snapshot->config.expected_packets;
	console_print("CONTROL_PLAN_STATS final=%d state=%s run_id=%d "
		      "period_ms=%d tasks=%d planned_slots=%d reached_slots=%d "
		      "elapsed_us=%d generated=%d primary_started=%d "
		      "primary_completed=%d tx_started=%d tx_completed=%d "
		      "deadline_miss=%d dma_timeout=%d "
		      "secondary_dma_late_samples=%d secondary_dma_late_max_us=%d "
		      "secondary_dma_late_avg_us=%d "
		      "time_reference=planned_secondary_start "
		      "rf_mode=%s aux_channel=3 aux_offset_us=%d "
		      "auxptr_dma_window_miss=%d "
		      "auxptr_dma_delta_samples=%d auxptr_dma_delta_min_us=%d "
		      "auxptr_dma_delta_max_us=%d auxptr_dma_delta_avg_us=%d "
		      "retune_failure=%d "
		      "retune_secondary_max_us=%d\r\n",
		      (long)final, (char *)bluebee_perf_state_name(snapshot->state),
		      (long)snapshot->config.run_id,
		      (long)snapshot->config.control.period_ms,
		      (long)snapshot->config.plan_count,
		      (long)snapshot->config.expected_packets, (long)reached,
		      (long)bluebee_perf_elapsed_us(snapshot),
		      (long)snapshot->counters.generated,
		      (long)snapshot->counters.primary_started,
		      (long)snapshot->counters.primary_completed,
		      (long)snapshot->counters.tx_started,
		      (long)snapshot->counters.tx_completed,
		      (long)snapshot->counters.deadline_miss,
		      (long)snapshot->counters.dma_timeout,
		      (long)snapshot->counters.secondary_dma_late_samples,
		      (long)snapshot->counters.secondary_dma_late_max_us,
		      (long)(snapshot->counters.secondary_dma_late_samples ?
			(snapshot->counters.secondary_dma_late_sum_us /
			 snapshot->counters.secondary_dma_late_samples) : 0u),
		      (char *)b2z_rf_mode_name(snapshot->config.control_rf_mode),
		      (long)b2z_aux_offset_us(snapshot->config.control_rf_mode),
		      (long)snapshot->counters.auxptr_dma_window_miss,
		      (long)snapshot->counters.auxptr_dma_delta_samples,
		      (long)snapshot->counters.auxptr_dma_delta_min_us,
		      (long)snapshot->counters.auxptr_dma_delta_max_us,
		      (long)(snapshot->counters.auxptr_dma_delta_samples ?
			(snapshot->counters.auxptr_dma_delta_sum_us /
			 snapshot->counters.auxptr_dma_delta_samples) : 0u),
		      (long)snapshot->counters.retune_failure,
		      (long)snapshot->counters.retune_secondary_max_us);
	if (!final)
		return;

	for (uint32_t i = 0u; i < snapshot->config.plan_count; i++) {
		const struct b2z_plan_entry *entry = &snapshot->config.plan[i];
		uint32_t task_reached = 0u, generated = 0u, primary_started = 0u;
		uint32_t primary_completed = 0u;
		uint32_t tx_started = 0u, tx_completed = 0u, deadline_miss = 0u;
		uint32_t dma_timeout = 0u, auxptr_dma_window_miss = 0u;

		for (uint32_t j = 0u; j < entry->repeats; j++) {
			uint32_t slot = entry->first_slot + j;
			uint8_t flags;

			if (slot >= reached)
				break;
			task_reached++;
			taskENTER_CRITICAL();
			flags = g_control_slot_flags[slot];
			taskEXIT_CRITICAL();
			generated += !!(flags & B2Z_SLOT_GENERATED);
			primary_started += !!(flags & B2Z_SLOT_PRIMARY_STARTED);
			primary_completed += !!(flags & B2Z_SLOT_PRIMARY_COMPLETED);
			tx_started += !!(flags & B2Z_SLOT_TX_STARTED);
			tx_completed += !!(flags & B2Z_SLOT_TX_COMPLETED);
			deadline_miss += !!(flags & B2Z_SLOT_DEADLINE_MISS);
			dma_timeout += !!(flags & B2Z_SLOT_DMA_TIMEOUT);
			auxptr_dma_window_miss +=
				!!(flags & B2Z_SLOT_AUXPTR_DMA_MISS);
		}
		console_print("CONTROL_PLAN_TASK run_id=%d entry=%d command_id=%d "
			      "first_slot=%d repeats=%d reached=%d generated=%d "
			      "execute_at_ms=%d valid_until_ms=%d ble_target=%d ble_opcode=%d ble_arg=%d "
			      "zigbee_target=%d zigbee_opcode=%d zigbee_arg=%d "
			      "primary_started=%d primary_completed=%d "
			      "tx_started=%d tx_completed=%d "
			      "deadline_miss=%d dma_timeout=%d "
			      "auxptr_dma_window_miss=%d\r\n",
			      (long)snapshot->config.run_id, (long)i,
			      (long)entry->packet.command_id, (long)entry->first_slot,
			      (long)entry->repeats, (long)task_reached, (long)generated,
			      (long)entry->packet.execute_at_ms, (long)entry->packet.valid_until_ms,
			      (long)entry->packet.ble_target, (long)entry->packet.ble_opcode, (long)entry->packet.ble_arg,
			      (long)entry->packet.zigbee_target, (long)entry->packet.zigbee_opcode, (long)entry->packet.zigbee_arg,
			      (long)primary_started, (long)primary_completed,
			      (long)tx_started,
			      (long)tx_completed, (long)deadline_miss,
			      (long)dma_timeout,
			      (long)auxptr_dma_window_miss);
	}
	for (uint32_t slot = 0u; slot < reached; slot++) {
		const struct b2z_plan_entry *entry =
			b2z_plan_entry_for_slot(&snapshot->config, slot);
		uint8_t flags;
		uint32_t late_us, aux_delta_us, retune_us;

		if (!entry) {
			console_print("CONTROL_PLAN_SLOT run_id=%d slot=%d invalid_plan=1\r\n",
				      (long)snapshot->config.run_id, (long)slot);
			continue;
		}

		taskENTER_CRITICAL();
		flags = g_control_slot_flags[slot];
		late_us = g_control_slot_late_us[slot];
		aux_delta_us = g_control_slot_aux_delta_us[slot];
		retune_us = g_control_slot_retune_us[slot];
		taskEXIT_CRITICAL();
		console_print("CONTROL_PLAN_SLOT run_id=%d slot=%d entry=%d "
			      "command_id=%d flags=%d generated=%d "
			      "primary_started=%d primary_completed=%d "
			      "tx_started=%d tx_completed=%d deadline_miss=%d "
			      "dma_timeout=%d secondary_dma_late_us=%d "
			      "auxptr_dma_delta_us=%d retune_secondary_us=%d "
			      "auxptr_dma_window_miss=%d\r\n",
			      (long)snapshot->config.run_id, (long)slot,
			      (long)(entry - snapshot->config.plan),
			      (long)entry->packet.command_id, (long)flags,
			      (long)!!(flags & B2Z_SLOT_GENERATED),
			      (long)!!(flags & B2Z_SLOT_PRIMARY_STARTED),
			      (long)!!(flags & B2Z_SLOT_PRIMARY_COMPLETED),
			      (long)!!(flags & B2Z_SLOT_TX_STARTED),
			      (long)!!(flags & B2Z_SLOT_TX_COMPLETED),
			      (long)!!(flags & B2Z_SLOT_DEADLINE_MISS),
			      (long)!!(flags & B2Z_SLOT_DMA_TIMEOUT),
			      (long)late_us, (long)aux_delta_us,
			      (long)retune_us,
			      (long)!!(flags & B2Z_SLOT_AUXPTR_DMA_MISS));
	}
	{
		uint32_t separate = snapshot->config.control_rf_mode == B2Z_CONTROL_RF_SEPARATE_CH3;
		uint32_t attempted = 0u, started = 0u, completed = 0u, ieee_completed = 0u;
		for (uint32_t slot = 0u; slot < snapshot->config.expected_packets; slot++) {
			for (uint32_t kind = 0u; kind < (separate ? 3u : 2u); kind++) {
				const struct b2z_burst_observation *b = &g_control_bursts[slot][kind];
				attempted += b->attempted; started += b->started; completed += b->completed;
				if (kind == (separate ? 2u : 1u)) ieee_completed += b->completed;
				console_print("CONTROL_BURST run_id=%d slot=%d kind=%s generated=%d "
					"attempted=%d started=%d completed=%d timeout=%d "
					"iq_bytes=%d air_us=%d pad_us=%d prepared_us=%d "
					"submit_before_us=%d submit_after_us=%d finish_us=%d\r\n",
					(long)snapshot->config.run_id, (long)slot,
					(char *)(kind == 0u ? "primary" : kind == 2u ? "ieee" : "secondary"),
					(long)b->generated, (long)b->attempted, (long)b->started,
					(long)b->completed, (long)b->timeout,
					(long)b->iq_bytes, (long)b->air_us, (long)b->pad_us,
					(long)b->prepared_us, (long)b->submit_before_us,
					(long)b->submit_after_us, (long)b->finish_us);
			}
		}
		console_print("CONTROL_COST_STATS run_id=%d logical_slots=%d ble_tx_completed=%d "
			"ieee_tx_completed=%d burst_attempted=%d burst_started=%d burst_completed=%d "
			"separate_gap_us=%d reference=dma_software_brackets\r\n",
			(long)snapshot->config.run_id, (long)snapshot->config.expected_packets,
			(long)snapshot->counters.tx_completed, (long)ieee_completed,
			(long)attempted, (long)started, (long)completed,
			(long)(separate ? B2Z_CONTROL_SEPARATE_GAP_US : 0u));
	}

	b2z_print_trace(snapshot);
}

static void bluebee_perf_print_stats(uint8_t final)
{
	struct bluebee_perf_runtime snapshot;

	bluebee_perf_snapshot(&snapshot);
	if (snapshot.config.test == BLUEBEE_PERF_TEST_CONTROL &&
	    snapshot.config.planned) {
		b2z_plan_print_stats(&snapshot, final);
		return;
	}
	if (snapshot.config.test == BLUEBEE_PERF_TEST_CONTROL) {
		console_print("CONTROL_STATS final=%d state=%s run_id=%d "
			      "command_id=%d period_ms=%d attempts=%d "
			      "elapsed_us=%d scheduled=%d generated=%d "
			      "primary_started=%d primary_completed=%d "
			      "tx_started=%d tx_completed=%d "
			      "deadline_miss=%d dma_timeout=%d "
			      "secondary_dma_late_samples=%d "
			      "secondary_dma_late_max_us=%d "
			      "secondary_dma_late_avg_us=%d "
			      "time_reference=planned_secondary_start "
			      "rf_mode=%s aux_channel=3 aux_offset_us=%d "
			      "auxptr_dma_window_miss=%d "
			      "auxptr_dma_delta_samples=%d auxptr_dma_delta_min_us=%d "
			      "auxptr_dma_delta_max_us=%d auxptr_dma_delta_avg_us=%d "
			      "retune_failure=%d "
			      "retune_secondary_max_us=%d\r\n",
			      (long)final,
			      (char *)bluebee_perf_state_name(snapshot.state),
			      (long)snapshot.config.run_id,
			      (long)snapshot.config.control.command_id,
			      (long)snapshot.config.control.period_ms,
			      (long)snapshot.config.expected_packets,
			      (long)bluebee_perf_elapsed_us(&snapshot),
			      (long)snapshot.counters.scheduled,
			      (long)snapshot.counters.generated,
			      (long)snapshot.counters.primary_started,
			      (long)snapshot.counters.primary_completed,
			      (long)snapshot.counters.tx_started,
			      (long)snapshot.counters.tx_completed,
			      (long)snapshot.counters.deadline_miss,
			      (long)snapshot.counters.dma_timeout,
			      (long)snapshot.counters.secondary_dma_late_samples,
			      (long)snapshot.counters.secondary_dma_late_max_us,
			      (long)(snapshot.counters.secondary_dma_late_samples ?
				(snapshot.counters.secondary_dma_late_sum_us /
			 snapshot.counters.secondary_dma_late_samples) : 0u),
			      (char *)b2z_rf_mode_name(snapshot.config.control_rf_mode),
			      (long)b2z_aux_offset_us(snapshot.config.control_rf_mode),
			      (long)snapshot.counters.auxptr_dma_window_miss,
			      (long)snapshot.counters.auxptr_dma_delta_samples,
			      (long)snapshot.counters.auxptr_dma_delta_min_us,
			      (long)snapshot.counters.auxptr_dma_delta_max_us,
			      (long)(snapshot.counters.auxptr_dma_delta_samples ?
				(snapshot.counters.auxptr_dma_delta_sum_us /
				 snapshot.counters.auxptr_dma_delta_samples) : 0u),
			      (long)snapshot.counters.retune_failure,
			      (long)snapshot.counters.retune_secondary_max_us);
		return;
	}
	console_print("PERF_STATS final=%d test=%s state=%s payload_len=%d "
		      "interval_us=%d duration_s=%d run_id=%d mode=%s mode_id=%d "
		      "batch_size=%d expected_packets=%d elapsed_us=%d "
		      "scheduled=%d generated=%d tx_started=%d tx_completed=%d "
		      "deadline_miss=%d dma_timeout=%d\r\n",
		      (long)final,
		      (char *)bluebee_perf_test_name(snapshot.config.test),
		      (char *)bluebee_perf_state_name(snapshot.state),
		      (long)snapshot.config.payload_len,
		      (long)snapshot.config.interval_us,
		      (long)snapshot.config.duration_s,
		      (long)snapshot.config.run_id,
		      (char *)bluebee_perf_mode_name(snapshot.config.mode),
		      (long)snapshot.config.mode,
		      (long)snapshot.config.batch_size,
		      (long)snapshot.config.expected_packets,
		      (long)bluebee_perf_elapsed_us(&snapshot),
		      (long)snapshot.counters.scheduled,
		      (long)snapshot.counters.generated,
		      (long)snapshot.counters.tx_started,
		      (long)snapshot.counters.tx_completed,
		      (long)snapshot.counters.deadline_miss,
		      (long)snapshot.counters.dma_timeout);

#define BLUEBEE_PERF_PRINT_TIMING(stage_name, member) \
	console_print("PERF_TIMING final=%d test=%s stage=" stage_name \
		      " samples=%d min_us=%d max_us=%d avg_us=%d\r\n", \
		      (long)final, \
		      (char *)bluebee_perf_test_name(snapshot.config.test), \
		      (long)snapshot.member.samples, \
		      (long)(snapshot.member.samples ? snapshot.member.min_us : 0u), \
		      (long)(snapshot.member.samples ? snapshot.member.max_us : 0u), \
		      (long)(snapshot.member.samples ? \
			     (snapshot.member.sum_us / snapshot.member.samples) : 0u))

	BLUEBEE_PERF_PRINT_TIMING("frame", frame_time);
	BLUEBEE_PERF_PRINT_TIMING("mapping", mapping_time);
	BLUEBEE_PERF_PRINT_TIMING("gfsk", gfsk_time);
	BLUEBEE_PERF_PRINT_TIMING("total", total_time);
#undef BLUEBEE_PERF_PRINT_TIMING
}

static int32_t bluebee_perf_parse_args(const char *text, uint32_t *values,
				       uint32_t *value_count)
{
	uint32_t count = 0u;

	if (!text || !values || !value_count)
		return -1;

	while (!bluebee_perf_is_line_end(*text)) {
		uint32_t value = 0u;
		uint32_t digits = 0u;

		while (*text == ' ' || *text == '\t')
			text++;
		if (bluebee_perf_is_line_end(*text))
			break;
		if (count >= BLUEBEE_PERF_MAX_ARGS)
			return -1;

		while (*text >= '0' && *text <= '9') {
			uint32_t digit = (uint32_t)(*text - '0');

			if (value > (0xFFFFFFFFu - digit) / 10u)
				return -1;
			value = value * 10u + digit;
			digits++;
			text++;
		}
		if (digits == 0u)
			return -1;
		if (!bluebee_perf_is_line_end(*text) &&
		    *text != ' ' && *text != '\t')
			return -1;
		values[count++] = value;
	}

	*value_count = count;
	return 0;
}

static void bluebee_perf_print_start_usage(enum bluebee_perf_test test)
{
	console_print("Usage: bluebee_%s_perf_start? <payload_len> <interval_us> "
		      "<duration_s> [run_id] [mode] [batch_size]\r\n",
		      (char *)bluebee_perf_test_name(test));
	console_print("Decimal integers only; mode: 0=realtime, 1=batch, 2=double; "
		      "batch_size defaults to 4 and is limited to 8\r\n");
}

static int32_t bluebee_perf_start_cmdline(enum bluebee_perf_test test,
					 const char *args)
{
	uint32_t values[BLUEBEE_PERF_MAX_ARGS] = { 0u };
	uint32_t count = 0u;
	struct bluebee_perf_config config;
	XTime now;

	if (bluebee_perf_parse_args(args, values, &count) < 0 ||
	    count < 3u || count > BLUEBEE_PERF_LEGACY_ARGS) {
		bluebee_perf_print_start_usage(test);
		return -1;
	}

	memset(&config, 0, sizeof(config));
	config.test = test;
	config.payload_len = values[0];
	config.interval_us = values[1];
	config.duration_s = values[2];
	if (count >= 4u) {
		if (values[3] > 0xFFFFu) {
			console_print("PERF_ERROR invalid run_id\r\n");
			return -1;
		}
		config.run_id = (uint16_t)values[3];
	} else {
		XTime_GetTime(&now);
		config.run_id = (uint16_t)((uint32_t)now ^
					   (uint32_t)((uint64_t)now >> 32));
	}
	config.mode = count >= 5u ? (uint8_t)values[4] : 0u;
	config.batch_size = count >= 6u ? values[5] : 0u;

	if (config.payload_len < BLUEBEE_PERF_MIN_PAYLOAD ||
	    config.payload_len > BLUEBEE_PERF_MAX_PAYLOAD ||
	    config.interval_us == 0u ||
	    config.duration_s > BLUEBEE_PERF_MAX_DURATION_S ||
	    (count >= 5u && values[4] > 2u) ||
	    (count >= 6u && (config.mode != 1u || config.batch_size == 0u))) {
		console_print("PERF_ERROR invalid arguments\r\n");
		bluebee_perf_print_start_usage(test);
		return -1;
	}
	if (config.mode == 1u) {
		if (config.batch_size == 0u)
			config.batch_size = BLUEBEE_PERF_BATCH_DEFAULT_SIZE;
		if (config.batch_size > BLUEBEE_PERF_BATCH_MAX_SIZE) {
			console_print("PERF_ERROR batch_size must be in [1, %d]\r\n",
				      (long)BLUEBEE_PERF_BATCH_MAX_SIZE);
			return -1;
		}
	} else {
		config.batch_size = 0u;
	}

	if (config.duration_s != 0u) {
		config.expected_packets =
			(uint32_t)(((uint64_t)config.duration_s * 1000000ULL) /
				   config.interval_us);
	}

	taskENTER_CRITICAL();
	if (!g_perf_task || bluebee_perf_is_busy(g_perf.state) ||
	    g_perf_reporting) {
		taskEXIT_CRITICAL();
		console_print("PERF_ERROR busy\r\n");
		return -1;
	}
	memset(&g_perf, 0, sizeof(g_perf));
	g_perf.config = config;
	g_perf.state = BLUEBEE_PERF_STATE_ARMED;
	taskEXIT_CRITICAL();

	console_print("PERF_START test=%s state=armed payload_len=%d interval_us=%d "
		      "duration_s=%d run_id=%d mode=%s mode_id=%d batch_size=%d "
		      "expected_packets=%d\r\n",
		      (char *)bluebee_perf_test_name(test),
		      (long)config.payload_len,
		      (long)config.interval_us,
		      (long)config.duration_s,
		      (long)config.run_id,
		      (char *)bluebee_perf_mode_name(config.mode),
		      (long)config.mode,
		      (long)config.batch_size,
		      (long)config.expected_packets);
	xTaskNotifyGive(g_perf_task);

	return 0;
}

int32_t bluebee_pure_perf_start_cmdline(const char *args)
{
	return bluebee_perf_start_cmdline(BLUEBEE_PERF_TEST_PURE, args);
}

int32_t bluebee_exadv_perf_start_cmdline(const char *args)
{
	return bluebee_perf_start_cmdline(BLUEBEE_PERF_TEST_EXADV, args);
}

int32_t b2z_control_start_cmdline(const char *args)
{
	uint32_t values[BLUEBEE_PERF_MAX_ARGS] = { 0u };
	uint32_t count = 0u;
	uint32_t base_count;
	uint32_t rf_mode;
	uint32_t period_ms;
	uint32_t attempts;
	uint64_t total_ms;
	struct bluebee_perf_config config;
	struct b2z_control_packet *packet = &config.control;

	if (bluebee_perf_parse_args(args, values, &count) < 0 ||
	    (count != 2u && count != 3u && count != 6u &&
	     count != 7u && count != 12u && count != 13u)) {
		console_print("Usage: b2z_control_start? <run_id> <command_id> "
			      "[period_ms attempts execute_at_ms valid_until_ms "
			      "[ble_target ble_opcode ble_arg zigbee_target "
			      "zigbee_opcode zigbee_arg]] [rf_mode]\r\n");
		return -1;
	}

	memset(&config, 0, sizeof(config));
	base_count = (count == 3u || count == 7u || count == 13u) ?
		count - 1u : count;
	rf_mode = base_count != count ? values[count - 1u] :
		B2Z_CONTROL_RF_SAME_CHANNEL;
	period_ms = base_count >= 6u ? values[2] : 200u;
	attempts = base_count >= 6u ? values[3] : 10u;
	if (values[0] == 0u || values[0] > 0xFFFFu ||
	    values[1] > 0x7FFFFFFFu ||
	    period_ms < 50u || period_ms > 0xFFFFu ||
	    attempts == 0u || rf_mode > B2Z_CONTROL_RF_SEPARATE_CH3 ||
	    (rf_mode != B2Z_CONTROL_RF_SAME_CHANNEL &&
	     period_ms < B2Z_STANDARD_MIN_PERIOD_MS)) {
		console_print("CONTROL_ERROR invalid run, command, period or attempts\r\n");
		return -1;
	}
	total_ms = (uint64_t)period_ms * attempts;
	if (total_ms > 600000ULL) {
		console_print("CONTROL_ERROR schedule exceeds 600 seconds\r\n");
		return -1;
	}

	config.test = BLUEBEE_PERF_TEST_CONTROL;
	config.payload_len = B2Z_CONTROL_RECORD_BYTES;
	config.interval_us = period_ms * 1000u;
	config.duration_s = (uint32_t)((total_ms + 999ULL) / 1000ULL);
	config.run_id = (uint16_t)values[0];
	config.mode = 0u;
	config.control_rf_mode = (uint8_t)rf_mode;
	config.expected_packets = attempts;
	packet->run_id = config.run_id;
	packet->period_ms = (uint16_t)period_ms;
	packet->command_id = values[1];
	packet->execute_at_ms = base_count >= 6u ? values[4] : 3000u;
	packet->valid_until_ms = base_count >= 6u ? values[5] : 2500u;
	packet->ble_target = 1u;
	packet->ble_opcode = 1u;
	packet->ble_arg = 1u;
	packet->zigbee_target = 2u;
	packet->zigbee_opcode = 1u;
	packet->zigbee_arg = 1u;
	if (base_count == 12u) {
		if (values[6] > 0xFFFFu || values[7] > 2u ||
		    values[8] > 0xFFFFu || values[9] > 0xFFFFu ||
		    values[10] > 2u || values[11] > 0xFFFFu) {
			console_print("CONTROL_ERROR invalid side command\r\n");
			return -1;
		}
		packet->ble_target = (uint16_t)values[6];
		packet->ble_opcode = (uint8_t)values[7];
		packet->ble_arg = (uint16_t)values[8];
		packet->zigbee_target = (uint16_t)values[9];
		packet->zigbee_opcode = (uint8_t)values[10];
		packet->zigbee_arg = (uint16_t)values[11];
	}
	if (packet->command_id == 0u) {
		if (base_count >= 6u && (values[4] != 0u || values[5] != 0u)) {
			console_print("CONTROL_ERROR sync-only needs zero times\r\n");
			return -1;
		}
		if (base_count == 12u &&
		    (values[6] != 0u || values[7] != 0u ||
		     values[8] != 0u || values[9] != 0u ||
		     values[10] != 0u || values[11] != 0u)) {
			console_print("CONTROL_ERROR sync-only needs zero side fields\r\n");
			return -1;
		}
		packet->execute_at_ms = 0u;
		packet->valid_until_ms = 0u;
		packet->ble_target = 0u;
		packet->ble_opcode = 0u;
		packet->ble_arg = 0u;
		packet->zigbee_target = 0u;
		packet->zigbee_opcode = 0u;
		packet->zigbee_arg = 0u;
	} else if (packet->ble_target == 0u ||
		   packet->zigbee_target == 0u ||
		   (packet->ble_opcode == 0u && packet->ble_arg != 0u) ||
		   (packet->zigbee_opcode == 0u && packet->zigbee_arg != 0u) ||
		   packet->valid_until_ms <
			(uint32_t)((uint64_t)(attempts - 1u) * period_ms) ||
		   packet->valid_until_ms >= packet->execute_at_ms ||
		   packet->execute_at_ms > 86400000u) {
		console_print("CONTROL_ERROR invalid target, deadline or opcode\r\n");
		return -1;
	}

	taskENTER_CRITICAL();
	if (!g_perf_task || bluebee_perf_is_busy(g_perf.state) ||
	    g_perf_reporting) {
		taskEXIT_CRITICAL();
		console_print("CONTROL_ERROR busy\r\n");
		return -1;
	}
	memset(&g_perf, 0, sizeof(g_perf));
	g_perf.config = config;
	g_perf.state = BLUEBEE_PERF_STATE_ARMED;
	taskEXIT_CRITICAL();
	console_print("CONTROL_START state=armed run_id=%d command_id=%d "
		      "period_ms=%d attempts=%d execute_at_ms=%d "
		      "valid_until_ms=%d ble_target=%d ble_opcode=%d ble_arg=%d "
		      "zigbee_target=%d zigbee_opcode=%d zigbee_arg=%d "
		      "rf_mode=%s aux_channel=3 aux_offset_us=%d "
		      "primary_mhz=2480 secondary_mhz=%d\r\n",
		      (long)packet->run_id, (long)packet->command_id,
		      (long)period_ms, (long)attempts,
		      (long)packet->execute_at_ms,
		      (long)packet->valid_until_ms,
		      (long)packet->ble_target, (long)packet->ble_opcode,
		      (long)packet->ble_arg, (long)packet->zigbee_target,
		      (long)packet->zigbee_opcode,
		      (long)packet->zigbee_arg,
		      (char *)b2z_rf_mode_name(config.control_rf_mode),
		      (long)b2z_aux_offset_us(config.control_rf_mode),
		      (long)(config.control_rf_mode !=
			B2Z_CONTROL_RF_SAME_CHANNEL ? 2410u : 2480u));
	xTaskNotifyGive(g_perf_task);
	return 0;
}

static int32_t bluebee_perf_require_no_args(const char *args,
					    const char *usage)
{
	if (!args)
		return 0;
	while (*args == ' ' || *args == '\t')
		args++;
	if (bluebee_perf_is_line_end(*args))
		return 0;
	console_print("Usage: %s\r\n", (char *)usage);
	return -1;
}

int32_t b2z_plan_clear_cmdline(const char *args)
{
	if (bluebee_perf_require_no_args(args, "b2z_plan_clear?") < 0)
		return -1;
	taskENTER_CRITICAL();
	if (bluebee_perf_is_busy(g_perf.state) || g_perf_reporting) {
		taskEXIT_CRITICAL();
		console_print("CONTROL_PLAN_ERROR busy\r\n");
		return -1;
	}
	memset(g_plan_draft, 0, sizeof(g_plan_draft));
	g_plan_draft_count = 0u;
	taskEXIT_CRITICAL();
	console_print("CONTROL_PLAN_CLEAR entries=0\r\n");
	return 0;
}

int32_t b2z_plan_add_cmdline(const char *args)
{
	uint32_t values[BLUEBEE_PERF_MAX_ARGS] = { 0u };
	uint32_t count = 0u;
	uint32_t first_slot = 0u;
	struct b2z_plan_entry entry;
	struct b2z_control_packet *packet = &entry.packet;
	uint8_t entry_index;

	if (bluebee_perf_parse_args(args, values, &count) < 0 ||
	    (count != 4u && count != 10u)) {
		console_print("Usage: b2z_plan_add? <command_id> <repeats> "
			      "<execute_at_ms> <valid_until_ms> "
			      "[ble_target ble_opcode ble_arg zigbee_target "
			      "zigbee_opcode zigbee_arg]\r\n");
		return -1;
	}
	if (values[0] > 0x7FFFFFFFu || values[1] == 0u ||
	    values[1] > B2Z_PLAN_MAX_SLOTS || values[2] > 86400000u) {
		console_print("CONTROL_PLAN_ERROR invalid command, repeats or time\r\n");
		return -1;
	}
	memset(&entry, 0, sizeof(entry));
	entry.repeats = (uint16_t)values[1];
	packet->command_id = values[0];
	packet->execute_at_ms = values[2];
	packet->valid_until_ms = values[3];
	if (packet->command_id == 0u) {
		if (count != 4u || values[2] != 0u || values[3] != 0u) {
			console_print("CONTROL_PLAN_ERROR sync-only needs zero times and no side fields\r\n");
			return -1;
		}
	} else {
		packet->ble_target = 1u;
		packet->ble_opcode = 1u;
		packet->ble_arg = 1u;
		packet->zigbee_target = 2u;
		packet->zigbee_opcode = 1u;
		packet->zigbee_arg = 1u;
		if (count == 10u) {
			if (values[4] > 0xFFFFu || values[5] > 2u ||
			    values[6] > 0xFFFFu || values[7] > 0xFFFFu ||
			    values[8] > 2u || values[9] > 0xFFFFu) {
				console_print("CONTROL_PLAN_ERROR invalid side command\r\n");
				return -1;
			}
			packet->ble_target = (uint16_t)values[4];
			packet->ble_opcode = (uint8_t)values[5];
			packet->ble_arg = (uint16_t)values[6];
			packet->zigbee_target = (uint16_t)values[7];
			packet->zigbee_opcode = (uint8_t)values[8];
			packet->zigbee_arg = (uint16_t)values[9];
		}
		if (packet->ble_target == 0u || packet->zigbee_target == 0u ||
		    (packet->ble_opcode == 0u && packet->ble_arg != 0u) ||
		    (packet->zigbee_opcode == 0u && packet->zigbee_arg != 0u) ||
		    packet->valid_until_ms >= packet->execute_at_ms) {
			console_print("CONTROL_PLAN_ERROR invalid target or deadline\r\n");
			return -1;
		}
	}

	taskENTER_CRITICAL();
	if (bluebee_perf_is_busy(g_perf.state) || g_perf_reporting ||
	    g_plan_draft_count >= B2Z_PLAN_MAX_ENTRIES) {
		taskEXIT_CRITICAL();
		console_print("CONTROL_PLAN_ERROR busy or full\r\n");
		return -1;
	}
	for (uint32_t i = 0u; i < g_plan_draft_count; i++) {
		if (packet->command_id != 0u &&
		    g_plan_draft[i].packet.command_id == packet->command_id) {
			taskEXIT_CRITICAL();
			console_print("CONTROL_PLAN_ERROR duplicate command_id\r\n");
			return -1;
		}
		first_slot += g_plan_draft[i].repeats;
	}
	if (first_slot + entry.repeats > B2Z_PLAN_MAX_SLOTS) {
		taskEXIT_CRITICAL();
		console_print("CONTROL_PLAN_ERROR too many slots\r\n");
		return -1;
	}
	entry.first_slot = (uint16_t)first_slot;
	entry_index = g_plan_draft_count;
	g_plan_draft[g_plan_draft_count++] = entry;
	taskEXIT_CRITICAL();
	console_print("CONTROL_PLAN_ADD entry=%d command_id=%d first_slot=%d "
		      "repeats=%d execute_at_ms=%d valid_until_ms=%d "
		      "ble_target=%d ble_opcode=%d ble_arg=%d "
		      "zigbee_target=%d zigbee_opcode=%d zigbee_arg=%d\r\n",
		      (long)entry_index, (long)packet->command_id,
		      (long)entry.first_slot, (long)entry.repeats,
		      (long)packet->execute_at_ms, (long)packet->valid_until_ms,
		      (long)packet->ble_target, (long)packet->ble_opcode,
		      (long)packet->ble_arg, (long)packet->zigbee_target,
		      (long)packet->zigbee_opcode, (long)packet->zigbee_arg);
	return 0;
}

int32_t b2z_plan_start_cmdline(const char *args)
{
	uint32_t values[BLUEBEE_PERF_MAX_ARGS] = { 0u };
	uint32_t count = 0u;
	uint32_t slots = 0u;
	struct bluebee_perf_config config;

	if (bluebee_perf_parse_args(args, values, &count) < 0 ||
	    (count != 2u && count != 3u)) {
		console_print("Usage: b2z_plan_start? <run_id> <period_ms> "
			      "[rf_mode]\r\n");
		return -1;
	}
	if (values[0] == 0u || values[0] > 0xFFFFu ||
	    values[1] < 50u || values[1] > 0xFFFFu ||
	    (count == 3u && values[2] > B2Z_CONTROL_RF_SEPARATE_CH3) ||
	    (count == 3u && values[2] != B2Z_CONTROL_RF_SAME_CHANNEL &&
	     values[1] < B2Z_STANDARD_MIN_PERIOD_MS)) {
		console_print("CONTROL_PLAN_ERROR invalid run or period\r\n");
		return -1;
	}
	memset(&config, 0, sizeof(config));
	config.test = BLUEBEE_PERF_TEST_CONTROL;
	config.payload_len = B2Z_CONTROL_RECORD_BYTES;
	config.interval_us = values[1] * 1000u;
	config.run_id = (uint16_t)values[0];
	config.mode = 0u;
	config.planned = 1u;
	config.control_rf_mode = count == 3u ? (uint8_t)values[2] :
		B2Z_CONTROL_RF_SAME_CHANNEL;
	config.control.period_ms = (uint16_t)values[1];

	taskENTER_CRITICAL();
	if (!g_perf_task || bluebee_perf_is_busy(g_perf.state) ||
	    g_perf_reporting ||
	    g_plan_draft_count == 0u) {
		taskEXIT_CRITICAL();
		console_print("CONTROL_PLAN_ERROR busy, no task or worker unavailable\r\n");
		return -1;
	}
	config.plan_count = g_plan_draft_count;
	memcpy(config.plan, g_plan_draft,
	       config.plan_count * sizeof(config.plan[0]));
	taskEXIT_CRITICAL();
	for (uint32_t i = 0u; i < config.plan_count; i++) {
		struct b2z_plan_entry *entry = &config.plan[i];
		uint32_t last_slot = entry->first_slot + entry->repeats - 1u;

		slots += entry->repeats;
		entry->packet.run_id = config.run_id;
		entry->packet.period_ms = config.control.period_ms;
		if (entry->packet.command_id != 0u &&
		    (entry->packet.valid_until_ms < last_slot * values[1] ||
		     entry->packet.valid_until_ms >=
			entry->packet.execute_at_ms)) {
			console_print("CONTROL_PLAN_ERROR entry=%d deadline precedes last slot\r\n",
				      (long)i);
			return -1;
		}
	}
	if ((uint64_t)slots * values[1] > 600000ULL) {
		console_print("CONTROL_PLAN_ERROR schedule exceeds 600 seconds\r\n");
		return -1;
	}
	config.expected_packets = slots;
	config.duration_s = (uint32_t)(((uint64_t)slots * values[1] + 999ULL) /
				       1000ULL);
	taskENTER_CRITICAL();
	if (!g_perf_task || bluebee_perf_is_busy(g_perf.state) ||
	    g_perf_reporting) {
		taskEXIT_CRITICAL();
		console_print("CONTROL_PLAN_ERROR busy\r\n");
		return -1;
	}
	memset(&g_perf, 0, sizeof(g_perf));
	memset(g_control_slot_flags, 0, sizeof(g_control_slot_flags));
	memset(g_control_bursts, 0, sizeof(g_control_bursts));
	memset(g_n3_trace, 0, sizeof(g_n3_trace));
	memset(g_n3_primary_anchor, 0, sizeof(g_n3_primary_anchor));
	g_n3_overflow = 0;
	memset(g_control_slot_late_us, 0, sizeof(g_control_slot_late_us));
	memset(g_control_slot_aux_delta_us, 0,
	       sizeof(g_control_slot_aux_delta_us));
	memset(g_control_slot_retune_us, 0,
	       sizeof(g_control_slot_retune_us));
	g_perf.config = config;
	g_perf.state = BLUEBEE_PERF_STATE_ARMED;
	taskEXIT_CRITICAL();
	console_print("CONTROL_PLAN_START state=armed run_id=%d period_ms=%d "
		      "tasks=%d slots=%d duration_s=%d "
		      "rf_mode=%s aux_channel=3 aux_offset_us=%d "
		      "primary_mhz=2480 secondary_mhz=%d\r\n",
		      (long)config.run_id, (long)values[1],
		      (long)config.plan_count, (long)slots,
		      (long)config.duration_s,
		      (char *)b2z_rf_mode_name(config.control_rf_mode),
		      (long)b2z_aux_offset_us(config.control_rf_mode),
		      (long)(config.control_rf_mode !=
			B2Z_CONTROL_RF_SAME_CHANNEL ? 2410u : 2480u));
	for (uint32_t i = 0u; i < config.plan_count; i++) {
		const struct b2z_plan_entry *entry = &config.plan[i];
		console_print("CONTROL_PLAN_ENTRY run_id=%d entry=%d "
			      "command_id=%d first_slot=%d repeats=%d "
			      "execute_at_ms=%d valid_until_ms=%d "
			      "ble_target=%d ble_opcode=%d ble_arg=%d "
			      "zigbee_target=%d zigbee_opcode=%d zigbee_arg=%d\r\n",
			      (long)config.run_id, (long)i,
			      (long)entry->packet.command_id,
			      (long)entry->first_slot, (long)entry->repeats,
			      (long)entry->packet.execute_at_ms,
			      (long)entry->packet.valid_until_ms,
			      (long)entry->packet.ble_target,
			      (long)entry->packet.ble_opcode,
			      (long)entry->packet.ble_arg,
			      (long)entry->packet.zigbee_target,
			      (long)entry->packet.zigbee_opcode,
			      (long)entry->packet.zigbee_arg);
	}
	xTaskNotifyGive(g_perf_task);
	return 0;
}

int32_t bluebee_perf_stop_cmdline(const char *args)
{
	enum bluebee_perf_state state;

	if (bluebee_perf_require_no_args(args, "bluebee_perf_stop?") < 0)
		return -1;

	taskENTER_CRITICAL();
	state = g_perf.state;
	if (bluebee_perf_is_busy(state)) {
		g_perf.stop_requested = 1u;
		g_perf.state = BLUEBEE_PERF_STATE_STOPPING;
	}
	taskEXIT_CRITICAL();

	if (bluebee_perf_is_busy(state)) {
		console_print(g_perf.config.test == BLUEBEE_PERF_TEST_CONTROL ?
			      "CONTROL_STOP requested\r\n" :
			      "PERF_STOP requested\r\n");
		return 0;
	}

	bluebee_perf_print_stats(1u);
	return 0;
}

int32_t bluebee_perf_status_cmdline(const char *args)
{
	if (bluebee_perf_require_no_args(args, "bluebee_perf_status?") < 0)
		return -1;
	bluebee_perf_print_stats(0u);
	return 0;
}

static uint8_t bluebee_perf_stop_requested(void)
{
	uint8_t stop;

	taskENTER_CRITICAL();
	stop = g_perf.stop_requested;
	taskEXIT_CRITICAL();

	return stop;
}

static int32_t bluebee_perf_wait_until(XTime deadline, uint8_t stop_sensitive)
{
	for (;;) {
		XTime now;
		uint32_t remaining_us;

		if (stop_sensitive && bluebee_perf_stop_requested())
			return -1;
		XTime_GetTime(&now);
		if (now >= deadline)
			return 0;
		remaining_us = bluebee_perf_ticks_to_us(deadline - now);
		if (remaining_us > BLUEBEE_PERF_WAIT_SLEEP_US) {
			uint32_t sleep_ms =
				(remaining_us - BLUEBEE_PERF_WAIT_SPIN_US) / 1000u;
			TickType_t ticks;

			if (sleep_ms > BLUEBEE_PERF_MAX_SLEEP_MS)
				sleep_ms = BLUEBEE_PERF_MAX_SLEEP_MS;
			ticks = pdMS_TO_TICKS(sleep_ms);
			if (ticks > 0u) {
				vTaskDelay(ticks);
				continue;
			}
		}
		taskYIELD();
	}
}

/* Leave the scheduler before the narrow AuxPtr window. */
static int32_t b2z_wait_aux_target(XTime target)
{
	XTime spin_start = target -
		bluebee_perf_ticks_from_us(B2Z_AUX_WAIT_SPIN_US);

	if (bluebee_perf_wait_until(spin_start, 1u) < 0)
		return -1;
	for (;;) {
		XTime now;

		if (bluebee_perf_stop_requested())
			return -1;
		XTime_GetTime(&now);
		if (now >= target)
			return 0;
	}
}

static int32_t bluebee_perf_prepare_tx(void)
{
	int32_t ret = 0;

	if (!ad9361_phy || !ad9361_phy->tx_dac || !tx_dmac)
		return -1;

	ble_tx_adv_stop(0u);
	ble_tx_adv_tx_lock();
	axi_dmac_transfer_stop(tx_dmac);
	ret |= axi_dac_set_datasel(ad9361_phy->tx_dac, -1,
				   AXI_DAC_DATA_SEL_DMA);
	ret |= no_os_gpio_set_value(ad9361_phy->gpio_desc_tx1_ctrl_h, 0);
	ret |= no_os_gpio_set_value(ad9361_phy->gpio_desc_tx1_ctrl_l, 1);
	ret |= no_os_gpio_set_value(ad9361_phy->gpio_desc_tx2_ctrl_h, 0);
	ret |= no_os_gpio_set_value(ad9361_phy->gpio_desc_tx2_ctrl_l, 1);
	ret |= ad9361_set_tx_rf_port_output(ad9361_phy, TXB);
	ret |= ad9361_set_tx_lo_freq(ad9361_phy, BLUEBEE_GEN_TX_LO_HZ);

#ifdef XILINX_PLATFORM
	Xil_DCacheFlushRange((uintptr_t)ble_exadv_primary_iq_ch39,
			     BLE_EXADV_PRIMARY_IQ_CH39_WORDS * sizeof(uint32_t));
#endif

	if (ret < 0) {
		axi_dmac_transfer_stop(tx_dmac);
		axi_dac_set_datasel(ad9361_phy->tx_dac, -1,
				    AXI_DAC_DATA_SEL_DDS);
		ble_tx_adv_tx_unlock();
		return -1;
	}

	return 0;
}

static void bluebee_perf_release_tx(void)
{
	if (tx_dmac)
		axi_dmac_transfer_stop(tx_dmac);
	if (ad9361_phy && ad9361_phy->tx_dac)
		axi_dac_set_datasel(ad9361_phy->tx_dac, -1,
				    AXI_DAC_DATA_SEL_DDS);
	ble_tx_adv_tx_unlock();
}

static int32_t bluebee_perf_dma_start_traced(const uint32_t *iq_words,
				      uint32_t iq_byte_count, struct b2z_trace *trace)
{
	struct axi_dma_transfer transfer;
	int32_t clear_ret;

	if (!iq_words || iq_byte_count == 0u)
		return -1;

	b2z_trace_mark(trace, N3_STOP_CLEAR, 0, 0);
	axi_dmac_transfer_stop(tx_dmac);
	clear_ret = axi_dmac_write(tx_dmac, AXI_DMAC_REG_IRQ_PENDING,
		       AXI_DMAC_IRQ_SOT | AXI_DMAC_IRQ_EOT);
	b2z_trace_mark(trace, N3_STOP_CLEAR, 1, clear_ret);
#ifdef XILINX_PLATFORM
	b2z_trace_mark(trace, N3_CACHE, 0, 0);
	Xil_DCacheFlushRange((uintptr_t)iq_words, iq_byte_count);
	b2z_trace_mark(trace, N3_CACHE, 1, 0);
#endif
	transfer.size = iq_byte_count;
	transfer.transfer_done = 0;
	transfer.cyclic = NO;
	transfer.src_addr = (uintptr_t)iq_words;
	transfer.dest_addr = 0;
	b2z_trace_mark(trace, N3_DAC_SYNC, 0, 0);
	no_os_axi_io_write(ad9361_phy->tx_dac->base,
			   BLUEBEE_PERF_AXI_DAC_SYNC_CONTROL,
			   BLUEBEE_PERF_AXI_DAC_SYNC);

	b2z_trace_mark(trace, N3_DAC_SYNC, 1, 0);
	if (trace) {
		const struct axi_dmac_submit_observer observer = {b2z_submit_mark, trace};
		int32_t ret = axi_dmac_transfer_start_observed(tx_dmac, &transfer, &observer);
		trace->remaining_bytes = tx_dmac->remaining_size;
		return ret;
	}
	return axi_dmac_transfer_start(tx_dmac, &transfer);
}

static int32_t bluebee_perf_dma_start(const uint32_t *iq_words, uint32_t bytes)
{
	return bluebee_perf_dma_start_traced(iq_words, bytes, NULL);
}

static bool bluebee_perf_dma_complete(void)
{
	bool ready = false;

	if (tx_dmac->irq_option == IRQ_DISABLED) {
		uint32_t pending = 0u;
		uint32_t submit = AXI_DMAC_QUEUE_FULL;
		uint32_t transfer_done = 0u;

		(void)axi_dmac_read(tx_dmac, AXI_DMAC_REG_IRQ_PENDING,
				    &pending);
		(void)axi_dmac_read(tx_dmac, AXI_DMAC_REG_TRANSFER_SUBMIT,
				    &submit);
		(void)axi_dmac_read(tx_dmac, AXI_DMAC_REG_TRANSFER_DONE,
				    &transfer_done);
		pending &= AXI_DMAC_IRQ_SOT | AXI_DMAC_IRQ_EOT;
		if (pending != 0u)
			(void)axi_dmac_write(tx_dmac, AXI_DMAC_REG_IRQ_PENDING,
					     pending);
		/*
		 * With IRQs masked, this DMAC exposes completion through the done
		 * bitmap even though IRQ_PENDING remains zero.  Require the submit
		 * request to have been accepted so stale state cannot complete a new
		 * transfer while stop/start reset is still in progress.
		 */
		if (((pending & AXI_DMAC_IRQ_EOT) != 0u) ||
		    (((submit & AXI_DMAC_QUEUE_FULL) == 0u) &&
		     ((transfer_done & 0x0Fu) != 0u))) {
			tx_dmac->transfer.transfer_done = true;
			return true;
		}
		return false;
	}

	if (tx_dmac->irq_option == IRQ_ENABLED) {
		/* The global poll task may have already persisted completion. */
		(void)axi_dmac_poll_pending(tx_dmac);
		(void)axi_dmac_is_transfer_ready(tx_dmac, &ready);
	}

	return ready;
}

static void bluebee_perf_dma_print_timeout(void)
{
	uint32_t pending = 0u;
	uint32_t submit = 0u;
	uint32_t transfer_done = 0u;

	(void)axi_dmac_read(tx_dmac, AXI_DMAC_REG_IRQ_PENDING, &pending);
	(void)axi_dmac_read(tx_dmac, AXI_DMAC_REG_TRANSFER_SUBMIT, &submit);
	(void)axi_dmac_read(tx_dmac, AXI_DMAC_REG_TRANSFER_DONE,
			    &transfer_done);
	console_print("PERF_DMA_TIMEOUT irq=%s pending=0x%08x submit=0x%08x "
		      "transfer_done=0x%08x\r\n",
		      tx_dmac->irq_option == IRQ_ENABLED ? "enabled" : "disabled",
		      (long)pending, (long)submit, (long)transfer_done);
}

static int32_t bluebee_perf_dma_wait(uint32_t timeout_us)
{
	XTime start;
	XTime deadline;

	XTime_GetTime(&start);
	deadline = start + bluebee_perf_ticks_from_us(timeout_us);
	for (;;) {
		XTime now;

		if (bluebee_perf_dma_complete())
			return 0;
		XTime_GetTime(&now);
		if (now >= deadline) {
			if (bluebee_perf_dma_complete())
				return 0;
			bluebee_perf_dma_print_timeout();
			axi_dmac_transfer_stop(tx_dmac);
			return -1;
		}
		if (bluebee_perf_ticks_to_us(deadline - now) >
		    BLUEBEE_PERF_WAIT_SLEEP_US)
			vTaskDelay(pdMS_TO_TICKS(1u));
		else
			taskYIELD();
	}
}

static int32_t bluebee_perf_dma_wait_deadline(XTime deadline)
{
	for (;;) {
		XTime now;

		if (bluebee_perf_dma_complete())
			return 0;
		XTime_GetTime(&now);
		if (now >= deadline) {
			if (bluebee_perf_dma_complete())
				return 0;
			bluebee_perf_dma_print_timeout();
			axi_dmac_transfer_stop(tx_dmac);
			return -1;
		}
		if (bluebee_perf_ticks_to_us(deadline - now) >
		    BLUEBEE_PERF_WAIT_SLEEP_US)
			vTaskDelay(pdMS_TO_TICKS(1u));
		else
			taskYIELD();
	}
}

static int32_t bluebee_perf_generate(enum bluebee_perf_test test,
				     const uint8_t *payload,
				     uint32_t payload_len,
				     const uint32_t **iq_words,
				     uint32_t *iq_byte_count,
				     uint32_t *tx_time_us,
				     struct bluebee_perf_gen_timing *timing)
{
	if (!timing)
		return -1;
	memset(timing, 0, sizeof(*timing));

	if (test == BLUEBEE_PERF_TEST_PURE) {
		const struct bluebee_gen_meta *meta;

		if (bluebee_gen_build_payload(payload, payload_len) < 0)
			return -1;
		meta = bluebee_gen_get_last_meta();
		*iq_words = meta->iq_words;
		*iq_byte_count = meta->iq_byte_count;
		*tx_time_us = meta->pre_pad_us + meta->air_us +
			meta->post_pad_us;
		timing->frame_us = meta->frame_time_us;
		timing->mapping_us = meta->mapping_time_us;
		timing->gfsk_us = meta->gfsk_time_us;
		timing->total_us = meta->total_time_us;
		return 0;
	}

	{
		const struct ble_exadv_secondary_gen_meta *meta;

		if (ble_exadv_secondary_gen_build_payload(payload, payload_len) < 0)
			return -1;
		meta = ble_exadv_secondary_gen_get_last_meta();
		*iq_words = meta->iq_words;
		*iq_byte_count = meta->iq_byte_count;
		*tx_time_us = meta->air_us + meta->post_pad_us;
		timing->frame_us = meta->frame_time_us;
		timing->mapping_us = meta->mapping_time_us;
		timing->gfsk_us = meta->gfsk_time_us;
		timing->total_us = meta->total_time_us;
	}

	return 0;
}

static void bluebee_perf_count(uint32_t *counter)
{
	taskENTER_CRITICAL();
	(*counter)++;
	taskEXIT_CRITICAL();
}

static void bluebee_perf_time_add(struct bluebee_perf_time_stats *stats,
				  uint32_t sample_us)
{
	if (stats->samples == 0u || sample_us < stats->min_us)
		stats->min_us = sample_us;
	if (stats->samples == 0u || sample_us > stats->max_us)
		stats->max_us = sample_us;
	stats->sum_us += sample_us;
	stats->samples++;
}

static void bluebee_perf_record_timing(
	const struct bluebee_perf_gen_timing *timing)
{
	taskENTER_CRITICAL();
	bluebee_perf_time_add(&g_perf.frame_time, timing->frame_us);
	bluebee_perf_time_add(&g_perf.mapping_time, timing->mapping_us);
	bluebee_perf_time_add(&g_perf.gfsk_time, timing->gfsk_us);
	bluebee_perf_time_add(&g_perf.total_time, timing->total_us);
	taskEXIT_CRITICAL();
}

static int32_t bluebee_perf_prepare_waveform(
	const struct bluebee_perf_config *config,
	uint32_t sequence,
	uint32_t arena_slot,
	struct bluebee_perf_prepared *prepared)
{
	uint8_t payload[BLUEBEE_PERF_MAX_PAYLOAD];
	const uint32_t *generated_iq = NULL;
	uint32_t iq_byte_count = 0u;
	uint32_t tx_time_us = 0u;
	struct bluebee_perf_gen_timing timing;

	if (!config || !prepared ||
	    arena_slot >= BLUEBEE_PERF_BATCH_MAX_SIZE)
		return -1;

	bluebee_perf_build_payload(payload, config->payload_len,
				    config->run_id, sequence);
	if (bluebee_perf_generate(config->test, payload, config->payload_len,
				  &generated_iq, &iq_byte_count, &tx_time_us,
				  &timing) < 0)
		return -1;
	if (iq_byte_count >
	    BLUEBEE_PERF_IQ_WORD_CAPACITY * sizeof(uint32_t))
		return -1;

	memcpy(g_perf_iq_arena[arena_slot], generated_iq, iq_byte_count);
	prepared->iq_words = g_perf_iq_arena[arena_slot];
	prepared->iq_byte_count = iq_byte_count;
	prepared->tx_time_us = tx_time_us;
	prepared->sequence = sequence;
	prepared->timing = timing;
	prepared->valid = 1u;
	bluebee_perf_record_timing(&timing);
	bluebee_perf_count(&g_perf.counters.generated);

	return 0;
}

static int32_t bluebee_perf_start_prepared(
	const struct bluebee_perf_config *config,
	const struct bluebee_perf_prepared *prepared,
	XTime *dma_deadline)
{
	XTime dma_start;

	if (!config || !prepared || !prepared->valid || !dma_deadline)
		return -1;

	if (config->test == BLUEBEE_PERF_TEST_EXADV) {
		XTime primary_start;

		XTime_GetTime(&primary_start);
		if (bluebee_perf_dma_start(ble_exadv_primary_iq_ch39,
					    BLE_EXADV_PRIMARY_IQ_CH39_WORDS *
						    sizeof(uint32_t)) < 0)
			return -1;
		if (bluebee_perf_dma_wait(BLUEBEE_PERF_PRIMARY_TIMEOUT_US) < 0) {
			bluebee_perf_count(&g_perf.counters.dma_timeout);
			return -1;
		}
		if (bluebee_perf_wait_until(
			    primary_start +
				    bluebee_perf_ticks_from_us(BLUEBEE_PERF_AUX_OFFSET_US),
			    1u) < 0)
			return -1;
	}

	if (bluebee_perf_stop_requested())
		return -1;
	if (bluebee_perf_dma_start(prepared->iq_words,
				    prepared->iq_byte_count) < 0)
		return -1;
	bluebee_perf_count(&g_perf.counters.tx_started);
	XTime_GetTime(&dma_start);
	*dma_deadline = dma_start + bluebee_perf_ticks_from_us(
		prepared->tx_time_us + BLUEBEE_PERF_DMA_MARGIN_US);

	return 0;
}

static int32_t bluebee_perf_finish_prepared(XTime dma_deadline)
{
	if (bluebee_perf_dma_wait_deadline(dma_deadline) < 0) {
		bluebee_perf_count(&g_perf.counters.dma_timeout);
		return -1;
	}
	bluebee_perf_count(&g_perf.counters.tx_completed);

	return 0;
}

static int32_t bluebee_perf_send_prepared(
	const struct bluebee_perf_config *config,
	const struct bluebee_perf_prepared *prepared)
{
	XTime dma_deadline;

	if (bluebee_perf_start_prepared(config, prepared, &dma_deadline) < 0)
		return -1;

	return bluebee_perf_finish_prepared(dma_deadline);
}

static int32_t bluebee_perf_prepare_batch(
	const struct bluebee_perf_config *config,
	uint32_t first_sequence,
	struct bluebee_perf_prepared *prepared,
	uint32_t *prepared_count)
{
	uint32_t count;

	if (!config || !prepared || !prepared_count ||
	    config->mode != 1u || config->batch_size == 0u ||
	    config->batch_size > BLUEBEE_PERF_BATCH_MAX_SIZE)
		return -1;

	count = config->batch_size;
	if (config->duration_s != 0u) {
		uint32_t remaining = config->expected_packets > first_sequence ?
			config->expected_packets - first_sequence : 0u;

		if (count > remaining)
			count = remaining;
	}

	for (uint32_t i = 0u; i < count; i++) {
		prepared[i].valid = 0u;
		if (bluebee_perf_stop_requested())
			return -1;
		if (bluebee_perf_prepare_waveform(config, first_sequence + i,
						   i, &prepared[i]) < 0)
			return -1;
	}
	*prepared_count = count;

	return 0;
}

static int32_t bluebee_perf_send_double(
	const struct bluebee_perf_config *config,
	const struct bluebee_perf_prepared *current,
	uint32_t next_sequence,
	uint8_t prepare_next,
	uint32_t next_arena_slot,
	struct bluebee_perf_prepared *next)
{
	XTime dma_deadline;
	int32_t prepare_ret = 0;
	int32_t finish_ret;

	if (bluebee_perf_start_prepared(config, current, &dma_deadline) < 0)
		return -1;

	if (prepare_next) {
		next->valid = 0u;
		prepare_ret = bluebee_perf_prepare_waveform(
			config, next_sequence, next_arena_slot, next);
	}
	finish_ret = bluebee_perf_finish_prepared(dma_deadline);

	return (prepare_ret < 0 || finish_ret < 0) ? -1 : 0;
}

static void bluebee_perf_set_scheduled(uint32_t scheduled)
{
	taskENTER_CRITICAL();
	if (g_perf.counters.scheduled < scheduled)
		g_perf.counters.scheduled = scheduled;
	taskEXIT_CRITICAL();
}

static uint32_t b2z_observation_us(void)
{
	XTime now;
	XTime_GetTime(&now);
	return bluebee_perf_ticks_to_us(now - g_perf.start_time);
}

static struct b2z_burst_observation *b2z_burst(uint32_t slot, uint32_t kind)
{
	return g_perf.config.planned && slot < B2Z_PLAN_MAX_SLOTS ?
		&g_control_bursts[slot][kind] : NULL;
}

static void b2z_burst_prepare(uint32_t slot, uint32_t kind,
			     uint32_t bytes, uint32_t air_us, uint32_t pad_us)
{
	struct b2z_burst_observation *b = b2z_burst(slot, kind);
	if (!b) return;
	b->generated = 1u; b->iq_bytes = bytes; b->air_us = air_us;
	b->pad_us = pad_us; b->prepared_us = b2z_observation_us();
}

static int32_t b2z_burst_start(uint32_t slot, uint32_t kind,
			     const uint32_t *iq, uint32_t bytes)
{
	struct b2z_burst_observation *b = b2z_burst(slot, kind);
	int32_t ret;
	if (b) { b->attempted = 1u; b->submit_before_us = b2z_observation_us(); }
	b2z_trace_mark(b2z_trace_for(slot, kind), N3_CALL, 0, 0);
	ret = bluebee_perf_dma_start_traced(iq, bytes, b2z_trace_for(slot, kind));
	b2z_trace_mark(b2z_trace_for(slot, kind), N3_CALL, 1, ret);
	if (b) { b->started = ret >= 0; b->submit_after_us = b2z_observation_us(); }
	return ret;
}

static int32_t b2z_burst_wait(uint32_t slot, uint32_t kind, uint32_t timeout_us)
{
	struct b2z_burst_observation *b = b2z_burst(slot, kind);
	int32_t ret;
	b2z_trace_mark(b2z_trace_for(slot, kind), N3_POLL, 0, 0);
	ret = bluebee_perf_dma_wait(timeout_us);
	b2z_trace_mark(b2z_trace_for(slot, kind), N3_POLL, 1, ret);
	if (b) {
		b->completed = ret >= 0; b->timeout = ret < 0;
		b->finish_us = b2z_observation_us();
	}
	return ret;
}

static int32_t bluebee_perf_send_slot(const struct bluebee_perf_config *config,
				      uint32_t sequence)
{
	uint8_t payload[BLUEBEE_PERF_MAX_PAYLOAD];
	const uint32_t *ieee_iq_words = NULL;
	uint32_t ieee_iq_bytes = 0u, ieee_tx_us = 0u;
	const uint32_t *iq_words = NULL;
	const uint32_t *primary_iq_words = ble_exadv_primary_iq_ch39;
	uint32_t primary_iq_byte_count =
		BLE_EXADV_PRIMARY_IQ_CH39_WORDS * sizeof(uint32_t);
	uint32_t iq_byte_count = 0u;
	uint32_t tx_time_us = 0u;
	uint32_t aux_offset_us = BLUEBEE_PERF_AUX_OFFSET_US;
	uint8_t standard_secondary =
		config->test == BLUEBEE_PERF_TEST_CONTROL &&
		config->control_rf_mode != B2Z_CONTROL_RF_SAME_CHANNEL;
	uint8_t secondary_lo_selected = 0u;
	XTime primary_start = 0u;
	int32_t result = -1;
	struct bluebee_perf_gen_timing timing;

	if (config->test == BLUEBEE_PERF_TEST_CONTROL) {
		const struct b2z_plan_entry *entry = config->planned ?
			b2z_plan_entry_for_slot(config, sequence) : NULL;
		struct b2z_control_packet packet;
		const struct ble_exadv_secondary_gen_meta *meta;

		if (config->planned && !entry)
			return -1;
		packet = entry ? entry->packet : config->control;

		packet.slot_index = sequence;
		packet.ref_tick_ms = (uint32_t)((uint64_t)sequence *
						 packet.period_ms);
		struct b2z_trace *prep = b2z_trace_for(sequence, 3u);
		b2z_trace_mark(prep, N3_GENERATE, 0, 0);
		int32_t gen_ret = ble_exadv_secondary_gen_build_control_mode(&packet, config->control_rf_mode);
		b2z_trace_mark(prep, N3_GENERATE, 1, gen_ret);
		if (gen_ret < 0) return -1;
		meta = ble_exadv_secondary_gen_get_last_meta();
		iq_words = meta->iq_words;
		iq_byte_count = meta->iq_byte_count;
		tx_time_us = meta->air_us + meta->post_pad_us;
		primary_iq_words = meta->primary_iq_words;
		primary_iq_byte_count = meta->primary_iq_byte_count;
		timing.frame_us = meta->frame_time_us;
		timing.mapping_us = meta->mapping_time_us;
		timing.gfsk_us = meta->gfsk_time_us;
		timing.total_us = meta->total_time_us;
		if (prep) { prep->frame_us = timing.frame_us; prep->mapping_us = timing.mapping_us; prep->gfsk_us = timing.gfsk_us; }
		aux_offset_us = meta->aux_offset_us;
		ieee_iq_words = meta->ieee_iq_words;
		ieee_iq_bytes = meta->ieee_iq_byte_count;
		ieee_tx_us = meta->ieee_air_us + meta->post_pad_us;
		b2z_burst_prepare(sequence, 0u, primary_iq_byte_count, meta->primary_air_us, meta->post_pad_us);
		b2z_burst_prepare(sequence, 1u, iq_byte_count, meta->air_us, meta->post_pad_us);
		if (ieee_iq_words)
			b2z_burst_prepare(sequence, 2u, ieee_iq_bytes, meta->ieee_air_us, meta->post_pad_us);
	} else {
		bluebee_perf_build_payload(payload, config->payload_len,
					    config->run_id, sequence);
		if (bluebee_perf_generate(config->test, payload,
					  config->payload_len, &iq_words,
					  &iq_byte_count, &tx_time_us,
					  &timing) < 0)
			return -1;
	}
	bluebee_perf_record_timing(&timing);
	bluebee_perf_count(&g_perf.counters.generated);
	b2z_plan_slot_flag(sequence, B2Z_SLOT_GENERATED);

	if (config->test == BLUEBEE_PERF_TEST_EXADV ||
	    config->test == BLUEBEE_PERF_TEST_CONTROL) {
		XTime_GetTime(&primary_start);
		if (b2z_trace_for(sequence, 3u)) g_n3_primary_anchor[sequence] = primary_start;
		if (b2z_burst_start(sequence, 0u, primary_iq_words,
					    primary_iq_byte_count) < 0)
			return -1;
		if (config->test == BLUEBEE_PERF_TEST_CONTROL)
			bluebee_perf_count(&g_perf.counters.primary_started);
		b2z_plan_slot_flag(sequence, B2Z_SLOT_PRIMARY_STARTED);
		if (b2z_burst_wait(sequence, 0u, BLUEBEE_PERF_PRIMARY_TIMEOUT_US) < 0) {
			bluebee_perf_count(&g_perf.counters.dma_timeout);
			b2z_plan_slot_flag(sequence, B2Z_SLOT_DMA_TIMEOUT);
			return -1;
		}
		if (config->test == BLUEBEE_PERF_TEST_CONTROL)
			bluebee_perf_count(&g_perf.counters.primary_completed);
		b2z_plan_slot_flag(sequence, B2Z_SLOT_PRIMARY_COMPLETED);
		if (standard_secondary) {
			XTime retune_start, retune_end;
			uint32_t retune_us;

			XTime_GetTime(&retune_start);
			secondary_lo_selected = 1u;
			b2z_trace_mark(b2z_trace_for(sequence, 3u), N3_RETUNE_SECONDARY, 0, 0);
			int32_t tune_ret = ad9361_set_tx_lo_freq(ad9361_phy, B2Z_CONTROL_SECONDARY_CH3_TX_LO_HZ);
			b2z_trace_mark(b2z_trace_for(sequence, 3u), N3_RETUNE_SECONDARY, 1, tune_ret);
			if (tune_ret < 0) {
				bluebee_perf_count(&g_perf.counters.retune_failure);
				goto restore_primary_lo;
			}
			XTime_GetTime(&retune_end);
			retune_us = bluebee_perf_ticks_to_us(
				retune_end - retune_start);
			taskENTER_CRITICAL();
			g_perf.counters.retune_secondary_samples++;
			g_perf.counters.retune_secondary_sum_us += retune_us;
			if (retune_us > g_perf.counters.retune_secondary_max_us)
				g_perf.counters.retune_secondary_max_us = retune_us;
			if (config->planned && sequence < B2Z_PLAN_MAX_SLOTS)
				g_control_slot_retune_us[sequence] = retune_us;
			taskEXIT_CRITICAL();
		}
		if ((standard_secondary ?
		     b2z_wait_aux_target(primary_start +
			bluebee_perf_ticks_from_us(aux_offset_us)) :
		     bluebee_perf_wait_until(primary_start +
			bluebee_perf_ticks_from_us(aux_offset_us), 1u)) < 0)
			goto restore_primary_lo;
	}

	if (bluebee_perf_stop_requested())
		goto restore_primary_lo;
	if (standard_secondary) {
		XTime now;
		XTime window_end = primary_start +
			bluebee_perf_ticks_from_us(aux_offset_us +
						  B2Z_AUXPTR_WINDOW_US);

		XTime_GetTime(&now);
		if (now > window_end) {
			bluebee_perf_count(
				&g_perf.counters.auxptr_dma_window_miss);
			b2z_plan_slot_flag(sequence, B2Z_SLOT_AUXPTR_DMA_MISS);
			goto restore_primary_lo;
		}
	}
	if (b2z_burst_start(sequence, 1u, iq_words, iq_byte_count) < 0)
		goto restore_primary_lo;
	if (config->test == BLUEBEE_PERF_TEST_CONTROL) {
		XTime now;
		XTime planned = g_perf.start_time +
			(XTime)((uint64_t)bluebee_perf_ticks_from_us(
				config->interval_us) * sequence) +
			bluebee_perf_ticks_from_us(aux_offset_us);
		uint32_t late_us;
		uint32_t aux_delta_us;

		XTime_GetTime(&now);
		aux_delta_us = bluebee_perf_ticks_to_us(now - primary_start);
		if (standard_secondary &&
		    now > primary_start + bluebee_perf_ticks_from_us(
			aux_offset_us + B2Z_AUXPTR_WINDOW_US)) {
			bluebee_perf_count(
				&g_perf.counters.auxptr_dma_window_miss);
			b2z_plan_slot_flag(sequence, B2Z_SLOT_AUXPTR_DMA_MISS);
		}
		late_us = now > planned ?
			bluebee_perf_ticks_to_us(now - planned) : 0u;
		taskENTER_CRITICAL();
		if (g_perf.counters.auxptr_dma_delta_samples == 0u ||
		    aux_delta_us < g_perf.counters.auxptr_dma_delta_min_us)
			g_perf.counters.auxptr_dma_delta_min_us = aux_delta_us;
		g_perf.counters.auxptr_dma_delta_samples++;
		g_perf.counters.auxptr_dma_delta_sum_us += aux_delta_us;
		if (aux_delta_us > g_perf.counters.auxptr_dma_delta_max_us)
			g_perf.counters.auxptr_dma_delta_max_us = aux_delta_us;
		g_perf.counters.secondary_dma_late_samples++;
		g_perf.counters.secondary_dma_late_sum_us += late_us;
		if (late_us > g_perf.counters.secondary_dma_late_max_us)
			g_perf.counters.secondary_dma_late_max_us = late_us;
		if (config->planned && sequence < B2Z_PLAN_MAX_SLOTS)
			g_control_slot_late_us[sequence] = late_us;
		if (config->planned && sequence < B2Z_PLAN_MAX_SLOTS)
			g_control_slot_aux_delta_us[sequence] = aux_delta_us;
		taskEXIT_CRITICAL();
	}
	bluebee_perf_count(&g_perf.counters.tx_started);
	b2z_plan_slot_flag(sequence, B2Z_SLOT_TX_STARTED);
	if (b2z_burst_wait(sequence, 1u, tx_time_us + BLUEBEE_PERF_DMA_MARGIN_US) < 0) {
		bluebee_perf_count(&g_perf.counters.dma_timeout);
		b2z_plan_slot_flag(sequence, B2Z_SLOT_DMA_TIMEOUT);
		goto restore_primary_lo;
	}
	bluebee_perf_count(&g_perf.counters.tx_completed);
	b2z_plan_slot_flag(sequence, B2Z_SLOT_TX_COMPLETED);
	if (ieee_iq_words) {
		XTime gap_start;
		/* Minimum software gap after BLE DMA completion, not an RF gap. */
		XTime_GetTime(&gap_start);
		if (bluebee_perf_wait_until(gap_start + bluebee_perf_ticks_from_us(
			B2Z_CONTROL_SEPARATE_GAP_US), 1u) < 0 || bluebee_perf_stop_requested())
			goto restore_primary_lo;
		if (b2z_burst_start(sequence, 2u, ieee_iq_words, ieee_iq_bytes) < 0)
			goto restore_primary_lo;
		if (b2z_burst_wait(sequence, 2u, ieee_tx_us + BLUEBEE_PERF_DMA_MARGIN_US) < 0) {
			bluebee_perf_count(&g_perf.counters.dma_timeout);
			b2z_plan_slot_flag(sequence, B2Z_SLOT_DMA_TIMEOUT);
			goto restore_primary_lo;
		}
	}
	result = 0;

restore_primary_lo:
	if (secondary_lo_selected) {
		b2z_trace_mark(b2z_trace_for(sequence, 3u), N3_RETUNE_PRIMARY, 0, 0);
		int32_t tune_ret = ad9361_set_tx_lo_freq(ad9361_phy, BLUEBEE_GEN_TX_LO_HZ);
		b2z_trace_mark(b2z_trace_for(sequence, 3u), N3_RETUNE_PRIMARY, 1, tune_ret);
		if (tune_ret < 0) {
			bluebee_perf_count(&g_perf.counters.retune_failure);
			result = -1;
		}
	}
	return result;
}

static void bluebee_perf_run(void)
{
	struct bluebee_perf_config config;
	struct bluebee_perf_prepared prepared[BLUEBEE_PERF_BATCH_MAX_SIZE];
	XTime interval_ticks;
	XTime experiment_end = 0;
	uint32_t sequence = 0u;
	uint32_t batch_first_sequence = 0u;
	uint32_t batch_count = 0u;
	uint32_t double_current_slot = 0u;
	uint8_t setup_ok = 0u;
	uint8_t stopped = 0u;
	uint8_t run_error = 0u;

	memset(prepared, 0, sizeof(prepared));
	taskENTER_CRITICAL();
	config = g_perf.config;
	g_perf.state = BLUEBEE_PERF_STATE_RUNNING;
	g_perf.stop_requested = 0u;
	g_perf.start_time = 0;
	g_perf.end_time = 0;
	taskEXIT_CRITICAL();

	if (bluebee_perf_prepare_tx() < 0) {
		run_error = 1u;
		goto finish;
	}
	setup_ok = 1u;
	if (config.planned && B2Z_N3_TRACE_ENABLED) b2z_timer_probe();

	/*
	 * Batch isolates RF/DMA by moving the first arena fill before the clock
	 * starts. Double similarly prepares only Sequence 0, then prepares N+1
	 * while DMA owns N.
	 */
	if (config.mode == 1u) {
		if (bluebee_perf_prepare_batch(&config, 0u, prepared,
					       &batch_count) < 0) {
			if (bluebee_perf_stop_requested())
				stopped = 1u;
			else
				run_error = 1u;
			goto finish;
		}
	} else if (config.mode == 2u &&
		   (config.duration_s == 0u || config.expected_packets > 0u)) {
		if (bluebee_perf_prepare_waveform(&config, 0u, 0u,
						   &prepared[0]) < 0) {
			run_error = 1u;
			goto finish;
		}
	}

	taskENTER_CRITICAL();
	XTime_GetTime(&g_perf.start_time);
	taskEXIT_CRITICAL();
	interval_ticks = bluebee_perf_ticks_from_us(config.interval_us);
	if (config.duration_s != 0u)
		experiment_end = g_perf.start_time +
			(XTime)((uint64_t)COUNTS_PER_SECOND * config.duration_s);

	for (;;) {
		XTime now;
		XTime next_slot;
		XTime deadline;
		uint32_t arrived;

		XTime_GetTime(&now);
		if (config.duration_s != 0u && now >= experiment_end) {
			bluebee_perf_set_scheduled(config.expected_packets);
			break;
		}
		if (config.duration_s != 0u &&
		    sequence >= config.expected_packets) {
			if (bluebee_perf_wait_until(experiment_end, 1u) < 0)
				stopped = 1u;
			else
				bluebee_perf_set_scheduled(config.expected_packets);
			break;
		}

		next_slot = g_perf.start_time +
			(XTime)((uint64_t)interval_ticks * sequence);
		if (bluebee_perf_wait_until(next_slot, 1u) < 0) {
			stopped = 1u;
			break;
		}
		if (bluebee_perf_stop_requested()) {
			stopped = 1u;
			break;
		}

		XTime_GetTime(&now);
		if (config.duration_s != 0u && now >= experiment_end) {
			bluebee_perf_set_scheduled(config.expected_packets);
			break;
		}
		arrived = bluebee_perf_slots_arrived(&config,
						  g_perf.start_time, now);
		if (arrived == 0u)
			continue;
		bluebee_perf_set_scheduled(arrived);
		if (arrived - 1u > sequence)
			sequence = arrived - 1u;

		deadline = g_perf.start_time +
			(XTime)((uint64_t)interval_ticks * (sequence + 1ULL));
		if (config.mode == 0u) {
			(void)bluebee_perf_send_slot(&config, sequence);
			if (config.test == BLUEBEE_PERF_TEST_CONTROL &&
			    g_perf.counters.retune_failure != 0u) {
				run_error = 1u;
				break;
			}
		} else if (config.mode == 1u) {
			if (sequence < batch_first_sequence ||
			    sequence >= batch_first_sequence + batch_count) {
				batch_first_sequence = sequence;
				if (bluebee_perf_prepare_batch(
					    &config, batch_first_sequence, prepared,
					    &batch_count) < 0) {
					if (bluebee_perf_stop_requested())
						stopped = 1u;
					else
						run_error = 1u;
					break;
				}
			}
			if (batch_count == 0u)
				break;
			(void)bluebee_perf_send_prepared(
				&config, &prepared[sequence - batch_first_sequence]);
		} else {
			uint32_t sent_slot = double_current_slot;
			uint32_t next_arena_slot = sent_slot ^ 1u;
			uint32_t next_sequence = sequence + 1u;
			uint8_t prepare_next =
				(config.duration_s == 0u ||
				 next_sequence < config.expected_packets);

			if (!prepared[sent_slot].valid ||
			    prepared[sent_slot].sequence != sequence) {
				prepared[sent_slot].valid = 0u;
				if (bluebee_perf_prepare_waveform(
					    &config, sequence, sent_slot,
					    &prepared[sent_slot]) < 0) {
					prepared[sent_slot].valid = 0u;
				}
			}
			if (prepared[sent_slot].valid) {
				(void)bluebee_perf_send_double(
					&config, &prepared[sent_slot], next_sequence,
					prepare_next, next_arena_slot,
					&prepared[next_arena_slot]);
			}
			prepared[sent_slot].valid = 0u;
			if (prepared[next_arena_slot].valid &&
			    prepared[next_arena_slot].sequence == next_sequence)
				double_current_slot = next_arena_slot;
		}

		if (bluebee_perf_stop_requested()) {
			stopped = 1u;
			break;
		}
		XTime_GetTime(&now);
		if (now > deadline) {
			bluebee_perf_count(&g_perf.counters.deadline_miss);
			b2z_plan_slot_flag(sequence, B2Z_SLOT_DEADLINE_MISS);
		}
		sequence++;
	}

finish:
	if (setup_ok)
		bluebee_perf_release_tx();
	taskENTER_CRITICAL();
	XTime_GetTime(&g_perf.end_time);
	if (run_error || !setup_ok)
		g_perf.state = BLUEBEE_PERF_STATE_ERROR;
	else if (stopped || g_perf.stop_requested)
		g_perf.state = BLUEBEE_PERF_STATE_STOPPED;
	else
		g_perf.state = BLUEBEE_PERF_STATE_COMPLETE;
	g_perf.stop_requested = 0u;
	g_perf_reporting = 1u;
	taskEXIT_CRITICAL();
	bluebee_perf_print_stats(1u);
	taskENTER_CRITICAL();
	g_perf_reporting = 0u;
	taskEXIT_CRITICAL();
}

void bluebee_perf_task(void *pvParameters)
{
	(void)pvParameters;

	taskENTER_CRITICAL();
	g_perf_task = xTaskGetCurrentTaskHandle();
	if (g_perf.state == 0)
		g_perf.state = BLUEBEE_PERF_STATE_IDLE;
	taskEXIT_CRITICAL();

	for (;;) {
		(void)ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
		bluebee_perf_run();
	}
}

#endif
