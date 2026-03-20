#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
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


NIMBLE_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class PairConfig:
    peripheral_app: str
    central_app: str
    peripheral_ok: str
    central_ok: str
    timeout_s: int = 90


PAIR_CONFIGS: dict[str, PairConfig] = {
    'bleprh_blecent': PairConfig(
        peripheral_app='bleprph',
        central_app='blecent',
        peripheral_ok=r'connection established; status=0',
        central_ok=r'Connection established',
    ),
    'bleprph_blecent': PairConfig(
        peripheral_app='bleprph',
        central_app='blecent',
        peripheral_ok=r'connection established; status=0',
        central_ok=r'Connection established',
    ),
    'ble_cte': PairConfig(
        peripheral_app='ble_cte/ble_periodic_adv_with_cte',
        central_app='ble_cte/ble_periodic_sync_with_cte',
        peripheral_ok=r'Instance \d+ started \(periodic\)',
        central_ok=r'Periodic Sync Established',
    ),
    'ble_cts': PairConfig(
        peripheral_app='ble_cts/cts_prph',
        central_app='ble_cts/cts_cent',
        peripheral_ok=r'connection established; status=0',
        central_ok=r'Connection established',
    ),
    'ble_enc_adv_data': PairConfig(
        peripheral_app='ble_enc_adv_data/enc_adv_data_prph',
        central_app='ble_enc_adv_data/enc_adv_data_cent',
        peripheral_ok=r'connection established; status=0',
        central_ok=r'Connection established',
    ),
    'ble_htp': PairConfig(
        peripheral_app='ble_htp/htp_prph',
        central_app='ble_htp/htp_cent',
        peripheral_ok=r'connection established; status=0',
        central_ok=r'Connection established',
    ),
    'ble_l2cap_coc': PairConfig(
        peripheral_app='ble_l2cap_coc/coc_bleprph',
        central_app='ble_l2cap_coc/coc_blecent',
        peripheral_ok=r'LE COC connected|connection established; status=0',
        central_ok=r'LE COC connected|Connection established',
    ),
    'ble_multi_conn': PairConfig(
        peripheral_app='ble_multi_conn/ble_multi_conn_prph',
        central_app='ble_multi_conn/ble_multi_conn_cent',
        peripheral_ok=r'Connection established\. Handle:',
        central_ok=r'Connection established\. Handle:',
        timeout_s=120,
    ),
    'ble_pawr_adv': PairConfig(
        peripheral_app='ble_pawr_adv/ble_pawr_adv',
        central_app='ble_pawr_adv/ble_pawr_sync',
        peripheral_ok=r'instance \d+ started \(periodic\)',
        central_ok=r'\[Periodic Sync Established\]',
    ),
    'ble_pawr_adv_conn': PairConfig(
        peripheral_app='ble_pawr_adv_conn/ble_pawr_adv_conn',
        central_app='ble_pawr_adv_conn/ble_pawr_sync_conn',
        peripheral_ok=r'\[Connection established\]',
        central_ok=r'\[Connection established\]',
    ),
    'ble_periodic_adv': PairConfig(
        peripheral_app='ble_periodic_adv',
        central_app='ble_periodic_sync',
        peripheral_ok=r'instance \d+ started \(periodic\)',
        central_ok=r'Periodic sync event',
    ),
    'ble_phy': PairConfig(
        peripheral_app='ble_phy/phy_prph',
        central_app='ble_phy/phy_cent',
        peripheral_ok=r'connection established; status=0',
        central_ok=r'Connection established on',
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
        peripheral_ok=r'connection established; status=0',
        central_ok=r'Connection established',
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
    timeout_s: int,
) -> None:
    peripheral_re = re.compile(peripheral_ok)
    central_re = re.compile(central_ok)
    peripheral_hit = False
    central_hit = False

    start = time.monotonic()
    with (
        serial.Serial(peripheral_port, baudrate=baud, timeout=0.2) as peripheral_ser,
        serial.Serial(central_port, baudrate=baud, timeout=0.2) as central_ser,
    ):
        while time.monotonic() - start < timeout_s:
            for role, ser_obj, matcher in (
                ('peripheral', peripheral_ser, peripheral_re),
                ('central', central_ser, central_re),
            ):
                raw = ser_obj.readline()
                if not raw:
                    continue
                line = raw.decode(errors='ignore').rstrip()
                print(f'[{role}] {line}', flush=True)
                if role == 'peripheral' and not peripheral_hit and matcher.search(line):
                    peripheral_hit = True
                    print(f'[match] peripheral regex matched: {peripheral_ok}', flush=True)
                if role == 'central' and not central_hit and matcher.search(line):
                    central_hit = True
                    print(f'[match] central regex matched: {central_ok}', flush=True)

            if peripheral_hit and central_hit:
                print('[result] PASS: both functional checks matched', flush=True)
                return

    missing = []
    if not peripheral_hit:
        missing.append(f'peripheral regex not matched: {peripheral_ok}')
    if not central_hit:
        missing.append(f'central regex not matched: {central_ok}')
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


def resolve_pair_cfg(args: argparse.Namespace, pair_name: str) -> tuple[Path, Path, str, str, int]:
    cfg = PAIR_CONFIGS[pair_name]
    peripheral_rel = args.peripheral_app or cfg.peripheral_app
    central_rel = args.central_app or cfg.central_app
    peripheral_ok = args.peripheral_ok or cfg.peripheral_ok
    central_ok = args.central_ok or cfg.central_ok
    timeout_s = args.timeout or cfg.timeout_s

    peripheral_app = (NIMBLE_DIR / peripheral_rel).resolve()
    central_app = (NIMBLE_DIR / central_rel).resolve()
    if not peripheral_app.is_dir():
        raise SystemExit(f'Peripheral app path does not exist: {peripheral_app}')
    if not central_app.is_dir():
        raise SystemExit(f'Central app path does not exist: {central_app}')
    return peripheral_app, central_app, peripheral_ok, central_ok, timeout_s


def run_single_pair(args: argparse.Namespace, pair_name: str) -> None:
    peripheral_app, central_app, peripheral_ok, central_ok, timeout_s = resolve_pair_cfg(args, pair_name)
    print(f'[pair] {pair_name}')
    print(f'[peripheral_app] {peripheral_app}')
    print(f'[central_app] {central_app}')
    print(f'[peripheral_port] {args.port_peripheral}')
    print(f'[central_port] {args.port_central}')
    print(f'[peripheral_ok] {peripheral_ok}')
    print(f'[central_ok] {central_ok}')
    print(f'[timeout_s] {timeout_s}')

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
        timeout_s=timeout_s,
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
    if args.all_pairs and (args.peripheral_app or args.central_app or args.peripheral_ok or args.central_ok):
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
