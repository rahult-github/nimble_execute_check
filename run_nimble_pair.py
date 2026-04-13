#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

try:
    import serial
except ImportError as e:
    raise SystemExit('Missing dependency: pyserial. Install with `pip install pyserial`.') from e


def resolve_nimble_dir() -> Path:
    idf_path = os.environ.get('IDF_PATH', '').strip()
    if not idf_path:
        raise SystemExit('IDF_PATH is not set. Run `source export.sh` first.')

    nimble_dir = Path(idf_path).expanduser().resolve() / 'examples' / 'bluetooth' / 'nimble'
    if not nimble_dir.is_dir():
        raise SystemExit(f'NimBLE examples directory not found: {nimble_dir}')
    return nimble_dir


NIMBLE_DIR = resolve_nimble_dir()
DEFAULT_FAIL_REGEX = r'Error:|assert|panic|guru meditation|backtrace|abort\(|traceback'


@dataclass(frozen=True)
class PairConfig:
    peripheral_app: str
    central_app: str
    peripheral_ok: str
    central_ok: str
    timeout_s: int = 90
    require_full_window: bool = False
    min_central_matches: int = 1
    max_central_gap_s: int | None = None
    peripheral_fail: str = DEFAULT_FAIL_REGEX
    central_fail: str = DEFAULT_FAIL_REGEX
    peripheral_steps: tuple[str, ...] = ()
    central_steps: tuple[str, ...] = ()
    inject_peripheral_keys: str = ''
    inject_central_keys: str = ''
    inject_key_count: int = 0
    inject_interval_s: float = 0.3
    inject_start_delay_s: float = 5.0


