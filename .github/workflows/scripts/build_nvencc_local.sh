#!/usr/bin/env bash

set -euo pipefail

repository_root="$(git rev-parse --show-toplevel)"
workflow_file="${repository_root}/.github/workflows/build_thirdparty.yaml"
dockerfile="${repository_root}/.github/workflows/docker/nvencc-ubuntu24.04.Dockerfile"
build_root="${repository_root}/.build/NVEncC"
cache_dir="${build_root}/cache"
next_cache_dir="${build_root}/cache-next"
logs_dir="${build_root}/logs"
output_dir="${build_root}/output"
next_output_dir="${build_root}/output-next"
builder_name='konomitv-nvencc'

# 削除・置換するディレクトリをリポジトリ内の専用ビルド領域に限定する。
if [[ "${build_root}" != "${repository_root}/.build/NVEncC" ]]; then
    echo "Unexpected NVEncC build directory: ${build_root}" >&2
    exit 1
fi

# バージョンは GitHub Actions と同じ定義から取得し、ローカル用スクリプトとの二重管理を避ける。
nvencc_version="$(sed -n "s/^  NVENCC_VERSION: '\([^']*\)'$/\1/p" "${workflow_file}")"
nvencc_cuda_version="$(sed -n "s/^  NVENCC_CUDA_VERSION: '\([^']*\)'$/\1/p" "${workflow_file}")"
nvencc_ffmpeg_version="$(sed -n "s/^  NVENCC_FFMPEG_VERSION: '\([^']*\)'$/\1/p" "${workflow_file}")"
if [[ -z "${nvencc_version}" || -z "${nvencc_cuda_version}" || -z "${nvencc_ffmpeg_version}" ]]; then
    echo 'Failed to resolve NVEncC build versions from build_thirdparty.yaml.' >&2
    exit 1
fi

mkdir -p "${cache_dir}" "${logs_dir}"
rm -rf "${next_cache_dir}" "${next_output_dir}"

build_timestamp="$(date '+%Y%m%d-%H%M%S')"
build_log="${logs_dir}/build-${build_timestamp}.log"

{
    echo "Building NVEncC ${nvencc_version} with CUDA ${nvencc_cuda_version} and FFmpeg ${nvencc_ffmpeg_version}."
    echo "Build log: ${build_log}"
} | tee "${build_log}"

# local キャッシュの import/export に対応する専用 docker-container ビルダーを作成し、次回以降も再利用する。
if ! docker buildx inspect "${builder_name}" >>"${build_log}" 2>&1; then
    docker buildx create --name "${builder_name}" --driver docker-container >>"${build_log}" 2>&1
fi
builder_driver="$(docker buildx inspect "${builder_name}" | sed -n 's/^Driver:[[:space:]]*//p')"
if [[ "${builder_driver}" != 'docker-container' ]]; then
    echo "Buildx builder ${builder_name} uses unsupported driver: ${builder_driver}" | tee -a "${build_log}" >&2
    exit 1
fi
docker buildx inspect "${builder_name}" --bootstrap 2>&1 | tee -a "${build_log}"

# 前回成功時にエクスポートした BuildKit キャッシュがあれば再利用する。
cache_from_args=()
if [[ -f "${cache_dir}/index.json" ]]; then
    cache_from_args+=(--cache-from "type=local,src=${cache_dir}")
fi

set +e
docker buildx build \
    --builder "${builder_name}" \
    --progress plain \
    --target artifact \
    --build-arg "NVENCC_VERSION=${nvencc_version}" \
    --build-arg "NVENCC_CUDA_VERSION=${nvencc_cuda_version}" \
    --build-arg "NVENCC_FFMPEG_VERSION=${nvencc_ffmpeg_version}" \
    "${cache_from_args[@]}" \
    --cache-to "type=local,dest=${next_cache_dir},mode=max" \
    --output "type=local,dest=${next_output_dir}" \
    --file "${dockerfile}" \
    "${repository_root}" 2>&1 | tee -a "${build_log}"
build_status="${PIPESTATUS[0]}"
set -e

if [[ "${build_status}" -ne 0 ]]; then
    echo "NVEncC build failed. See ${build_log}" >&2
    exit "${build_status}"
fi

# Dockerfile 内の検証に加えてローカル出力の必須ファイルも確認し、不完全な成果物への置換を防ぐ。
if [[ ! -x "${next_output_dir}/NVEncC.elf" || ! -f "${next_output_dir}/BuildInfo.txt" ]]; then
    echo "NVEncC build output is incomplete. See ${build_log}" >&2
    exit 1
fi

# 成功したビルドのキャッシュだけを次回用として確定し、不完全なキャッシュへの置換を避ける。
rm -rf "${cache_dir}"
mv "${next_cache_dir}" "${cache_dir}"
rm -rf "${output_dir}"
mv "${next_output_dir}" "${output_dir}"

echo "NVEncC build completed: ${output_dir}/NVEncC.elf"
