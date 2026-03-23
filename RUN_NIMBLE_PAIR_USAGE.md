# NimBLE Pair Runner Usage Guide

This guide documents how to use:

- `examples/bluetooth/nimble/run_nimble_pair.py`

The script automates:

1. Building peripheral + central example apps
2. Flashing each app to a different board
3. Monitoring both UART logs
4. Declaring pass/fail from pair-specific functional log patterns

It supports two validation modes:

- First-match mode: pass as soon as required regex matches are seen.
- Full-window soak mode: monitor for the entire timeout and pass only if traffic continues.

## 1. Prerequisites

- ESP-IDF environment exported:
  - `source export.sh`
- Python dependency:
  - `pip install pyserial`
- Two DUTs connected over serial (for example `/dev/ttyUSB0` and `/dev/ttyUSB1`)
- Correct target known (`esp32`, `esp32c3`, `esp32c6`, etc.)

Path resolution behavior:

- The script resolves NimBLE examples from:
  - `$IDF_PATH/examples/bluetooth/nimble`
- You can run the script from any current working directory.
- `IDF_PATH` must be set (via `source export.sh`).

## 2. List Supported Pairs

```bash
python examples/bluetooth/nimble/run_nimble_pair.py --list-pairs
```

This prints all pair keys and corresponding peripheral/central apps.

## 3. Run One Pair

Example (`bleprph` + `blecent` on ESP32):

```bash
python examples/bluetooth/nimble/run_nimble_pair.py \
  --pair bleprph_blecent \
  --target esp32 \
  --port-peripheral /dev/ttyUSB0 \
  --port-central /dev/ttyUSB1
```

Notes:

- Alias `bleprh_blecent` is also accepted.
- By default this will build + flash both apps, then monitor logs.

## 4. Run All Applicable Pairs for a Target

```bash
python examples/bluetooth/nimble/run_nimble_pair.py \
  --all-pairs \
  --target esp32c3 \
  --port-peripheral /dev/ttyUSB0 \
  --port-central /dev/ttyUSB1
```

Behavior:

- Runs every predefined pair that supports the target.
- Prints per-pair status and final summary (`passed`, `failed`).
- Returns non-zero exit code if any pair fails.

## 5. Target Filtering Rule (Important)

For `--all-pairs`, and also single `--pair` validation, the script reads each app's `README.md` first line table:

- `| Supported Targets | ... |`

A pair is runnable only if:

- target is listed in peripheral app README
- target is listed in central app README

If either side does not list the target, that pair is skipped in `--all-pairs`, or rejected in single-pair mode.

## 6. Skip Build/Flash (Log-Only Validation)

Use this when both boards are already flashed:

```bash
python examples/bluetooth/nimble/run_nimble_pair.py \
  --pair bleprph_blecent \
  --port-peripheral /dev/ttyUSB0 \
  --port-central /dev/ttyUSB1 \
  --skip-build-flash
```

In this mode:

- no `idf.py build`
- no `idf.py flash`
- only UART monitoring and pass/fail checks

## 7. All CLI Options

```text
--list-pairs
--pair <pair_name>
--all-pairs
--target <idf_target>
--port-peripheral <port>
--port-central <port>
--baud <int>                 (default: 115200)
--timeout <seconds>          (override pair default timeout)
--build-root <path>          (default: /tmp/nimble_pair_builds)
--clean-build
--skip-build-flash
--peripheral-app <rel_path>  (single pair only)
--central-app <rel_path>     (single pair only)
--peripheral-ok <regex>      (single pair only)
--central-ok <regex>         (single pair only)
```

Notes:

- `--timeout` overrides the pair default timeout.
- In full-window soak mode, `--timeout` is the soak duration.

Restrictions:

- Use either `--pair` or `--all-pairs`, not both.
- `--target` is mandatory unless `--skip-build-flash` is used.
- `--all-pairs` requires `--target`.
- Custom app/regex override options are allowed only with `--pair`.

## 8. Build Output Location

Build artifacts are stored out-of-tree under:

- `/tmp/nimble_pair_builds`

Per app/target build directory pattern:

- `<build_root>/<app_name>_<target>`

The script also uses a build-local `sdkconfig` in that directory to avoid conflicts with checked-in example `sdkconfig` files.

## 9. Typical Workflows

1. Full end-to-end validation of one pair:
```bash
python examples/bluetooth/nimble/run_nimble_pair.py \
  --pair ble_spp \
  --target esp32c6 \
  --port-peripheral /dev/ttyUSB0 \
  --port-central /dev/ttyUSB1
```

2. Re-check behavior without reflashing:
```bash
python examples/bluetooth/nimble/run_nimble_pair.py \
  --pair ble_spp \
  --port-peripheral /dev/ttyUSB0 \
  --port-central /dev/ttyUSB1 \
  --skip-build-flash
```

3. Qualification sweep for one chip:
```bash
python examples/bluetooth/nimble/run_nimble_pair.py \
  --all-pairs \
  --target esp32h2 \
  --port-peripheral /dev/ttyUSB0 \
  --port-central /dev/ttyUSB1 \
  --clean-build
```

4. Force a 120s soak for one pair:
```bash
python examples/bluetooth/nimble/run_nimble_pair.py \
  --pair ble_cte \
  --target esp32c5 \
  --port-peripheral /dev/ttyUSB0 \
  --port-central /dev/ttyUSB1 \
  --timeout 120
```

## 10. Soak-Mode Pairs (Current Defaults)

The following pairs are configured for full-window soak by default:

- `ble_cte`
  - timeout: `60s`
  - central regex: `IQ Report \| Sync Handle:`
  - requires continuing matches across window (gap limit 10s)
- `ble_pawr_adv`
  - timeout: `60s`
  - central regex: `\[Periodic Adv Report\]`
  - requires continuing matches across window (gap limit 10s)
- `ble_pawr_adv_conn`
  - timeout: `60s`
  - peripheral regex: `\[Response\] subevent:`
  - central regex: `\[Periodic Adv Report\]`
  - requires continuing central matches across window (gap limit 10s)

## 11. Troubleshooting

1. `invalid choice` for `--pair`
- Run `--list-pairs` and use exact key.

2. `Pair ... is not supported for target ... per app README Supported Targets`
- Choose a supported target, or a different pair.

3. `could not open port ...`
- Verify port names and access permissions.
- Ensure no other monitor process is holding the port.

4. Build fails because environment is not set
- Re-run `source export.sh` in the shell.

5. Timeout / regex not matched
- Increase `--timeout`.
- Check logs and use `--peripheral-ok` / `--central-ok` for temporary custom validation.
- For soak-mode pairs, a failure can also mean:
  - central matches were too sparse, or
  - central matches stalled longer than the configured gap limit.

## 12. Exit Codes

- `0`: success
- non-zero: build/flash failure, serial/monitor failure, or validation failure