PAIR_CONFIGS: dict[str, PairConfig] = {
    'bleprh_blecent': PairConfig(
        peripheral_app='bleprph',
        central_app='blecent',
        peripheral_ok=(
            r'subscribe event;|Characteristic write;|Notification/Indication scheduled|'
            r'GATT procedure initiated: notify;|Characteristic read by NimBLE stack;|'
            r'notify_tx event;|Characteristic read;'
        ),
        central_ok=(
            r'Subscribe complete; status=0|'
            r'Subscribe to the custom subscribable characteristic complete; status=0|'
            r'Write to the custom subscribable characteristic complete; status=0|'
            r'Read complete for the subscribable characteristic; status=0'
        ),
    ),
    'bleprph_blecent': PairConfig(
        peripheral_app='bleprph',
        central_app='blecent',
        peripheral_ok=(
            r'subscribe event;|Characteristic write;|Notification/Indication scheduled|'
            r'GATT procedure initiated: notify;|Characteristic read by NimBLE stack;|'
            r'notify_tx event;|Characteristic read;'
        ),
        central_ok=(
            r'Subscribe complete; status=0|'
            r'Subscribe to the custom subscribable characteristic complete; status=0|'
            r'Write to the custom subscribable characteristic complete; status=0|'
            r'Read complete for the subscribable characteristic; status=0'
        ),
    ),
    'ble_cte': PairConfig(
        peripheral_app='ble_cte/ble_periodic_adv_with_cte',
        central_app='ble_cte/ble_periodic_sync_with_cte',
        peripheral_ok='',
        central_ok=r'IQ Report \| Sync Handle:',
        timeout_s=60,
        require_full_window=True,
        min_central_matches=5,
        max_central_gap_s=10,
    ),
    'ble_cts': PairConfig(
        peripheral_app='ble_cts/cts_prph',
        central_app='ble_cts/cts_cent',
        peripheral_ok=r'connection established; status=0',
        central_ok=r'Read Current time complete; status=0',
    ),
    'ble_enc_adv_data': PairConfig(
        peripheral_app='ble_enc_adv_data/enc_adv_data_prph',
        central_app='ble_enc_adv_data/enc_adv_data_cent',
        peripheral_ok=r'authorization event; .*is_read=1|Encryption of adv data done successfully',
        central_ok=r'Writing of session key, iv, and peer addr to NVS success|Decryption of adv data done successfully',
    ),
    'ble_htp': PairConfig(
        peripheral_app='ble_htp/htp_prph',
        central_app='ble_htp/htp_cent',
        peripheral_ok=r'subscribe event; cur_notify=1|Notification sent successfully|GATT procedure initiated: notify;',
        central_ok=(
            r'Read temperature type char completed; status=0|'
            r'Write to measurement interval char completed; status=0|'
            r'Subscribe to temperature measurement char completed; status=(0|261)|'
            r'Subscribe to intermediate temperature char completed; status=(0|261)|'
            r'received notification; conn_handle='
        ),
    ),
    'ble_l2cap_coc': PairConfig(
        peripheral_app='ble_l2cap_coc/coc_bleprph',
        central_app='ble_l2cap_coc/coc_blecent',
        peripheral_ok=r'LE COC connected|LE CoC accepting',
        central_ok=r'Data sent successfully',
    ),
    'ble_multi_conn': PairConfig(
        peripheral_app='ble_multi_conn/ble_multi_conn_prph',
        central_app='ble_multi_conn/ble_multi_conn_cent',
        peripheral_ok=r'Connection established\. Handle:[0-9]+\. Total:([2-9]|[1-9][0-9]+)',
        central_ok=r'Connection established\. Handle:[0-9]+, Total:([2-9]|[1-9][0-9]+)',
        timeout_s=120,
    ),
    'ble_pawr_adv': PairConfig(
        peripheral_app='ble_pawr_adv/ble_pawr_adv',
        central_app='ble_pawr_adv/ble_pawr_sync',
        peripheral_ok='',
        central_ok=r'\[Periodic Adv Report\]',
        timeout_s=60,
        require_full_window=True,
        min_central_matches=10,
        max_central_gap_s=10,
    ),
    'ble_pawr_adv_conn': PairConfig(
        peripheral_app='ble_pawr_adv_conn/ble_pawr_adv_conn',
        central_app='ble_pawr_adv_conn/ble_pawr_sync_conn',
        peripheral_ok=r'\[Request\] data:|\[Response\] subevent:',
        central_ok=r'\[Periodic Adv Report\]|\[RSP Data Set\]',
        timeout_s=60,
        require_full_window=True,
        min_central_matches=10,
        max_central_gap_s=10,
    ),
    'ble_periodic_adv': PairConfig(
        peripheral_app='ble_periodic_adv',
        central_app='ble_periodic_sync',
        peripheral_ok='',
        central_ok=r'Periodic adv report event',
        timeout_s=60,
        require_full_window=True,
        min_central_matches=5,
        max_central_gap_s=10,
    ),
    'ble_phy': PairConfig(
        peripheral_app='ble_phy/phy_prph',
        central_app='ble_phy/phy_cent',
        peripheral_ok=r'advertise complete; reason=0|disconnect; reason=',
        central_ok=r'Read complete; status=261|Write complete; status=261',
    ),
    'ble_proximity_sensor': PairConfig(
        peripheral_app='ble_proximity_sensor/proximity_sensor_prph',
        central_app='ble_proximity_sensor/proximity_sensor_cent',
        peripheral_ok=r'connection established; status=0',
        central_ok=r'Connection established',
    ),
    'ble_spp': PairConfig(
        peripheral_app='ble_spp/spp_server',
        central_app='ble_spp/spp_client',
        peripheral_ok=(
            r'subscribe event; .*curn=1|'
            r'Data received in write event|'
            r'Notification sent successfully'
        ),
        central_ok=(
            r'Service discovery complete; status=0|'
            r'Write in uart task success!|'
            r'received notification; conn_handle='
        ),
        peripheral_steps=(
            r'subscribe event; .*curn=1',
            r'Data received in write event',
            r'Notification sent successfully',
        ),
        central_steps=(
            r'Service discovery complete; status=0',
            r'Write in uart task success!',
            r'received notification; conn_handle=',
        ),
        inject_peripheral_keys='1234',
        inject_central_keys='abcd',
        inject_key_count=12,
        inject_interval_s=0.25,
        inject_start_delay_s=5.0,
        timeout_s=120,
    ),
    'throughput_app': PairConfig(
        peripheral_app='throughput_app/bleprph_throughput',
        central_app='throughput_app/blecent_throughput',
        peripheral_ok=r'connection established; status = 0',
        central_ok=r'Connection established',
        timeout_s=120,
    ),
}

