"""Execute the real transfer-start implementation against fake MMIO, no RF."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]


class N3ObserverTests(unittest.TestCase):
    def test_submit_bracket_and_legacy_failure_paths(self):
        driver = (ROOT / 'app_FreeRTOS/drivers/axi_dmac.c').read_text()
        start = driver.index('static int32_t axi_dmac_transfer_start_impl(')
        end = driver.index('/*******************************************************************************', start)
        implementation = driver[start:end]
        # Supply just the driver platform dependencies; compile its actual implementation.
        regs = sorted(set(__import__('re').findall(r'AXI_DMAC_[A-Z_]+', implementation)))
        prefix = '''
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <stdio.h>
#include <assert.h>
#define FREERTOS_INTEGRATION 1
#define IRQ_ENABLED 1
#define CYCLIC 1
#define DMA_CYCLIC 1
#define DMA_DEV_TO_MEM 0
#define DMA_MEM_TO_DEV 1
#define DMA_MEM_TO_MEM 2
#define xSemaphoreTake(a,b) ((void)0)
typedef void *SemaphoreHandle_t;
struct axi_dma_transfer { uint32_t size,cyclic,dest_addr,src_addr; bool transfer_done; };
struct axi_dmac { struct axi_dma_transfer transfer; void *completion_sem;
 uint32_t remaining_size,next_dest_addr,next_src_addr,init_addr,max_length;
 int direction,hw_cyclic,irq_option; };
struct axi_dmac_submit_observer { void (*mark)(void *,uint8_t,int32_t); void *context; };
static int queue_full, write_error, submit_writes, marks, phase;
'''
        prefix += '\n'.join(f'#define {r} {i+10}' for i, r in enumerate(regs)) + '\n'
        prefix += '''
static int32_t axi_dmac_read(struct axi_dmac *d,uint32_t reg,uint32_t *v) {
 *v = reg == AXI_DMAC_REG_TRANSFER_SUBMIT && queue_full ? AXI_DMAC_QUEUE_FULL : 0; return 0;
}
static int32_t axi_dmac_write(struct axi_dmac *d,uint32_t reg,uint32_t v) {
 if (reg == AXI_DMAC_REG_TRANSFER_SUBMIT) { assert(phase==0 || phase==1); submit_writes++; phase=2; return write_error; } return 0;
}
static void observer(void *ctx,uint8_t after,int32_t status) {
 assert(ctx == &marks);
 if (!after) { assert(phase==0); phase=1; } else { assert(phase==2); assert(status==write_error); phase=3; }
 marks++;
}
'''
        main = '''
int main(void) {
 struct axi_dmac d={0}; d.direction=DMA_MEM_TO_DEV; d.max_length=4095;
 struct axi_dma_transfer t={.size=1024};
 struct axi_dmac_submit_observer o={observer,&marks};
 assert(axi_dmac_transfer_start_observed(&d,&t,&o)==0);
 assert(marks==2 && submit_writes==1 && phase==3 && d.remaining_size==0);
 marks=submit_writes=phase=0; queue_full=1;
 assert(axi_dmac_transfer_start_observed(&d,&t,&o)==-1); assert(marks==0 && submit_writes==0);
 queue_full=0; t.size=0;
 assert(axi_dmac_transfer_start_observed(&d,&t,&o)==0); assert(marks==0);
 t.size=1024; t.cyclic=CYCLIC;
 assert(axi_dmac_transfer_start_observed(&d,&t,&o)==-1); assert(marks==0);
 t.cyclic=0; write_error=-7;
 assert(axi_dmac_transfer_start_observed(&d,&t,&o)==0); assert(marks==2); /* legacy return semantics retained */
 marks=submit_writes=phase=0; write_error=0;
 assert(axi_dmac_transfer_start(&d,&t)==0); assert(marks==0 && submit_writes==1);
 phase=0; t.size=8192;
 assert(axi_dmac_transfer_start_observed(&d,&t,&o)==0); assert(d.remaining_size>0);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'test.c'; exe = Path(tmp) / 'test'
            src.write_text(prefix + implementation + main)
            subprocess.run(['cc', '-std=c99', str(src), '-o', str(exe)], check=True, capture_output=True)
            subprocess.run([str(exe)], check=True, capture_output=True)

    def test_raw_tick_formatter_handles_rollover_and_sign_bit(self):
        source = (ROOT / 'app_FreeRTOS/app/bluebee_perf.c').read_text()
        helper = source[source.index('static const char *b2z_tick_hex('):source.index('static int32_t b2z_signed_us(')]
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'test.c'; exe = Path(tmp) / 'test'
            src.write_text('#include <stdint.h>\n#include <string.h>\n#include <assert.h>\ntypedef uint64_t XTime;\n' + helper + '''
int main(void) { char a[17];
 assert(strcmp(b2z_tick_hex(0xffffffff80000000ULL,a),"ffffffff80000000")==0);
 assert(strcmp(b2z_tick_hex(0x100000000ULL,a),"0000000100000000")==0);
 assert(strcmp(b2z_tick_hex(0,a),"0000000000000000")==0); return 0; }
''')
            subprocess.run(['cc','-std=c99',str(src),'-o',str(exe)],check=True,capture_output=True)
            subprocess.run([str(exe)],check=True,capture_output=True)
