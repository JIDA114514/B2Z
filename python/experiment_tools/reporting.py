"""Shared, stdlib-only reports for independent BLE and ZigBee receivers."""
from __future__ import annotations

from contextlib import contextmanager
import csv
from datetime import datetime, timezone
import fcntl
import io
import json
import os
from pathlib import Path
import tempfile

PROJECT = Path(__file__).resolve().parents[2]
EXPERIMENTS = PROJECT / "python/experiments"


def new_directory(label):
    return EXPERIMENTS / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ_") + label)


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".writing-", delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(text)
            handle.flush()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def write_json(path, value):
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


@contextmanager
def archive_lock(root):
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".index.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def resolve_recorded_path(path):
    """Resolve migrated project paths without modifying immutable source reports."""
    path = Path(path)
    if path.exists():
        return path
    mapping_path = EXPERIMENTS / "migration.manifest.json"
    if not mapping_path.exists():
        return path
    name = path.as_posix()
    marker = "python/"
    if name.startswith(str(PROJECT) + "/"):
        name = path.relative_to(PROJECT).as_posix()
    elif path.is_absolute() and "/" + marker in name:
        name = marker + name.split("/" + marker, 1)[1]
    mapping = json.loads(mapping_path.read_text())["paths"]
    entry = mapping.get(name)
    return PROJECT / entry["destination"] if entry else path


def output_prefix(args, role):
    """Keep explicit --output semantics; default to a unique session directory."""
    if args.output:
        return args.output
    directory = args.experiment_dir or new_directory(role)
    if args.iq_file:
        analysis = args.analysis_id or datetime.now(timezone.utc).strftime("replay_%Y%m%dT%H%M%S_%fZ")
        return directory / "analyses" / analysis / role / "rx"
    return directory / "captures" / role / "rx"


def add_output_arguments(parser):
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--output", type=Path, help="legacy output prefix; never overwrite existing artifacts")
    group.add_argument("--experiment-dir", type=Path, help="shared experiment directory; each receiver has its own subdirectory")
    parser.add_argument("--analysis-id", help="offline analysis subdirectory name; only with --experiment-dir and --iq-file")


def validate_output_arguments(parser, args):
    if args.analysis_id and (not args.experiment_dir or not args.iq_file):
        parser.error("--analysis-id requires --experiment-dir and --iq-file")
    if args.analysis_id and (Path(args.analysis_id).name != args.analysis_id or args.analysis_id in (".", "..")):
        parser.error("--analysis-id must be a single directory name")
    if args.iq_file:
        args.iq_file = resolve_recorded_path(args.iq_file)


def receiver_role(summary):
    schema = summary.get("schema", "")
    if schema.startswith("exadv_rx_"):
        return "ble"
    if schema.startswith("zigbee_rx_"):
        return "zigbee"
    return None


def show(value, digits=3):
    if value is None:
        return "N/A"
    return f"{value:.{digits}f}" if isinstance(value, float) else str(value)


def ratio_text(ratio):
    ratio = ratio or {}
    numerator, denominator = ratio.get("numerator"), ratio.get("denominator")
    if denominator is None or denominator == 0 or numerator is None or ratio.get("value") is None:
        return f"N/A（分子 {show(numerator)}；分母 {show(denominator)}；" + ratio.get("reason", "分母缺失或为零") + "）"
    return f"{numerator}/{denominator} = {100 * ratio['value']:.2f}%"


def observation(summary):
    return summary.get("observation", {}).get("sample_duration_s", summary.get("processed_sample_duration_s"))