# Canonical order for batch runs. Keep alias-only keys out of this list.
ALL_PAIR_KEYS: list[str] = [
    'bleprph_blecent',
    'ble_cte',
    'ble_cts',
    'ble_enc_adv_data',
    'ble_htp',
    'ble_l2cap_coc',
    'ble_multi_conn',
    'ble_pawr_adv',
    'ble_pawr_adv_conn',
    'ble_periodic_adv',
    'ble_phy',
    'ble_proximity_sensor',
    'ble_spp',
    'throughput_app',
]

SUPPORTED_TARGETS_CACHE: dict[Path, set[str] | None] = {}


def target_to_readme_token(target: str) -> str:
    t = target.strip().lower()
    if t == 'esp32':
        return 'ESP32'
    if t.startswith('esp32'):
        # esp32c3 -> ESP32-C3, esp32s3 -> ESP32-S3, esp32h2 -> ESP32-H2
        return f'ESP32-{t[len("esp32"):].upper()}'
    return t.upper()


def get_supported_targets_from_readme(app_dir: Path) -> set[str] | None:
    readme = app_dir / 'README.md'
    if readme in SUPPORTED_TARGETS_CACHE:
        return SUPPORTED_TARGETS_CACHE[readme]
    if not readme.is_file():
        SUPPORTED_TARGETS_CACHE[readme] = None
        return None

    supported: set[str] | None = None
    for line in readme.read_text(encoding='utf-8', errors='ignore').splitlines():
        if line.lstrip().startswith('| Supported Targets |'):
            cells = [c.strip() for c in line.strip().split('|')[1:-1]]
            # Row format: | Supported Targets | ESP32 | ESP32-C3 | ... |
            supported = {c.upper() for c in cells[1:] if c}
            break

    SUPPORTED_TARGETS_CACHE[readme] = supported
    return supported


def run_cmd(cmd: list[str]) -> None:
    print(f'[cmd] {" ".join(cmd)}', flush=True)
    subprocess.run(cmd, check=True)


def build_and_flash(app_dir: Path, target: str, port: str, build_root: Path, clean_build: bool) -> None:
    build_dir = build_root / f'{app_dir.name}_{target}'
    build_dir.mkdir(parents=True, exist_ok=True)
    sdkconfig_path = build_dir / 'sdkconfig'

    if clean_build:
        run_cmd(['idf.py', '-C', str(app_dir), '-B', str(build_dir), 'fullclean'])

    # Keep target-specific sdkconfig out of example dir to avoid mismatch with
    # pre-existing project sdkconfig (for example esp32c3 vs esp32).
    run_cmd(
        [
            'idf.py',
            '-C',
            str(app_dir),
            '-B',
            str(build_dir),
            f'-DIDF_TARGET={target}',
            f'-DSDKCONFIG={sdkconfig_path}',
            'build',
        ]
    )
    run_cmd(['idf.py', '-C', str(app_dir), '-B', str(build_dir), '-p', port, 'flash'])


