"""Summarize a completed 150-measurement comparison without contacting a router."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import statistics

from comparison import STAGES, WORKLOADS, compare_baselines, validate_measurement, validate_plan


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value, name, *, optional=False, integer=False):
    if value is None and optional:
        return None
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0, 'Invalid ' + name)
    require(not integer or type(value) is int, 'Non-integer ' + name)
    return value


def pin(value):
    require(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value), 'Missing source/image pin')
    return value


def summarize(report, plan):
    """Validate completeness before emitting a bounded, explicitly scoped summary."""
    validate_plan(plan)
    require(plan['repeats'] == 5 and len(plan['workloads']) == 6, 'Full 150-measurement plan required')
    expected = {row['id']: row for row in WORKLOADS}
    cases = {row['id']: row for row in plan['workloads']}
    require(cases.keys() == expected.keys(), 'Unexpected workload set')
    for key, row in cases.items():
        for field in ('kind', 'direction', 'payload_bytes'):
            require(row.get(field) == expected[key].get(field), 'Workload definition differs: ' + key)
    plan_hash = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    require(report.get('plan_sha256') == plan_hash, 'Report does not match this plan')
    require(report.get('status') == 'completed' and report.get('pass') is True and report.get('cleanup_pass') is True, 'Comparison is incomplete, failed or not clean')
    require(report.get('capacity_validated') is False, 'Virtual comparison must not claim hardware capacity')
    preflight = report.get('adapter_preflight', {})
    require(preflight.get('pass') is True and preflight.get('scope') == 'owned-isolated-lab', 'Owned DUT preflight missing')
    require(all(preflight.get(key) is True for key in ('source_matches_plan', 'generator_calibration_pass', 'cps_source_pool_validated')), 'Source/calibration preflight missing')
    allocation = {key: number(preflight.get(key), key, integer=True) for key in ('dut_vcpu', 'dut_memory_mib')}
    require(1 <= allocation['dut_vcpu'] <= 8 and 512 <= allocation['dut_memory_mib'] <= 4096, 'Invalid DUT allocation')
    restoration = report.get('restoration', {})
    require(all(restoration.get(key) is True for key in ('pass', 'verified', 'backing_chain_unchanged', 'resources_released')), 'Verified restoration missing')
    require(not any(row.get('simulation') for row in (report, preflight, restoration)), 'Simulation is not benchmark evidence')
    bindings = plan['bindings']
    provenance = {'plan_semantic_sha256': plan_hash,
                  'container_source_sha256': pin(bindings.get('controller_source_sha256'))}
    provenance.update({profile + '_image_config_sha256': pin(bindings['images'][profile].get('image_config_sha256')) for profile in ('base', 'web')})
    rows = report.get('runs', [])
    require(len(rows) == 150, 'Exactly 150 measurements required')
    groups = {(stage, case): [] for stage in STAGES for case in cases}
    seen = set()
    for row in rows:
        stage, case, repeat = row.get('stage'), row.get('case'), row.get('repeat')
        require((stage, case) in groups and type(repeat) is int and 0 <= repeat < 5, 'Unknown stage/case/repeat')
        key = stage, case, repeat
        require(key not in seen, 'Duplicate measurement')
        seen.add(key)
        metrics = validate_measurement(row['metrics'], stage)
        require(not row.get('simulation') and not metrics.get('simulation'), 'Simulation is not benchmark evidence')
        kind = cases[case]['kind']
        require(metrics.get('rate_unit') == {'tcp': 'bps', 'udp': 'pps', 'cps': 'cps'}[kind], 'Rate unit differs from workload')
        for field, limit in (('generator_cpu_p95_max_percent', 'generator_cpu_p95_max_percent'), ('host_steal_p95_percent', 'host_steal_p95_max_percent')):
            require(metrics[field] <= plan['criteria'][limit], 'Generator/host reserve failed')
        if stage in ('container', 'container-web'):
            require(metrics['container_memory_peak_bytes'] > 0, 'Container memory missing')
        if kind == 'tcp':
            forward = number(metrics.get('forward_receiver_bps'), 'forward TCP rate')
            reverse = number(metrics.get('reverse_receiver_bps'), 'reverse TCP rate')
            require(math.isclose(forward + reverse, metrics['receiver_rate'], rel_tol=1e-9), 'TCP direction rates do not add up')
        groups[stage, case].append(metrics)
    baselines = compare_baselines(rows, plan['criteria']['baseline_variation_max_percent'])
    require(all(row['pass'] for row in baselines), 'Baseline drift invalidates comparison')
    require(report.get('baseline_checks') == baselines, 'Stored baseline checks differ')
    measurements = []
    for case in cases:
        workload = cases[case]
        offer = number(workload.get({'tcp': 'offered_bps', 'udp': 'offered_pps', 'cps': 'rate'}[workload['kind']]), 'offered rate')
        for stage in STAGES:
            samples = groups[stage, case]
            require(len(samples) == 5, 'Incomplete repeat group')
            writes = [sample.get('write_sectors_delta') for sample in samples]
            measurements.append({
                'case': case, 'stage': stage, 'samples': 5, 'rate_unit': samples[0]['rate_unit'],
                'offered_rate_per_direction': offer,
                'offered_rate_total': offer * (2 if workload.get('direction') == 'bidir' else 1),
                'udp_payload_bytes': workload.get('payload_bytes'),
                'receiver_rate_median': statistics.median(sample['receiver_rate'] for sample in samples),
                'forward_receiver_bps_median': statistics.median(sample['forward_receiver_bps'] for sample in samples) if cases[case]['kind'] == 'tcp' else None,
                'reverse_receiver_bps_median': statistics.median(sample['reverse_receiver_bps'] for sample in samples) if cases[case]['kind'] == 'tcp' else None,
                'dut_cpu_mean_percent_median': statistics.median(sample['dut_cpu_mean_percent'] for sample in samples),
                'dut_cpu_p95_percent_max': max(sample['dut_cpu_p95_percent'] for sample in samples),
                'dut_memory_free_min_bytes': min(sample['dut_memory_free_min_bytes'] for sample in samples),
                'container_memory_peak_bytes': max(sample['container_memory_peak_bytes'] for sample in samples),
                'generator_cpu_p95_max_percent': max(sample['generator_cpu_p95_max_percent'] for sample in samples),
                'host_steal_p95_max_percent': max(sample['host_steal_p95_percent'] for sample in samples),
                'write_sectors_delta_median': statistics.median(writes) if all(value is not None for value in writes) else None,
                'write_counter_known_samples': sum(value is not None for value in writes),
            })
    switching = []
    switches = report.get('switching', [])
    require(len(switches) == 3 and {row.get('stage') for row in switches} == set(STAGES[1:-1]), 'Three distinct switching stages required')
    for row in switches:
        result = row['result']
        require(result.get('pass') is True and result.get('pinned_flow_preserved') is True and result.get('observer') == 'sdwan_lab.continuity' and not result.get('simulation'), 'Switching/pinned flow failed')
        for role in ('affected', 'pinned'):
            for protocol in ('udp', 'tcp'):
                sample = result['observations'][role][protocol]
                fields = {key: number(sample.get(key), key, integer=True) for key in ('offered', 'received', 'unanswered', 'established_sessions', 'disconnects')}
                require(fields['received'] + fields['unanswered'] == fields['offered'], 'Echo counters do not add up')
                if role == 'pinned' and protocol == 'udp':
                    require(fields['unanswered'] == 0, 'Pinned UDP lost replies')
                if role == 'pinned' and protocol == 'tcp':
                    require(fields['established_sessions'] == 1 and fields['disconnects'] == 0, 'Pinned TCP was interrupted')
                if role == 'affected' and protocol == 'udp':
                    require(fields['unanswered'] > 0, 'Failure was not observed')
                if role == 'affected' and protocol == 'tcp':
                    require(fields['established_sessions'] >= 2, 'Affected TCP did not reconnect')
                switching.append(dict(stage=row['stage'], role=role, protocol=protocol, **fields,
                                      max_success_gap_ms=number(sample.get('max_success_gap_ms'), 'echo gap', optional=True)))
    return {'schema_version': 1, 'status': 'completed', 'pass': True, 'capacity_validated': False,
            'measurement_count': 150, 'warmup_seconds': plan['warmup_seconds'], 'measure_seconds': plan['seconds'],
            'dut_allocation': allocation,
            'provenance': provenance, 'measurements': measurements, 'baseline_checks': baselines, 'switching': switching}


def markdown(summary, language):
    ru = language == 'ru'
    require(language in ('ru', 'en'), 'Language must be ru or en')
    lines = ['# ' + ('Сравнение SD-WAN: 150 измерений' if ru else 'SD-WAN comparison: 150 measurements'), '',
             ('Виртуальный стенд. Аппаратная производительность не подтверждена.' if ru else 'Virtual lab. Physical hardware capacity is not established.'), '',
             f"DUT: {summary['dut_allocation']['dut_vcpu']} vCPU, {summary['dut_allocation']['dut_memory_mib']} MiB; " +
             (f"прогрев {summary['warmup_seconds']} с, измерение {summary['measure_seconds']} с." if ru else f"warmup {summary['warmup_seconds']} s, measurement {summary['measure_seconds']} s."), '',
             ('Сравнение использует фиксированную заданную нагрузку и не определяет максимальную пропускную способность.' if ru else 'This compares a fixed offered load; it does not determine maximum throughput.'), '',
             ('В таблице медианы пяти повторов; CPU p95 — максимум пяти p95. Bidir складывает оба направления.' if ru else 'Five-repeat medians; CPU p95 is the maximum of five p95 values. Bidir sums both directions.'), '',
             ('Память контейнера — максимум выборок cgroup, не RSS и не kernel memory.peak. Секторы записи — логический счётчик RouterOS, не циклы NAND.' if ru else 'Container memory is the maximum sampled cgroup value, not RSS or kernel memory.peak. Write sectors are a RouterOS logical counter, not NAND cycles.'), '',
             '| ' + ('Нагрузка | Режим | Задано суммарно | Получено | CPU mean % | CPU p95 % | Свободно MiB | Контейнер KiB | Секторы |' if ru else 'Workload | Stage | Total offered | Received | CPU mean % | CPU p95 % | Free MiB | Container KiB | Sectors |'),
             '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for row in summary['measurements']:
        rate = row['receiver_rate_median'] / 1e6 if row['rate_unit'] == 'bps' else row['receiver_rate_median']
        unit = 'Mbit/s' if row['rate_unit'] == 'bps' else row['rate_unit']
        offer = row['offered_rate_total'] / 1e6 if row['rate_unit'] == 'bps' else row['offered_rate_total']
        write = ('неизвестно' if ru else 'unknown') if row['write_sectors_delta_median'] is None else f"{row['write_sectors_delta_median']:g}"
        lines.append(f"| {row['case']} | {row['stage']} | {offer:.3f} {unit} | {rate:.3f} {unit} | {row['dut_cpu_mean_percent_median']:.2f} | {row['dut_cpu_p95_percent_max']:.2f} | {row['dut_memory_free_min_bytes']/1024**2:.3f} | {row['container_memory_peak_bytes']/1024:.3f} | {write} |")
    lines += ['', '## ' + ('Непрерывность при переключении' if ru else 'Switching continuity'), '',
              ('Максимум за всё окно отказа и возврата. Промежуток между echo-ответами включает интервал проб, RTT и планирование; это не точное время сетевого отказа.' if ru else 'Maximum over the whole failure/recovery window. The gap between echo replies includes probe interval, RTT and scheduling; it is not exact network outage time.'), '',
              '| ' + ('Режим | Поток | Протокол | Без ответа | TCP-сессии | Разрывы | Макс. промежуток ms |' if ru else 'Stage | Flow | Protocol | Unanswered | TCP sessions | Disconnects | Max gap ms |'),
              '|---|---|---|---:|---:|---:|---:|']
    for row in summary['switching']:
        gap = ('неизвестно' if ru else 'unknown') if row['max_success_gap_ms'] is None else f"{row['max_success_gap_ms']:.3f}"
        lines.append(f"| {row['stage']} | {row['role']} | {row['protocol']} | {row['unanswered']} | {row['established_sessions']} | {row['disconnects']} | {gap} |")
    lines += ['', '## SHA256', '']
    for key, value in summary['provenance'].items():
        if isinstance(value, str): lines.append(f'- {key}: `{value}`')
    return '\n'.join(lines) + '\n'


def export(report_path, plan_path, output):
    report_raw, plan_raw = report_path.read_bytes(), plan_path.read_bytes()
    summary = summarize(json.loads(report_raw), json.loads(plan_raw))
    summary['provenance'].update(report_file_sha256=hashlib.sha256(report_raw).hexdigest(), plan_file_sha256=hashlib.sha256(plan_raw).hexdigest())
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    (output / 'summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    for language in ('ru', 'en'):
        (output / ('summary.' + language + '.md')).write_text(markdown(summary, language), encoding='utf-8')
    with (output / 'measurements.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(summary['measurements'][0])); writer.writeheader(); writer.writerows(summary['measurements'])
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True); parser.add_argument('--plan', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    summary = export(args.report, args.plan, args.output)
    print(json.dumps({'pass': summary['pass'], 'measurements': summary['measurement_count'], 'capacity_validated': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
