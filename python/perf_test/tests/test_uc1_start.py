"""Run the real serial parser and pre-arm validation without an RTOS/RF."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[3]

class UC1StartTests(unittest.TestCase):
    def test_slot_guard_blocks_late_dma_without_changing_legacy(self):
        source=(ROOT/'app_FreeRTOS/app/bluebee_perf.c').read_text()
        a=source.index('static int32_t b2z_burst_start_impl(')
        impl=source[a:source.index('static int32_t b2z_burst_start(',a)]
        code=r"""
#include <stdint.h>
#include <stdbool.h>
#include <assert.h>
#define BLUEBEE_PERF_DMA_MARGIN_US 5000u
#define B2Z_SLOT_DEADLINE_MISS 32u
#define N3_CALL 0
struct b2z_burst_observation { uint32_t air_us,pad_us,attempted,submit_before_us,started,submit_after_us; };
static struct { struct { uint32_t uc1,interval_us; } config;
 struct { uint32_t deadline_miss; } counters; } g_perf;
static struct b2z_burst_observation obs;
static uint32_t now_us,submits,flags;
static struct b2z_burst_observation *b2z_burst(uint32_t s,uint32_t k){return &obs;}
static uint32_t b2z_observation_us(void){return now_us;}
static void b2z_plan_slot_flag(uint32_t s,uint8_t f){flags|=f;}
static void bluebee_perf_count(uint32_t *n){++*n;}
static void *b2z_trace_for(uint32_t s,uint32_t k){return 0;}
static void b2z_trace_mark(void *t,int a,int b,int c){}
static int32_t bluebee_perf_dma_start_traced(const uint32_t *iq,uint32_t n,void *t,bool cache){++submits;return 0;}
"""+impl+r"""
int main(void){
 g_perf.config.uc1=1;g_perf.config.interval_us=500000;
 obs.air_us=400;obs.pad_us=20;now_us=1490000;
 assert(b2z_burst_start_impl(2,0,0,4,false)==0 && submits==1);
 now_us=1495000;
 assert(b2z_burst_start_impl(2,1,0,4,false)<0 && submits==1);
 assert(flags==B2Z_SLOT_DEADLINE_MISS && g_perf.counters.deadline_miss==1);
 g_perf.config.uc1=0;
 assert(b2z_burst_start_impl(2,1,0,4,false)==0 && submits==2);
 return 0;
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'check.c').write_text(code)
            subprocess.run(['cc','-std=c99',str(p/'check.c'),'-o',str(p/'check')],check=True,capture_output=True)
            subprocess.run([str(p/'check')],check=True)

    def test_arguments_and_prearm_schedule(self):
        app=ROOT/'app_FreeRTOS/app'
        source=(app/'bluebee_perf.c').read_text()
        structs=source[source.index('struct b2z_plan_entry {'):source.index('struct bluebee_perf_counters {')]
        a=source.index('static uint8_t bluebee_perf_is_line_end(')
        parser=source[a:source.index('\n}',a)+2]+'\n'+source[source.index('static int32_t bluebee_perf_parse_args('):source.index('static void bluebee_perf_print_start_usage(')]
        start=source.index('static int32_t b2z_plan_start_internal(')
        body=source[start:source.index('\n\ttaskENTER_CRITICAL();',start)]
        body=body.replace('static int32_t b2z_plan_start_internal(const char *args, uint8_t capacity)',
                          'static int32_t validate(const char *args, uint8_t capacity, struct bluebee_perf_config *out)')
        body+='\n *out=config;return 0;\n}\n'
        prefix='''#include <stdint.h>
#include <string.h>
#include <assert.h>
#include "ble_exadv_secondary_gen.h"
#define B2Z_PLAN_MAX_ENTRIES 16
#define B2Z_PLAN_MAX_SLOTS 1024
#define BLUEBEE_PERF_MAX_ARGS 13
#define B2Z_STANDARD_MIN_PERIOD_MS 500
#define console_print(...) ((void)0)
enum bluebee_perf_test { BLUEBEE_PERF_TEST_CONTROL };
'''
        main='''
int main(void) {
 struct bluebee_perf_config c;
 assert(validate("2701 500 100 26 0 1 1 6000 0",4,&c)==0);
 assert(c.uc1 && c.uc1_k==3 && c.uc1_tasks==100 && c.expected_packets==610 && c.capacity==2 && c.control_rf_mode==1);
 assert(validate("2701 500 100 26 0 2 1 6000 0",4,&c)==0 && c.control_rf_mode==2 && c.uc1_k==3);
 assert(validate("2701 500 100 26 0 3 1 6000 0",4,&c)==0 && c.capacity==3 && c.uc1_k==2);
 assert(validate("2701 500 100 0 0 3 1 6000 0",4,&c)==0 && c.uc1_k==4);
 assert(validate("2701 500 6 26 0 1 0 3 1",4,&c)==0 && c.uc1_profile && c.expected_packets==300);
 const char *bad[]={
 "0 500 100 0 0 1 0 1 0", "65536 500 100 0 0 1 0 1 0",
 "2701 499 100 0 0 1 0 1 0", "2701 500 170 0 0 1 0 1 0",
 "2701 1000 100 0 0 1 0 1 0", "2701 500 0 0 0 1 0 1 0",
 "2701 500 100 3 6 1 0 1 0", "2701 500 100 256 0 1 0 1 0",
 "2701 500 100 0 0 257 0 1 0", "2701 500 100 0 0 1 2 1 0",
 "2701 500 100 0 0 1 0 5 0", "2701 500 100 0 0 1 0 0 0",
 "2701 500 100 0 0 1 1 1647 0", "2701 500 100 0 0 1 1 100000 0",
 "2701 500 6 0 0 3 0 3 1", "2701 500 6 0 0 1 1 6000 1",
 "2701 500 6 0 0 1 0 3 2", "2701 500 6 0 0 1 0 3",
 "2701 500 6 0 0 1 0 3 1 1", "2701 5e2 6 0 0 1 0 3 1",
 "2701 500 6 0 0 1 -1 3 1", "2701 500 6 0 0 1 0 4294967296 1"};
 for(unsigned i=0;i<sizeof(bad)/sizeof(bad[0]);i++)assert(validate(bad[i],4,&c)<0);
 /* Original C1/C2 and capacity argument domains still accepted. */
 assert(validate("2411 500 100 26 0 2",2,&c)==0 && !c.uc1 && c.capacity==3);
 assert(validate("2401 500 100 2 6 1",1,&c)==0 && !c.uc1 && c.capacity==1);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'check.c').write_text(prefix+structs+parser+body+main)
            result=subprocess.run(['cc','-std=c99','-DCONFIG_H_',f'-I{app}',str(p/'check.c'),str(app/'ble_exadv_secondary_gen.c'),'-lm','-o',str(p/'check')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            subprocess.run([str(p/'check')],check=True)