def monitor_two_ports(
    peripheral_port: str,
    central_port: str,
    baud: int,
    peripheral_ok: str,
    central_ok: str,
    peripheral_fail: str,
    central_fail: str,
    peripheral_steps: tuple[str, ...],
    central_steps: tuple[str, ...],
    inject_peripheral_keys: str,
    inject_central_keys: str,
    inject_key_count: int,
    inject_interval_s: float,
    inject_start_delay_s: float,
    timeout_s: int,
    require_full_window: bool = False,
    min_central_matches: int = 1,
    max_central_gap_s: int | None = None,
) -> None:
    peripheral_re = re.compile(peripheral_ok) if peripheral_ok else None
    central_re = re.compile(central_ok) if central_ok else None
    peripheral_fail_re = re.compile(peripheral_fail, flags=re.IGNORECASE) if peripheral_fail else None
    central_fail_re = re.compile(central_fail, flags=re.IGNORECASE) if central_fail else None
    peripheral_steps_re = tuple(re.compile(p) for p in peripheral_steps)
    central_steps_re = tuple(re.compile(p) for p in central_steps)
    peripheral_steps_hit = [False] * len(peripheral_steps_re)
    central_steps_hit = [False] * len(central_steps_re)
    inject_peripheral_bytes = inject_peripheral_keys.encode() if inject_peripheral_keys else b''
    inject_central_bytes = inject_central_keys.encode() if inject_central_keys else b''
    peripheral_hit = peripheral_re is None
    central_hit = central_re is None
    central_match_count = 0
    last_central_match_ts: float | None = None

    start = time.monotonic()
    next_inject_ts = start + inject_start_delay_s if inject_key_count > 0 else None
    inject_round = 0
    with (
        serial.Serial(peripheral_port, baudrate=baud, timeout=0.2) as peripheral_ser,
        serial.Serial(central_port, baudrate=baud, timeout=0.2) as central_ser,
    ):
        while time.monotonic() - start < timeout_s:
            now = time.monotonic()
            if next_inject_ts is not None and now >= next_inject_ts and inject_round < inject_key_count:
                if inject_peripheral_bytes:
                    pb = bytes([inject_peripheral_bytes[inject_round % len(inject_peripheral_bytes)]])
                    peripheral_ser.write(pb)
                    print(f'[inject] peripheral_uart <= {pb!r}', flush=True)
                if inject_central_bytes:
                    cb = bytes([inject_central_bytes[inject_round % len(inject_central_bytes)]])
                    central_ser.write(cb)
                    print(f'[inject] central_uart <= {cb!r}', flush=True)
                inject_round += 1
                next_inject_ts += inject_interval_s

            if require_full_window and max_central_gap_s is not None and last_central_match_ts is not None:
                if now - last_central_match_ts > max_central_gap_s:
                    raise RuntimeError(
                        f'FAIL after {timeout_s}s: central regex stalled for {now - last_central_match_ts:.1f}s '
                        f'(limit {max_central_gap_s}s): {central_ok}'
                    )

            for role, ser_obj, matcher, fail_matcher, fail_regex in (
                ('peripheral', peripheral_ser, peripheral_re, peripheral_fail_re, peripheral_fail),
                ('central', central_ser, central_re, central_fail_re, central_fail),
            ):
                raw = ser_obj.readline()
                if not raw:
                    continue
                line = raw.decode(errors='ignore').rstrip()
                print(f'[{role}] {line}', flush=True)
                if fail_matcher and fail_matcher.search(line):
                    raise RuntimeError(f'FAIL: {role} fail-regex matched: {fail_regex}; line={line}')
                if role == 'peripheral' and peripheral_steps_re:
                    for idx, step_re in enumerate(peripheral_steps_re):
                        if not peripheral_steps_hit[idx] and step_re.search(line):
                            peripheral_steps_hit[idx] = True
                            print(f'[match-step] peripheral step {idx + 1}/{len(peripheral_steps_re)} matched', flush=True)
                if role == 'central' and central_steps_re:
                    for idx, step_re in enumerate(central_steps_re):
                        if not central_steps_hit[idx] and step_re.search(line):
                            central_steps_hit[idx] = True
                            print(f'[match-step] central step {idx + 1}/{len(central_steps_re)} matched', flush=True)
                if role == 'peripheral' and matcher and not peripheral_hit and matcher.search(line):
                    peripheral_hit = True
                    print(f'[match] peripheral regex matched: {peripheral_ok}', flush=True)
                if role == 'central' and matcher and matcher.search(line):
                    central_match_count += 1
                    last_central_match_ts = time.monotonic()
                    if not central_hit:
                        central_hit = True
                        print(f'[match] central regex matched: {central_ok}', flush=True)

            peripheral_steps_ok = all(peripheral_steps_hit) if peripheral_steps_hit else True
            central_steps_ok = all(central_steps_hit) if central_steps_hit else True
            if not require_full_window and peripheral_hit and central_hit and peripheral_steps_ok and central_steps_ok:
                print('[result] PASS: both functional checks matched', flush=True)
                return

    missing = []
    if not peripheral_hit:
        missing.append(f'peripheral regex not matched: {peripheral_ok}')
    if not central_hit:
        missing.append(f'central regex not matched: {central_ok}')
    if peripheral_steps_hit and not all(peripheral_steps_hit):
        pending = [peripheral_steps[i] for i, hit in enumerate(peripheral_steps_hit) if not hit]
        missing.append(f'peripheral required log(s) missing: {" | ".join(pending)}')
    if central_steps_hit and not all(central_steps_hit):
        pending = [central_steps[i] for i, hit in enumerate(central_steps_hit) if not hit]
        missing.append(f'central required log(s) missing: {" | ".join(pending)}')
    elif central_match_count < min_central_matches:
        missing.append(
            f'central regex matched only {central_match_count} times; '
            f'min required: {min_central_matches}: {central_ok}'
        )
    elif require_full_window and max_central_gap_s is not None and last_central_match_ts is not None:
        idle_s = time.monotonic() - last_central_match_ts
        if idle_s > max_central_gap_s:
            missing.append(
                f'central regex stopped for {idle_s:.1f}s near end; '
                f'limit {max_central_gap_s}s: {central_ok}'
            )

    if require_full_window and not missing:
        print(
            f'[result] PASS: full-window check passed; central regex matched {central_match_count} times in {timeout_s}s',
            flush=True,
        )
        return

    raise RuntimeError(f'FAIL after {timeout_s}s: ' + '; '.join(missing))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Build/flash a NimBLE peripheral app on DUT-1 and central app on DUT-2, then verify functionality.'
    )
    parser.add_argument('--list-pairs', action='store_true', help='List supported pair presets and exit.')
    parser.add_argument('--pair', choices=sorted(PAIR_CONFIGS.keys()), help='Pair preset name.')
    parser.add_argument('--all-pairs', action='store_true', help='Run all supported pair presets for the selected target.')
    parser.add_argument('--target', required=False, help='IDF target for both DUTs (for example: esp32c3).')
    parser.add_argument('--port-peripheral', required=False, help='UART port for peripheral DUT (for example: /dev/ttyUSB0).')
    parser.add_argument('--port-central', required=False, help='UART port for central DUT (for example: /dev/ttyUSB1).')
    parser.add_argument('--baud', type=int, default=115200, help='UART baud for log monitoring. Default: 115200.')
    parser.add_argument('--timeout', type=int, help='Override monitor timeout in seconds.')
    parser.add_argument('--build-root', default='/tmp/nimble_pair_builds', help='Out-of-tree build root path.')
    parser.add_argument('--clean-build', action='store_true', help='Run fullclean before build.')
    parser.add_argument('--skip-build-flash', action='store_true', help='Skip build/flash, only monitor logs.')
    parser.add_argument('--peripheral-app', help='Override peripheral app path (relative to examples/bluetooth/nimble).')
    parser.add_argument('--central-app', help='Override central app path (relative to examples/bluetooth/nimble).')
    parser.add_argument('--peripheral-ok', help='Override peripheral regex used to confirm functionality.')
    parser.add_argument('--central-ok', help='Override central regex used to confirm functionality.')
    parser.add_argument('--peripheral-fail', help='Override peripheral regex used to fail fast on error logs.')
    parser.add_argument('--central-fail', help='Override central regex used to fail fast on error logs.')
    return parser


