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

#define BLUEBEE_PERF_MAX_ARGS             6u
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


enum bluebee_perf_test {
	BLUEBEE_PERF_TEST_PURE = 0,
	BLUEBEE_PERF_TEST_EXADV,
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

struct bluebee_perf_config {
	enum bluebee_perf_test test;
	uint32_t payload_len;
	uint32_t interval_us;
	uint32_t duration_s;
	uint16_t run_id;
	uint8_t mode;
	uint32_t batch_size;
	uint32_t expected_packets;
};

struct bluebee_perf_counters {
	uint32_t scheduled;
	uint32_t generated;
	uint32_t tx_started;
	uint32_t tx_completed;
	uint32_t deadline_miss;
	uint32_t dma_timeout;
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

/* Dedicated DDR BSS arena; independent of the 1 MB FreeRTOS heap. */
static uint32_t
g_perf_iq_arena[BLUEBEE_PERF_BATCH_MAX_SIZE][BLUEBEE_PERF_IQ_WORD_CAPACITY]
	__attribute__((aligned(64)));

static const char *bluebee_perf_test_name(enum bluebee_perf_test test)
{
	return test == BLUEBEE_PERF_TEST_EXADV ? "exadv" : "pure";
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

static void bluebee_perf_print_stats(uint8_t final)
{
	struct bluebee_perf_runtime snapshot;

	bluebee_perf_snapshot(&snapshot);
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
	    count < 3u || count > BLUEBEE_PERF_MAX_ARGS) {
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
	if (!g_perf_task || bluebee_perf_is_busy(g_perf.state)) {
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
		console_print("PERF_STOP requested\r\n");
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

static int32_t bluebee_perf_dma_start(const uint32_t *iq_words,
				      uint32_t iq_byte_count)
{
	struct axi_dma_transfer transfer;

	if (!iq_words || iq_byte_count == 0u)
		return -1;

	axi_dmac_transfer_stop(tx_dmac);
	axi_dmac_write(tx_dmac, AXI_DMAC_REG_IRQ_PENDING,
		       AXI_DMAC_IRQ_SOT | AXI_DMAC_IRQ_EOT);
#ifdef XILINX_PLATFORM
	Xil_DCacheFlushRange((uintptr_t)iq_words, iq_byte_count);
#endif
	transfer.size = iq_byte_count;
	transfer.transfer_done = 0;
	transfer.cyclic = NO;
	transfer.src_addr = (uintptr_t)iq_words;
	transfer.dest_addr = 0;
	no_os_axi_io_write(ad9361_phy->tx_dac->base,
			   BLUEBEE_PERF_AXI_DAC_SYNC_CONTROL,
			   BLUEBEE_PERF_AXI_DAC_SYNC);

	return axi_dmac_transfer_start(tx_dmac, &transfer);
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

static int32_t bluebee_perf_send_slot(const struct bluebee_perf_config *config,
				      uint32_t sequence)
{
	uint8_t payload[BLUEBEE_PERF_MAX_PAYLOAD];
	const uint32_t *iq_words = NULL;
	uint32_t iq_byte_count = 0u;
	uint32_t tx_time_us = 0u;
	struct bluebee_perf_gen_timing timing;

	bluebee_perf_build_payload(payload, config->payload_len,
				    config->run_id, sequence);
	if (bluebee_perf_generate(config->test, payload, config->payload_len,
				  &iq_words, &iq_byte_count, &tx_time_us,
				  &timing) < 0)
		return -1;
	bluebee_perf_record_timing(&timing);
	bluebee_perf_count(&g_perf.counters.generated);

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
	if (bluebee_perf_dma_start(iq_words, iq_byte_count) < 0)
		return -1;
	bluebee_perf_count(&g_perf.counters.tx_started);
	if (bluebee_perf_dma_wait(tx_time_us + BLUEBEE_PERF_DMA_MARGIN_US) < 0) {
		bluebee_perf_count(&g_perf.counters.dma_timeout);
		return -1;
	}
	bluebee_perf_count(&g_perf.counters.tx_completed);

	return 0;
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
		if (now > deadline)
			bluebee_perf_count(&g_perf.counters.deadline_miss);
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
	taskEXIT_CRITICAL();
	bluebee_perf_print_stats(1u);
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