def receiver_lines(summary):
    role = receiver_role(summary)
    config = summary.get("config", {})
    counts = summary.get("counts", {})
    capture = summary.get("capture_stats", {})
    state = {"complete": "正常结束", "interrupted": "用户中断", "error": "异常结束"}.get(summary.get("status"), "未知")
    lines = [f"接收链：{'BLE exadv' if role == 'ble' else 'IEEE 802.15.4 / BlueBee'}",
             f"模式：{'离线回放' if config.get('iq_file') else '实时采集'}",
             f"运行状态：{state}（仅表示程序状态）",
             f"有效包：{show(counts.get('packets' if role == 'ble' else 'fcs_valid_packets', 0))}（{'BLE CRC及扩展头有效' if role == 'ble' else 'PHY FCS有效'}）",
             f"IQ观察时长：{show(observation(summary), 6)} s（全部已处理采样，含实验前后余量）"]
    if role == "ble":
        lines += [f"严格 AuxPtr 匹配：{show(summary.get('matched_events'))}",
                  f"同频诊断配对：{show(summary.get('diagnostic_pairs'))}（不代表规范跟随）",
                  "无线 PRR：N/A（未合并发送计数及一致观察窗口）"]
    else:
        rx = summary.get("receiver", {})
        lines += [f"Run ID：{show(summary.get('run_id'))}",
                  f"有效唯一测试包：{show(rx.get('unique'))}；重复：{show(rx.get('duplicate'))}；乱序：{show(rx.get('out_of_order'))}",
                  f"最长连续缺失：{show(rx.get('longest_loss_burst'))}（{rx.get('loss_scope', '范围未记录')}）"]
        labels = {"wireless_prr": "无线 PRR", "end_to_end_receive": "端到端接收率", "scheduling_completion": "调度完成率"}
        lines += [f"{label}：{ratio_text(summary.get('ratios', {}).get(key))}" for key, label in labels.items()]
        if summary.get("board"):
            lines.append("无线 PRR 使用 DMA 完成计数代理；不等于已校准的完整空口发射计数。")
        for key, label in (("gross", "总吞吐"), ("application", "应用 goodput")):
            rate = summary.get("throughput", {}).get(key, {})
            lines.append(f"{label}：{show(rate.get('byte_s'))} B/s（{show(rate.get('bit_s'))} bit/s）")
    lines += [f"采集队列：溢出 {capture.get('queue_overflow', 0)}；高水位 {show(capture.get('queue_high_water'))}",
              "时间基准：相对 IQ 标称采样时间；独立采集未经校准不能直接相减。"]
    if summary.get("error"):
        lines.append("异常：" + str(summary["error"]))
    if summary.get("diagnostic_note"):
        lines.append("诊断配置：" + summary["diagnostic_note"])
    return lines


def receiver_markdown(summary, summary_path):
    config = summary.get("config", {})
    lines = ["# 接收报告", "", *[f"- {line}" for line in receiver_lines(summary)], "",
             "## 关键配置", "", "| 参数 | 值 |", "|---|---|"]
    for key in ("serial", "channels", "channel", "whitening_channels", "center_hz", "sample_rate", "format",
                "payload_len", "expected_packets", "demod", "symbol_order", "cutoff_hz", "channel_cutoff_hz", "iq_file"):
        if key in config:
            lines.append(f"| {key} | {show(config[key]).replace('|', '&#124;')} |")
    lines += ["", "## 数据与口径", "", f"完整结构化记录：[{summary_path.name}]({summary_path.name})。",
              "", "候选 CRC/FCS 失败计数不等于唯一物理坏包数；队列未溢出不证明 USB 无丢样。",
              "当前报告描述解码与测试负载校验，不表示命令执行或执行器同步。", ""]
    prefix = summary_path.name.removesuffix(".summary.json")
    for path in sorted(summary_path.parent.glob(prefix + ".*")):
        if path.name.endswith((".report.md", ".summary.json")):
            continue
        lines.append(f"- [{path.name}]({path.name})")
    lines += ["", "历史记录中保存的旧路径可通过 python/experiments/migration.manifest.json 或 manage.py locate 查询。", ""]
    for limit in summary.get("limitations", []):
        lines.append("- " + limit)
    return "\n".join(lines) + "\n"


def write_receiver_reports(summary, paths, experiment_dir=None):
    summary_path = paths["summary"]
    report_path = paths["report"]
    write_json(summary_path, summary)
    atomic_text(report_path, receiver_markdown(summary, summary_path))
    text = "\n".join(receiver_lines(summary)) + f"\n详细报告：{report_path}\n"
    atomic_text(paths["text"], text)
    # Explicit --output remains usable by old orchestrators, including outside
    # the central archive. Only registered/central sessions enter the index.
    session = Path(experiment_dir).resolve() if experiment_dir else session_for(summary_path)
    if session:
        refresh_session(session)
    return text