def pair_supported_on_target(pair: str, target: str | None) -> bool:
    if not target:
        return True
    cfg = PAIR_CONFIGS[pair]
    token = target_to_readme_token(target)
    for rel in (cfg.peripheral_app, cfg.central_app):
        app_dir = (NIMBLE_DIR / rel).resolve()
        supported = get_supported_targets_from_readme(app_dir)
        # If README table is missing, don't block execution.
        if supported is None:
            continue
        if token not in supported:
            return False
    return True


def resolve_pair_cfg(
    args: argparse.Namespace, pair_name: str
) -> tuple[
    Path,
    Path,
    str,
    str,
    str,
    str,
    tuple[str, ...],
    tuple[str, ...],
    str,
    str,
    int,
    float,
    float,
    int,
    bool,
    int,
    int | None,
]:
    cfg = PAIR_CONFIGS[pair_name]
    peripheral_rel = args.peripheral_app or cfg.peripheral_app
    central_rel = args.central_app or cfg.central_app
    peripheral_ok = args.peripheral_ok or cfg.peripheral_ok
    central_ok = args.central_ok or cfg.central_ok
    peripheral_fail = args.peripheral_fail or cfg.peripheral_fail
    central_fail = args.central_fail or cfg.central_fail
    peripheral_steps = cfg.peripheral_steps
    central_steps = cfg.central_steps
    inject_peripheral_keys = cfg.inject_peripheral_keys
    inject_central_keys = cfg.inject_central_keys
    inject_key_count = cfg.inject_key_count
    inject_interval_s = cfg.inject_interval_s
    inject_start_delay_s = cfg.inject_start_delay_s
    timeout_s = args.timeout or cfg.timeout_s

    peripheral_app = (NIMBLE_DIR / peripheral_rel).resolve()
    central_app = (NIMBLE_DIR / central_rel).resolve()
    if not peripheral_app.is_dir():
        raise SystemExit(f'Peripheral app path does not exist: {peripheral_app}')
    if not central_app.is_dir():
        raise SystemExit(f'Central app path does not exist: {central_app}')
    return (
        peripheral_app,
        central_app,
        peripheral_ok,
        central_ok,
        peripheral_fail,
        central_fail,
        peripheral_steps,
        central_steps,
        inject_peripheral_keys,
        inject_central_keys,
        inject_key_count,
        inject_interval_s,
        inject_start_delay_s,
        timeout_s,
        cfg.require_full_window,
        cfg.min_central_matches,
        cfg.max_central_gap_s,
    )


