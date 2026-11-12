"""Exercise the board's virtual task lookup without RF or the RTOS."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]

class CapacityScheduleTests(unittest.TestCase):
    def test_virtual_tasks_and_manual_plan_are_independent(self):
        app=ROOT/'app_FreeRTOS/app'
        source=(app/'bluebee_perf.c').read_text()
        structs=source[source.index('struct b2z_plan_entry {'):source.index('struct bluebee_perf_counters {')]
        helpers=source[source.index('static uint32_t b2z_task_count('):source.index('static void b2z_plan_slot_flag(')]
        code='''#include <stdint.h>
#include <string.h>
#include <assert.h>
#include "ble_exadv_secondary_gen.h"
#define B2Z_PLAN_MAX_ENTRIES 16
#define B2Z_PLAN_MAX_SLOTS 1024
enum bluebee_perf_test { TEST };
'''+structs+helpers+'''
int main(void) {
 struct bluebee_perf_config c={0}; struct b2z_plan_entry tmp;
 c.capacity=1;c.expected_packets=1024;c.run_id=2301;c.control.period_ms=500;
 assert(b2z_task_count(&c)==1024);
 for (uint32_t s=0;s<1024;s++) {
  const struct b2z_plan_entry *e=b2z_plan_entry_for_slot(&c,s,&tmp);
  assert(e==&tmp && e->first_slot==s && e->repeats==1);
  assert(e->packet.command_id==s+1 && e->packet.run_id==2301);
  assert(e->packet.valid_until_ms==s*500+2000);
  assert(e->packet.execute_at_ms==s*500+3000);
 }
 assert(b2z_plan_entry_for_slot(&c,1024,&tmp)==0);
 c.capacity=0;c.plan_count=1;c.plan[0].first_slot=0;c.plan[0].repeats=3;c.plan[0].packet.command_id=43;
 assert(b2z_task_count(&c)==1);
 for(uint32_t s=0;s<3;s++) assert(b2z_plan_entry_for_slot(&c,s,&tmp)==&c.plan[0]);
 assert(b2z_plan_entry_for_slot(&c,3,&tmp)==0);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'test.c').write_text(code)
            subprocess.run(['cc','-std=c99',f'-I{app}',str(p/'test.c'),'-o',str(p/'test')],check=True,capture_output=True)
            subprocess.run([str(p/'test')],check=True,capture_output=True)