def session_for(path, root=EXPERIMENTS):
    try:
        relative = Path(path).resolve().relative_to(root.resolve())
    except ValueError:
        return None
    return root / relative.parts[0] if len(relative.parts) > 1 else None


def load_summaries(directory):
    records = []
    for path in sorted(directory.rglob("*.summary.json")):
        try:
            value = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            # Index corruption explicitly instead of silently dropping evidence.
            value = {"status": "unreadable", "error": str(exc)}
        if not isinstance(value, dict):
            value = {"status": "unrecognized", "error": "summary root is not an object"}
        records.append((path, value))
    return records


def relative_link(path, directory):
    return Path(os.path.relpath(path, directory)).as_posix()


def build_session(directory):
    records = load_summaries(directory)
    metadata = directory / "experiment.config.json"
    if not metadata.exists():
        write_json(metadata, {"schema": "experiment_v1", "experiment_id": directory.name,
                              "origin": "automatic", "scope": "See individual receiver and analysis records; grouping alone does not establish joint reception."})
    lines = [f"# 实验：{directory.name}", "", "本页自动生成；人工观察请写入 notes.md。运行正常结束不代表达到实验目标。", "",
             "## 接收结果", "", "| 记录 | 接收链 | 模式 | 程序状态 | Run ID | 有效包 | 唯一测试包 | IQ时长(s) |",
             "|---|---|---|---|---|---|---|---|"]
    runs = []
    for path, value in records:
        role = receiver_role(value)
        if not role:
            continue
        mode = "replay" if value.get("config", {}).get("iq_file") else "live"
        markdown = Path(str(path).removesuffix(".summary.json") + ".report.md")
        atomic_text(markdown, receiver_markdown(value, path))
        relative = relative_link(path, directory)
        count = value.get("counts", {}).get("packets" if role == "ble" else "fcs_valid_packets", 0)
        unique = value.get("receiver", {}).get("unique")
        lines.append(f"| [{relative.removesuffix('.summary.json')}]({relative_link(markdown, directory)}) | {role} | {mode} | {show(value.get('status'))} | {show(value.get('run_id'))} | {count} | {show(unique)} | {show(observation(value), 6)} |")
        rate = value.get("throughput", {}).get("application", {})
        config = value.get("config", {})
        wireless = value.get("ratios", {}).get("wireless_prr", {})
        runs.append({"experiment_id": directory.name, "record": relative, "receiver": role, "mode": mode,
                     "start_utc": value.get("start_utc"), "status": value.get("status"), "run_id": value.get("run_id"),
                     "payload_len": config.get("payload_len"), "expected_packets": config.get("expected_packets"),
                     "sample_rate": config.get("sample_rate"), "center_hz": config.get("center_hz"), "serial": config.get("serial"),
                     "cutoff_hz": config.get("cutoff_hz", config.get("channel_cutoff_hz")), "valid_packets": count,
                     "unique": unique, "duplicate": value.get("receiver", {}).get("duplicate"),
                     "iq_duration_s": observation(value), "wireless_prr": wireless.get("value"),
                     "wireless_prr_numerator": wireless.get("numerator"), "wireless_prr_denominator": wireless.get("denominator"),
                     "wireless_prr_reason": wireless.get("reason", "TX counts/window not merged" if not wireless else ""),
                     "application_byte_s": rate.get("byte_s"), "application_bit_s": rate.get("bit_s"),
                     "queue_overflow": value.get("capture_stats", {}).get("queue_overflow", 0)})
    lines += ["", "同目录不自动计算联合成功率；联合结果须依据已保存的逐标识匹配分析。独立设备的相对时间不能直接相减。", "",
              "## 分析与原始记录", ""]
    for path, value in records:
        if not receiver_role(value):
            link = relative_link(path, directory)
            lines.append(f"- [{link}]({link})（{show(value.get('status', '历史分析；状态未记录'))}）")
    for path in sorted(directory.rglob("*.md")):
        if path.name == "report.md" or path.name.endswith(".report.md"):
            continue
        link = relative_link(path, directory)
        lines.append(f"- [{link}]({link})")
    for path in sorted(directory.rglob("*")):
        if path.is_file() and (path.suffix in (".png", ".pdf") or path.name.endswith((".metrics.csv", ".board.log", ".manifest.json"))):
            link = relative_link(path, directory)
            lines.append(f"- [{link}]({link})")
    lines += ["", "配置：[experiment.config.json](experiment.config.json)。完整参数、分母依据和异常见各接收报告及原始 JSON。", ""]
    atomic_text(directory / "report.md", "\n".join(lines))
    statuses = {value["status"] for _, value in records if value.get("status")}
    state = next((status for status in ("error", "unreadable", "running", "interrupted", "complete") if status in statuses), "unrecorded")
    row = {"experiment_id": directory.name, "run_ids": ";".join(sorted({str(r["run_id"]) for r in runs if r["run_id"] is not None})),
           "status": state, "receiver_records": len(runs), "live_records": sum(r["mode"] == "live" for r in runs),
           "replay_records": sum(r["mode"] == "replay" for r in runs), "analysis_records": len(records) - len(runs),
           "report": f"{directory.name}/report.md"}
    return row, runs