def run_single_pair(args: argparse.Namespace, pair_name: str) -> None:
    (
        peripheral_app,
        central_app,
        peripheral_ok,
        central_ok,
        peripheral_fail,
        central_fail,
        peripheral_steps,
        central_steps,
        inject_peripheral_keys,
        inject_central_keys,
        inject_key_count,
        inject_interval_s,
        inject_start_delay_s,
        timeout_s,
        require_full_window,
        min_central_matches,
        max_central_gap_s,
    ) = resolve_pair_cfg(args, pair_name)
    print(f'[pair] {pair_name}')
    print(f'[peripheral_app] {peripheral_app}')
    print(f'[central_app] {central_app}')
    print(f'[peripheral_port] {args.port_peripheral}')
    print(f'[central_port] {args.port_central}')
    print(f'[peripheral_ok] {peripheral_ok}')
    print(f'[central_ok] {central_ok}')
    print(f'[peripheral_fail] {peripheral_fail}')
    print(f'[central_fail] {central_fail}')
    if peripheral_steps:
        print(f'[peripheral_steps] {len(peripheral_steps)}')
    if central_steps:
        print(f'[central_steps] {len(central_steps)}')
    if inject_key_count > 0:
        print(f'[inject_key_count] {inject_key_count}')
        print(f'[inject_interval_s] {inject_interval_s}')
        print(f'[inject_start_delay_s] {inject_start_delay_s}')
    print(f'[timeout_s] {timeout_s}')
    if require_full_window:
        print(f'[full_window] enabled')
        print(f'[min_central_matches] {min_central_matches}')
        print(f'[max_central_gap_s] {max_central_gap_s}')

    if not args.skip_build_flash:
        build_root = Path(args.build_root).resolve()
        build_root.mkdir(parents=True, exist_ok=True)
        build_and_flash(peripheral_app, args.target, args.port_peripheral, build_root, args.clean_build)
        build_and_flash(central_app, args.target, args.port_central, build_root, args.clean_build)

    monitor_two_ports(
        peripheral_port=args.port_peripheral,
        central_port=args.port_central,
        baud=args.baud,
        peripheral_ok=peripheral_ok,
        central_ok=central_ok,
        peripheral_fail=peripheral_fail,
        central_fail=central_fail,
        peripheral_steps=peripheral_steps,
        central_steps=central_steps,
        inject_peripheral_keys=inject_peripheral_keys,
        inject_central_keys=inject_central_keys,
        inject_key_count=inject_key_count,
        inject_interval_s=inject_interval_s,
        inject_start_delay_s=inject_start_delay_s,
        timeout_s=timeout_s,
        require_full_window=require_full_window,
        min_central_matches=min_central_matches,
        max_central_gap_s=max_central_gap_s,
    )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.list_pairs:
        for name, cfg in PAIR_CONFIGS.items():
            print(f'{name}: {cfg.peripheral_app} <-> {cfg.central_app}')
        return 0

    if args.all_pairs and args.pair:
        parser.error('Use either --pair or --all-pairs, not both.')
    if not args.pair and not args.all_pairs:
        parser.error('--pair or --all-pairs is required unless --list-pairs is used.')
    if args.all_pairs and (
        args.peripheral_app
        or args.central_app
        or args.peripheral_ok
        or args.central_ok
        or args.peripheral_fail
        or args.central_fail
    ):
        parser.error('Custom app/regex overrides are only supported with --pair.')

    if not args.port_peripheral or not args.port_central:
        parser.error('--port-peripheral and --port-central are required.')
    if not args.target and not args.skip_build_flash:
        parser.error('--target is required unless --skip-build-flash is used.')
    if args.all_pairs and not args.target:
        parser.error('--target is required with --all-pairs.')

    if args.pair:
        if args.target and not pair_supported_on_target(args.pair, args.target):
            raise SystemExit(f'Pair {args.pair} is not supported for target {args.target} per app README Supported Targets.')
        run_single_pair(args, args.pair)
        return 0

    selected_pairs = [p for p in ALL_PAIR_KEYS if pair_supported_on_target(p, args.target)]
    if not selected_pairs:
        raise SystemExit(f'No pairs are supported for target {args.target}.')

    print(f'[all-pairs] target={args.target} total={len(selected_pairs)}')
    passed: list[str] = []
    failed: list[tuple[str, str]] = []
    for idx, pair_name in enumerate(selected_pairs, start=1):
        print(f'\n[all-pairs] ({idx}/{len(selected_pairs)}) running {pair_name}')
        try:
            run_single_pair(args, pair_name)
            passed.append(pair_name)
            print(f'[all-pairs] PASS {pair_name}')
        except Exception as e:  # noqa: BLE001
            failed.append((pair_name, str(e)))
            print(f'[all-pairs] FAIL {pair_name}: {e}')

    print('\n[all-pairs-summary]')
    print(f'passed={len(passed)} failed={len(failed)}')
    if passed:
        print('passed_pairs=' + ', '.join(passed))
    if failed:
        print('failed_pairs=' + ', '.join(name for name, _ in failed))
        for name, reason in failed:
            print(f' - {name}: {reason}')
        return 1

    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\nInterrupted by user')
        sys.exit(130)
    except subprocess.CalledProcessError as e:
        print(f'Command failed with exit code {e.returncode}')
        sys.exit(e.returncode)
    except Exception as e:  # noqa: BLE001
        print(str(e))
        sys.exit(1)
