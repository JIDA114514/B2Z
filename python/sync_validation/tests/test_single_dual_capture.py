import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

spec=importlib.util.spec_from_file_location('single_dual_capture',Path(__file__).resolve().parents[1]/'capture_single_dual.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

BASE=['--ble-serial','000000000000000017c467dc2926a0c3',
      '--zigbee-serial','000000000000000017c467dc3348a6c3','--run-id','10270']
AVAILABLE={'returncode':0,'raw_output':'test inventory','detected_serials':[BASE[1],BASE[3]],'missing_serials':[]}


class Process:
    def __init__(self,code=0):
        self.returncode=code;self.signals=[]
    def poll(self):
        return self.returncode
    def send_signal(self,value):
        self.signals.append(value);self.returncode=-2
    def wait(self,timeout=None):
        return self.returncode
    def kill(self):
        self.returncode=-9


class CaptureTests(unittest.TestCase):
    def test_dry_run_has_no_capture_or_output_side_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'dry'
            with mock.patch.object(m.subprocess,'Popen') as popen,mock.patch.object(m,'inspect_devices') as inventory,contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(m.main(BASE+['--output',str(target),'--dry-run']),0)
            popen.assert_not_called();inventory.assert_not_called();self.assertFalse(target.exists())

    def test_distinct_serials_required(self):
        args=['--ble-serial',BASE[1],'--zigbee-serial',BASE[1],'--run-id','1','--dry-run']
        with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
            m.main(args)

    def test_records_all_stages_without_assuming_zero_sequence(self):
        observed=[]
        def popen(command,**kwargs):
            observed.append(command)
            prefix=Path(command[command.index('--output')+1])
            value={'status':'complete','counts':{},'capture_stats':{'queue_high_water':2},
                   'run_id':10270,'receiver':{'unique':5}}
            Path(str(prefix)+'.summary.json').write_text(json.dumps(value))
            return Process()
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'record'
            with mock.patch.object(m,'inspect_devices',return_value=AVAILABLE),mock.patch.object(m.subprocess,'Popen',side_effect=popen),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(m.main(BASE+['--output',str(output),'--no-save-iq']),0)
            report=json.loads((output/'single_dual.summary.json').read_text())
        self.assertEqual([s['stage'] for s in report['stages']],['single_before','dual','single_after'])
        self.assertEqual([len(s['receivers']) for s in report['stages']],[1,2,1])
        self.assertEqual(len(observed),4)
        self.assertTrue(all('--expected-packets' not in cmd for cmd in observed))

    def test_failure_stops_running_peer_and_records_error(self):
        active=Process(None);processes=[Process(),active,Process(1)]
        def popen(command,**kwargs):
            prefix=Path(command[command.index('--output')+1])
            proc=processes.pop(0)
            value={'status':'complete' if proc.returncode!=1 else 'error','counts':{},
                'capture_stats':{},'run_id':10270,'receiver':{'unique':5}}
            if proc.returncode==1:
                value['stderr_tail']=['hackrf_open() failed: HackRF not found (-5)']
            Path(str(prefix)+'.summary.json').write_text(json.dumps(value))
            return proc
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'failure'
            with mock.patch.object(m,'inspect_devices',return_value=AVAILABLE),mock.patch.object(m.subprocess,'Popen',side_effect=popen),contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError,'HackRF not found'):
                    m.main(BASE+['--output',str(output)])
            report=json.loads((output/'single_dual.summary.json').read_text())
            self.assertIn('receiver failed',report['error'])
            self.assertIn('HackRF not found',report['stages'][1]['receivers']['ble']['stderr_tail'][0])
            self.assertEqual(report['stages'][1]['receivers']['zigbee']['process_returncode'],-2)
        self.assertTrue(active.signals)

    def test_missing_second_device_stops_before_first_capture(self):
        inventory={'returncode':0,'raw_output':'one device','detected_serials':[BASE[3]],'missing_serials':[BASE[1]]}
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'missing'
            with mock.patch.object(m,'inspect_devices',return_value=inventory),mock.patch.object(m.subprocess,'Popen') as popen,contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError,'required HackRF not detected'):
                    m.main(BASE+['--output',str(target)])
            popen.assert_not_called()
            report=json.loads((target/'single_dual.summary.json').read_text())
            self.assertEqual(report['status'],'error')
            self.assertEqual(report['stages'][0]['device_check']['missing_serials'],[BASE[1]])

    def test_inventory_parser_records_missing_serial(self):
        response=SimpleNamespace(returncode=0,stdout='Serial number: '+BASE[3]+'\n',stderr='')
        with mock.patch.object(m.shutil,'which',return_value='/usr/bin/hackrf_info'),mock.patch.object(m.subprocess,'run',return_value=response):
            result=m.inspect_devices(SimpleNamespace(ble_serial=BASE[1],zigbee_serial=BASE[3]))
        self.assertEqual(result['missing_serials'],[BASE[1]])
        self.assertEqual(result['detected_serials'],[BASE[3]])

    def test_error_message_preserves_transfer_failure_before_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'dual_ble.summary.json').write_text(json.dumps({'stderr_tail':[
                "Couldn't transfer any bytes for one second.",
                'Exiting... hackrf_is_streaming() result: streaming stopped (-1003)',
                'hackrf_stop_rx() failed: No such device (-1000)',
                'hackrf_close() failed: No such device (-1000)',
                'hackrf_exit() done','exit']}))
            message=m.failure_message(root,'dual',[('ble',1)])
        self.assertIn("Couldn't transfer any bytes",message)
        self.assertIn('No such device',message)
        self.assertIn('dual_ble.console.log',message)


if __name__=='__main__':
    unittest.main()