INDEX_FIELDS = ["experiment_id", "run_ids", "status", "receiver_records", "live_records", "replay_records", "analysis_records", "report"]
RUN_FIELDS = ["experiment_id", "record", "receiver", "mode", "start_utc", "status", "run_id", "payload_len", "expected_packets",
              "sample_rate", "center_hz", "serial", "cutoff_hz", "valid_packets", "unique", "duplicate", "iq_duration_s",
              "wireless_prr", "wireless_prr_numerator", "wireless_prr_denominator", "wireless_prr_reason",
              "application_byte_s", "application_bit_s", "queue_overflow"]


def write_csv(path, fields, rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows({key: "N/A" if row.get(key) is None else row.get(key) for key in fields} for row in rows)
    atomic_text(path, stream.getvalue())


def rebuild_index(root=EXPERIMENTS):
    root = Path(root)
    with archive_lock(root):
        rows, runs = [], []
        for directory in sorted(root.iterdir()):
            if directory.is_dir() and (directory / "experiment.config.json").exists():
                row, detail = build_session(directory)
                rows.append(row)
                runs.extend(detail)
        write_csv(root / "index.csv", INDEX_FIELDS, rows)
        write_csv(root / "runs.csv", RUN_FIELDS, runs)
        migration = root / "migration.manifest.json"
        originals = {}
        if migration.exists():
            originals = {entry["destination"]: (old, entry) for old, entry in json.loads(migration.read_text())["paths"].items()}
        artifacts = []
        for row in rows:
            for path in sorted((root / row["experiment_id"]).rglob("*")):
                if not path.is_file() or path.name.startswith("."):
                    continue
                try:
                    key = path.relative_to(PROJECT).as_posix()
                except ValueError:
                    key = ""
                old, original = originals.get(key, (None, {}))
                artifacts.append({"experiment_id": row["experiment_id"], "path": path.relative_to(root).as_posix(),
                                  "bytes": path.stat().st_size, "sha256": original.get("sha256"), "legacy_path": old})
        write_csv(root / "artifacts.csv", ["experiment_id", "path", "bytes", "sha256", "legacy_path"], artifacts)
        lines = ["# 实验索引", "", "自动生成。每行一个归档目录；回放与实时采集数量分开，目录分组不代表独立重复或联合成功。", "",
                 "| 实验 | Run ID | 程序状态 | 实时记录 | 回放记录 | 分析记录 |", "|---|---|---|---|---|---|"]
        lines += [f"| [{r['experiment_id']}]({r['report']}) | {r['run_ids'] or 'N/A'} | {r['status']} | {r['live_records']} | {r['replay_records']} | {r['analysis_records']} |" for r in rows]
        lines += ["", "[实验表](index.csv) · [逐接收记录](runs.csv) · [本机文件清单与旧路径](artifacts.csv)", ""]
        atomic_text(root / "index.md", "\n".join(lines))
    return len(rows), len(runs)


def refresh_session(directory):
    directory = Path(directory).resolve()
    # One lock protects session reports and both indexes from simultaneous receivers.
    root = EXPERIMENTS if session_for(directory / "report.md") else directory.parent
    with archive_lock(root):
        build_session(directory)
    if root == EXPERIMENTS:
        rebuild_index(root)
