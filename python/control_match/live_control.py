"""Attach the same one-side control engine to either streaming PHY receiver."""
from __future__ import annotations

from collections import Counter
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import time

try:
    from .control_engine import EngineConfig, SideControlEngine
    from .packet_adapter import control_payload
except ImportError:
    from control_engine import EngineConfig, SideControlEngine
    from packet_adapter import control_payload


TASK_COLUMNS = ("run_id", "command_id", "target_id", "opcode", "arg",
                "decoded_packets", "unique_slots", "duplicate_attempts",
                "first_decoded_sample", "last_decoded_sample", "accepted_sample",
                "target_sample", "processed_sample", "processing_lateness_ms",
                "status", "last_rejection_reason", "cancellation_reason")


class ControlSession:
    """Write one receiver's events as they happen, then summarize tasks."""

    @staticmethod
    def artifact_paths(prefix: Path) -> dict[str, Path]:
        return {"control_events": Path(str(prefix) + ".control.events.jsonl"),
                "control_tasks": Path(str(prefix) + ".control.tasks.csv"),
                "control_summary": Path(str(prefix) + ".control.summary.json"),
                "control_report": Path(str(prefix) + ".control.report.md")}

    def __init__(self, prefix: Path, config: EngineConfig, *, offline: bool):
        self.config = config
        self.engine = SideControlEngine(config)
        self.offline = offline
        self.paths = self.artifact_paths(prefix)
        if any(path.exists() for path in self.paths.values()):
            raise FileExistsError("control output already exists")
        self.paths["control_events"].parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.paths["control_events"].open("x", encoding="utf-8")
        self.counts = Counter()
        self.reasons = Counter()
        self.tasks: dict[int, dict] = {}

    def _write(self, events: list[dict], packet_no: int | None = None) -> None:
        for event in events:
            event = dict(event)
            event["observation_mode"] = "offline_sample_replay" if self.offline else "live_software"
            if packet_no is not None:
                event["receiver_packet_no"] = packet_no
            if not self.offline:
                event["host_monotonic_ns"] = time.monotonic_ns()
            self.stream.write(json.dumps(event, ensure_ascii=False) + "\n")
            self.counts[event["event"]] += 1
            if "reason" in event:
                self.reasons[event["reason"]] += 1
            self._update_task(event)
        if events:
            self.stream.flush()

    def _update_task(self, event: dict) -> None:
        if event["event"] not in ("decoded", "accepted", "scheduled", "rescheduled",
                                  "duplicate", "rejected", "cancelled", "software_processed"):
            return
        command_id = event.get("command_id", 0)
        if not command_id:
            return
        row = self.tasks.setdefault(command_id, {"run_id": self.config.run_id,
                                                  "command_id": command_id,
                                                  "target_id": event.get("target_id"),
                                                  "opcode": event.get("opcode"),
                                                  "arg": event.get("arg"),
                                                  "decoded_packets": 0,
                                                  "duplicate_attempts": 0,
                                                  "status": "decoded", "slots": set()})
        kind, sample = event["event"], event["local_sample"]
        if kind == "decoded":
            row["decoded_packets"] += 1
            row["slots"].add(event["slot_index"])
            row.setdefault("first_decoded_sample", sample)
            row["last_decoded_sample"] = sample
        elif kind == "accepted":
            row["accepted_sample"] = sample
            row["status"] = "accepted"
        elif kind in ("scheduled", "rescheduled"):
            row["target_sample"] = event["target_sample"]
            row["status"] = "scheduled"
        elif kind == "duplicate":
            row["duplicate_attempts"] += 1
        elif kind == "rejected":
            row["last_rejection_reason"] = event["reason"]
            if row["status"] == "decoded":
                row["status"] = "rejected"
        elif kind == "cancelled":
            row["status"] = "cancelled"
            row["cancellation_reason"] = event["reason"]
        elif kind == "software_processed":
            row["status"] = "software_processed"
            row["processed_sample"] = sample
            row["processing_lateness_ms"] = event["lateness_ms"]

    def observe_packet(self, packet: dict) -> None:
        """Consume one locally decoded, outer-CRC-valid packet."""
        available = packet["available_sample"]
        try:
            payload = control_payload(packet, self.config.side)
        except (KeyError, TypeError, ValueError) as exc:
            self._write([{"event": "wire_rejected", "side": self.config.side,
                          "sender_id": self.config.sender_id, "run_id": self.config.run_id,
                          "local_sample": available, "reason": str(exc),
                          "timeline": "local_iq_sample_domain", "software_only": True}],
                        packet.get("packet_no"))
            return
        if payload is not None:
            self._write(self.engine.observe(payload, packet["sample_start"], available),
                        packet.get("packet_no"))

    def advance(self, sample: int) -> None:
        self._write(self.engine.advance(sample))

    def finish(self, receiver_status: str) -> dict:
        self.stream.close()
        rows = []
        for command_id, task in sorted(self.tasks.items()):
            row = {key: task.get(key) for key in TASK_COLUMNS}
            row["unique_slots"] = len(task["slots"])
            rows.append(row)
        with self.paths["control_tasks"].open("x", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=TASK_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        result = {"schema": "b2z_live_control_v1", "side": self.config.side,
                  "run_id": self.config.run_id, "sender_id": self.config.sender_id,
                  "receiver_status": receiver_status,
                  "observation_mode": "offline_sample_replay" if self.offline else "live_software",
                  "target_ids": sorted(self.config.target_ids),
                  "accept_broadcast": self.config.accept_broadcast,
                  "external_reference_bound_ms": self.config.external_reference_bound_ms,
                  "reference_bound_status": ("not supplied; timed commands denied" if
                                             self.config.external_reference_bound_ms is None else
                                             "user supplied; calibration not verified by software"),
                  "event_counts": dict(self.counts), "reasons": dict(self.reasons),
                  "tasks": rows, "engine": self.engine.snapshot(),
                  "generated_utc": datetime.now(timezone.utc).isoformat(),
                  "files": {key: str(path) for key, path in self.paths.items()},
                  "limitations": ["one receiver's software events only",
                                  "IQ sample progress is not a calibrated host or RF timestamp",
                                  "offline events are simulated; live host timestamps include processing latency",
                                  "no cross-device execution error or physical actuator measurement"]}
        with self.paths["control_summary"].open("x", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        lines = ["# 单侧控制处理", "",
                 f"- 接收侧：{self.config.side}；Run ID：{self.config.run_id}",
                 f"- 模式：{'离线样本进度回放' if self.offline else '实时软件处理'}；接收程序状态：{receiver_status}",
                 f"- 参考误差界：{self.config.external_reference_bound_ms if self.config.external_reference_bound_ms is not None else 'N/A'} ms（{result['reference_bound_status']}）",
                 f"- 有效控制记录：{self.counts['decoded']}；接受任务：{self.counts['accepted']}；软件处理：{self.counts['software_processed']}；取消：{self.counts['cancelled']}",
                 "", "| Command ID | 已解码包 | 唯一时隙 | 状态 | 处理样本 | 原因 |",
                 "| ---: | ---: | ---: | --- | ---: | --- |"]
        for row in rows:
            reason = row.get("cancellation_reason") or row.get("last_rejection_reason") or ""
            lines.append(f"| {row['command_id']} | {row['decoded_packets']} | {row['unique_slots']} | "
                         f"{row['status']} | {row.get('processed_sample') or 'N/A'} | {reason} |")
        lines += ["", "仅记录本侧软件事件；离线回放不表示实时处理。独立接收机的 IQ 样本零点不能直接相减，未校准时不报告执行同步误差。", "",
                  f"逐事件：[control.events.jsonl]({self.paths['control_events'].name})；逐任务：[control.tasks.csv]({self.paths['control_tasks'].name})；结构化结果：[control.summary.json]({self.paths['control_summary'].name})。", ""]
        self.paths["control_report"].write_text("\n".join(lines), encoding="utf-8")
        return result
