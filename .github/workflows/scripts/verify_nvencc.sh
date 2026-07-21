#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 2 ]]; then
    echo 'Usage: verify_nvencc.sh <NVEncC binary> <expected version>' >&2
    exit 2
fi

nvencc_binary="$1"
expected_version="$2"

if [[ ! -x "${nvencc_binary}" ]]; then
    echo "NVEncC binary is not executable: ${nvencc_binary}" >&2
    exit 1
fi

# 表示上の NVEncC バージョンを検査し、別の upstream 成果物が混ざるのを防ぐ。
nvencc_version="$("${nvencc_binary}" --version)"
echo "${nvencc_version}"
grep -F "NVEnc (x64) ${expected_version}" <<<"${nvencc_version}" >/dev/null

# RTX 50 シリーズで初回起動時の PTX JIT を発生させないため、sm_120 のネイティブ cubin を必須にする。
sm_120_count="$(cuobjdump --list-elf "${nvencc_binary}" | grep -c 'sm_120' || true)"
if [[ "${sm_120_count}" -eq 0 ]]; then
    echo 'NVEncC does not contain an sm_120 native cubin.' >&2
    exit 1
fi
echo "sm_120 cubins: ${sm_120_count}"

# 予期せぬ共有ライブラリ依存は KonomiTV のスタンドアローン配布を壊すため、その場で失敗させる。
ldd_output="$(ldd "${nvencc_binary}")"
echo "${ldd_output}"
if grep -F '=> not found' <<<"${ldd_output}" | grep -Fv 'libcuda.so.1 => not found' >/dev/null; then
    echo 'Unexpected missing shared libraries were found.' >&2
    exit 1
fi
if readelf -d "${nvencc_binary}" | grep -F '(NEEDED)' | grep -E 'libav|libplacebo|libvmaf|libvulkan|libnpp|libcudart' >/dev/null; then
    echo 'A library that must be statically linked was found in DT_NEEDED.' >&2
    exit 1
fi
