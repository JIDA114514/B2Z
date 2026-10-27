"""Independent HackRF transport, matching the frozen exadv capture behavior.

No BLE parser, decoded packets, ZMQ endpoint or shared IQ state is imported.
"""
from collections import Counter, deque
import queue
import shutil
import signal
import subprocess
import threading

class Capture:
    """Drain stdout independently; abort explicitly on application queue overflow."""
    def __init__(self, args, save_file=None, stderr_file=None):
        self.args = args
        self.save_file = save_file
        self.stderr_file = stderr_file
        self.queue = queue.Queue(maxsize=args.queue_blocks)
        self.done = threading.Event()
        self.stop = threading.Event()
        self.error = None
        self.proc = None
        self.command = None
        self.stats = Counter()
        self.stderr_tail = deque(maxlen=40)
        self.thread = None
        self.stderr_thread = None

    def start(self):
        if self.args.iq_file:
            self.stream = self.args.iq_file.open("rb")
        else:
            executable = shutil.which("hackrf_transfer")
            if not executable:
                raise RuntimeError("hackrf_transfer not found; install HackRF tools or use --iq-file")
            a = self.args
            self.command = [executable, "-r", "-", "-f", str(round(a.center_hz)),
                            "-s", str(a.sample_rate), "-l", str(a.lna), "-g", str(a.vga),
                            "-a", str(int(a.amp)), "-p", "0"]
            if a.serial:
                self.command += ["-d", a.serial]
            if a.duration:
                self.command += ["-n", str(max(1, int(a.duration * a.sample_rate)))]
            self.proc = subprocess.Popen(self.command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.stream = self.proc.stdout
            self.stderr_thread = threading.Thread(target=self._stderr, daemon=True)
            self.stderr_thread.start()
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _stderr(self):
        for line in iter(self.proc.stderr.readline, b""):
            value = line.decode(errors="replace")
            self.stderr_tail.append(value.rstrip())
            if self.stderr_file:
                self.stderr_file.write(value)
                self.stderr_file.flush()

    def _read(self):
        width = 2 if self.args.format == "ci8" else 8
        remaining = int(self.args.duration * self.args.sample_rate) * width if self.args.duration else None
        try:
            while not self.stop.is_set() and (remaining is None or remaining > 0):
                size = self.args.block_samples * width
                if remaining is not None:
                    size = min(size, remaining)
                chunk = self.stream.read(size)
                if not chunk:
                    break
                if remaining is not None:
                    remaining -= len(chunk)
                self.stats["bytes_read"] += len(chunk)
                if self.save_file:
                    self.save_file.write(chunk)
                if self.proc:
                    try:
                        self.queue.put_nowait(chunk)
                    except queue.Full:
                        self.stats["queue_overflow"] += 1
                        self.error = "live decode queue overflow; capture incomplete, reduce CPU load or record/replay IQ"
                        break
                else:
                    # A file can be backpressured; do not label offline pacing as loss.
                    while not self.stop.is_set():
                        try:
                            self.queue.put(chunk, timeout=.1)
                            break
                        except queue.Full:
                            pass
                self.stats["queue_high_water"] = max(self.stats["queue_high_water"], self.queue.qsize())
        except Exception as exc:
            self.error = f"capture read failed: {exc}"
        finally:
            self.done.set()

    def close(self):
        self.stop.set()
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGINT)
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=3)
        if self.thread:
            self.thread.join(timeout=3)
        if self.stderr_thread:
            self.stderr_thread.join(timeout=3)
        if hasattr(self, "stream"):
            self.stream.close()
        if self.proc:
            self.proc.stderr.close()
