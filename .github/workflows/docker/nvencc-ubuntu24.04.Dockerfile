# syntax=docker/dockerfile:1

# RTX 50 シリーズ向けの sm_120 ネイティブコードを生成できる CUDA 12.8 以降を使用する。
# KonomiTV の利用環境は Ubuntu 24.04 前提のため、glibc の後方互換性よりも実環境との一致を優先する。
ARG NVENCC_CUDA_VERSION=12.8.1
FROM nvidia/cuda:${NVENCC_CUDA_VERSION}-devel-ubuntu24.04 AS builder

ARG DEBIAN_FRONTEND=noninteractive
ARG NVENCC_VERSION
ARG NVENCC_CUDA_VERSION
ARG NVENCC_FFMPEG_VERSION

ENV CUDA_PATH=/usr/local/cuda
ENV RUSTUP_HOME=/usr/local/rustup
ENV CARGO_HOME=/usr/local/cargo
ENV PATH=/usr/local/cuda/bin:/usr/local/cargo/bin:${PATH}
ENV BUILD_SCRIPTS_DIR=/opt/build_scripts
ENV FFMPEG_PREFIX=/opt/build_scripts/ffmpeg_dll/build_dll/x64/build
ENV VMAF_PREFIX=/opt/build_scripts/ffmpeg_dll/x64/build
ENV NVENC_HEADER_DIR=/opt/nvenc_headers
ENV AVISYNTH_HEADER_INC=/opt/nvenc_headers/AviSynthPlus-3.7.5/avs_core/include
ENV VAPOURSYNTH_HEADER_INC=/opt/nvenc_headers/vapoursynth-R72/include
ENV VSHIP_HEADER_INC=/opt/nvenc_headers/vship/src

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# NVEncC と、静的リンクする FFmpeg・libplacebo・libvmaf のビルドに必要なツールを導入する。
# CUDA/NPP の開発ライブラリは NVIDIA 公式 devel イメージに含まれているものを使用する。
RUN cuda_package_suffix="$(cut -d. -f1,2 <<<"${NVENCC_CUDA_VERSION}" | tr '.' '-')" \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
      autoconf \
      autogen \
      automake \
      autopoint \
      build-essential \
      bzip2 \
      ca-certificates \
      "cuda-nvrtc-dev-${cuda_package_suffix}" \
      cmake \
      curl \
      gettext \
      git \
      gperf \
      libssl-dev \
      libtool \
      libx11-dev \
      make \
      nasm \
      ninja-build \
      openssl \
      p7zip-full \
      patch \
      pkg-config \
      python3 \
      python3-pip \
      unzip \
      wget \
      xxd \
      xz-utils \
      yasm \
    && python3 -m pip install --break-system-packages --no-cache-dir --upgrade meson \
    && test -f /usr/local/cuda/include/npp.h \
    && test -f /usr/local/cuda/include/nvrtc.h \
    && test -f /usr/local/cuda/include/nvml.h \
    && test -f /usr/local/cuda/include/curand_kernel.h \
    && test -f /usr/local/cuda/lib64/libcudart_static.a \
    && test -f /usr/local/cuda/lib64/libnppif_static.a \
    && test -f /usr/local/cuda/lib64/libnppig_static.a \
    && test -f /usr/local/cuda/lib64/libnppc_static.a \
    && test -f /usr/local/cuda/lib64/libculibos.a \
    && test -f /usr/local/cuda/lib64/stubs/libcuda.so \
    && rm -rf /var/lib/apt/lists/*

# libplacebo のビルドに必要な Rust / cargo-c もコンテナ内に固定して用意する。
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
      | sh -s -- -y --profile minimal \
    && cargo install cargo-c --version '0.10.18+cargo-0.92.0' --locked \
    && cargo cbuild --version

# NVEncC の upstream パッケージと同等に libav*・libplacebo・libvmaf を静的リンクする。
# build_scripts は upstream の既定ブランチを使用するが、FFmpeg は NVEncC と互換性を確認した数値バージョンを先に配置する。
# これにより build_scripts の既定ブランチが未対応の FFmpeg 開発版へ移行しても、NVEncC のビルドを壊さない。
RUN git clone --depth 1 https://github.com/rigaya/build_scripts.git "${BUILD_SCRIPTS_DIR}" \
    && mkdir -p "${BUILD_SCRIPTS_DIR}/ffmpeg_dll/src" \
    && curl -fsSL "https://ffmpeg.org/releases/ffmpeg-${NVENCC_FFMPEG_VERSION}.tar.xz" \
      | tar -xJ -C "${BUILD_SCRIPTS_DIR}/ffmpeg_dll/src" \
    && mv "${BUILD_SCRIPTS_DIR}/ffmpeg_dll/src/ffmpeg-${NVENCC_FFMPEG_VERSION}" \
      "${BUILD_SCRIPTS_DIR}/ffmpeg_dll/src/ffmpeg" \
    && cd "${BUILD_SCRIPTS_DIR}/ffmpeg_dll" \
    && sed -i 's/\r$//' ./build_ffmpeg_dll.sh ./build_libvmaf.sh \
    && if ! grep -Fq '"-Denable_float=true"' ./build_libvmaf.sh; then \
      sed -i '/"-Dbuilt_in_models=true"/a\        "-Denable_float=true"' ./build_libvmaf.sh; \
    fi

# 最も時間のかかる FFmpeg と周辺ライブラリを独立したレイヤーにし、後続工程の修正時に再利用できるようにする。
RUN cd "${BUILD_SCRIPTS_DIR}/ffmpeg_dll" \
    && export NUMBER_OF_PROCESSORS="$(nproc)" \
    && bash ./build_ffmpeg_dll.sh --skip-src-archive --disable-pgo \
    && test -f "${FFMPEG_PREFIX}/lib/pkgconfig/libavutil.pc"

# 現行 build_scripts の Vulkan Loader パッチは Windows 側の SHARED 定義だけを STATIC に変更しており、
# Linux 側では共有ライブラリを削除した後に libvulkan.a が残らないため、Linux 用定義も補正して再リンクする。
# FFmpeg の後段を独立レイヤーにすることで、この upstream 側の修正だけでは全依存を再構築しない。
RUN vulkan_source="${BUILD_SCRIPTS_DIR}/ffmpeg_dll/build_dll/x64/Vulkan-Loader" \
    && sed -i 's/add_library(vulkan SHARED)/add_library(vulkan STATIC)/' "${vulkan_source}/loader/CMakeLists.txt" \
    && grep -F 'add_library(vulkan STATIC)' "${vulkan_source}/loader/CMakeLists.txt" \
    && cmake -S "${vulkan_source}" -B "${vulkan_source}/build" \
      -DCMAKE_INSTALL_PREFIX="${FFMPEG_PREFIX}" \
      -DCMAKE_INSTALL_LIBDIR=lib \
      -DCMAKE_BUILD_TYPE=Release \
      -DBUILD_TESTS=OFF \
      -DUNIX=OFF \
      -DVULKAN_HEADERS_INSTALL_DIR="${FFMPEG_PREFIX}" \
      -DBUILD_WSI_XCB_SUPPORT=OFF \
      -DBUILD_WSI_XLIB_SUPPORT=OFF \
      -DBUILD_WSI_WAYLAND_SUPPORT=OFF \
      -DBUILD_WSI_DIRECTFB_SUPPORT=OFF \
    && cmake --build "${vulkan_source}/build" -j"$(nproc)" \
    && cmake --install "${vulkan_source}/build" \
    && rm -f "${FFMPEG_PREFIX}/lib"/libvulkan.so* \
    && test -f "${FFMPEG_PREFIX}/lib/libvulkan.a"

# libvmaf も FFmpeg とは別レイヤーで構築し、NVEncC 本体の試行錯誤では依存ライブラリを再構築しない。
RUN cd "${BUILD_SCRIPTS_DIR}/ffmpeg_dll" \
    && export NUMBER_OF_PROCESSORS="$(nproc)" \
    && bash ./build_libvmaf.sh --skip-src-archive \
    && test -f "${VMAF_PREFIX}/lib/pkgconfig/libvmaf.pc"

# upstream の Ubuntu 向け配布版と同じ入力・品質評価機能を維持するため、任意機能の公開ヘッダーを用意する。
RUN mkdir -p "${NVENC_HEADER_DIR}" \
    && curl -fsSL https://github.com/AviSynth/AviSynthPlus/archive/refs/tags/v3.7.5.tar.gz \
      | tar -xz -C "${NVENC_HEADER_DIR}" \
    && curl -fsSL https://github.com/vapoursynth/vapoursynth/archive/refs/tags/R72.tar.gz \
      | tar -xz -C "${NVENC_HEADER_DIR}" \
    && curl -fsSL https://codeberg.org/Line-fr/Vship/archive/v5.0.0.tar.gz \
      | tar -xz -C "${NVENC_HEADER_DIR}" \
    && test -f "${AVISYNTH_HEADER_INC}/avisynth_c.h" \
    && test -f "${VAPOURSYNTH_HEADER_INC}/VapourSynth.h" \
    && test -f "${VSHIP_HEADER_INC}/VshipAPI.h"

# NVEncC は数値のリリースタグで取得し、ソース内のバージョン定義との一致も検証する。
RUN git clone --branch "${NVENCC_VERSION}" --depth 1 --recurse-submodules --shallow-submodules \
      https://github.com/rigaya/NVEnc.git /opt/nvencc \
    && source_version="$(sed -n 's/^#define VER_STR_FILEVERSION[[:space:]]*"\([^"]*\)".*$/\1/p' /opt/nvencc/NVEncCore/rgy_version.h | tr -d '\r\n')" \
    && test "${source_version}" = "${NVENCC_VERSION}"

WORKDIR /opt/nvencc

# CUDA 12.8 以上を検出した NVEncC の Meson 設定は、従来 GPU 用コードに加えて
# compute_120 と sm_120 を自動追加する。KonomiTV で使う libav* と upstream 配布版の主要機能も維持する。
RUN VMAFPKG="${VMAF_PREFIX}/lib/pkgconfig" \
    && FFPKG="${FFMPEG_PREFIX}/lib/pkgconfig:${FFMPEG_PREFIX}/lib/x86_64-linux-gnu/pkgconfig" \
    && export PKG_CONFIG_PATH="${VMAFPKG}:${FFPKG}" \
    && meson setup ./build . \
      --buildtype=release \
      -Db_lto=true \
      -Denable_libplacebo=enabled \
      -Dlibplacebo_static=true \
      -Denable_vmaf=enabled \
      -Dlibvmaf_static=true \
      -Dcpp_args="['-I${AVISYNTH_HEADER_INC}','-I${VAPOURSYNTH_HEADER_INC}','-I${VSHIP_HEADER_INC}']" \
    && grep -F '#define LIBVMAF_STATIC_CUDA_LINK 1' ./build/rgy_config.h \
    && grep -F '#define ENABLE_LIBVSHIP 1' ./build/rgy_config.h \
    && meson compile -C ./build -j"$(nproc)"

COPY .github/workflows/scripts/verify_nvencc.sh /usr/local/bin/verify_nvencc.sh

# GPU のないビルド環境でも --version とオプション検査を実行できるよう、CUDA Driver API の stub を使う。
# そのうえで fatbin を直接検査し、sm_120 が欠落した成果物を配布工程へ進めない。
RUN mkdir -p /tmp/nvenc-cuda-stubs \
    && ln -sf /usr/local/cuda/targets/x86_64-linux/lib/stubs/libcuda.so /tmp/nvenc-cuda-stubs/libcuda.so.1 \
    && export LD_LIBRARY_PATH="/tmp/nvenc-cuda-stubs:/usr/local/cuda/targets/x86_64-linux/lib/stubs" \
    && /usr/local/bin/verify_nvencc.sh ./build/nvencc "${NVENCC_VERSION}" \
    && ./check_options.py -exe ./build/nvencc \
    && mkdir -p /artifact \
    && cp ./build/nvencc /artifact/NVEncC.elf \
    && cp ./NVEnc_license.txt /artifact/License.txt \
    && { \
      ./build/nvencc --version; \
      echo "CUDA source version: ${NVENCC_CUDA_VERSION}"; \
      echo "FFmpeg source version: ${NVENCC_FFMPEG_VERSION}"; \
      echo "NVEnc source revision: $(git rev-parse HEAD)"; \
      echo "build_scripts source revision: $(git -C "${BUILD_SCRIPTS_DIR}" rev-parse HEAD)"; \
      sha256sum ./build/nvencc; \
    } > /artifact/BuildInfo.txt

FROM scratch AS artifact
COPY --from=builder /artifact/ /
