# Сборка минимального контейнера

Готовые архивы находятся в [GitHub Releases](https://github.com/alphazulu/mikrotik-sd-wan/releases). Это Docker-save tar/gzip, пригодные для импорта в RouterOS; не образ диска CHR. Исходный CHR и пакет `container` загружаются у MikroTik отдельно.

## Закреплённый SDK

Сборка проверена на Linux x86_64 с Rust **1.99.1**, musl target libraries и встроенным `rust-lld`. Скрипт использует SDK в локальном `runtime/toolchains`, не меняя системный PATH. Из корня чистой копии:

```sh
mkdir -p runtime/toolchains
curl --proto '=https' --tlsv1.2 -fsSL https://sh.rustup.rs -o runtime/toolchains/rustup-init.sh
RUSTUP_HOME="$PWD/runtime/toolchains/rustup" CARGO_HOME="$PWD/runtime/toolchains/cargo" sh runtime/toolchains/rustup-init.sh -y --no-modify-path --default-toolchain 1.99.1
RUSTUP_HOME="$PWD/runtime/toolchains/rustup" CARGO_HOME="$PWD/runtime/toolchains/cargo" runtime/toolchains/cargo/bin/rustup target add x86_64-unknown-linux-musl aarch64-unknown-linux-musl armv5te-unknown-linux-musleabi
python3 container-controller/build.py
```

Доступ в Интернет требуется для SDK/crates; готовому контроллеру он не нужен. Зависимости закреплены в `Cargo.lock`, Cargo вызывается с `--locked`. Версии иных SDK и хосты иных архитектур отдельной приёмки не проходили.

Для одной архитектуры:

```sh
python3 container-controller/build.py --architectures amd64
```

Все три сборки формируют `dist/container/build-report.json`, tar, gzip и готовые Docker contexts. Скрипт проверяет ELF machine и отсутствие `PT_INTERP`/`PT_DYNAMIC`. Образ содержит один статический бинарник с mode0555 и UID65532:65532; настроек, пароля, shell, toolchain и shared libraries в нём нет.

## Docker и проверка артефактов

Docker daemon не требуется для основной сборки. При необходимости после cross-build можно использовать сгенерированный контекст:

```sh
docker build --platform linux/arm64 -t sdwan-controller:arm64 dist/container/arm64
```

После сборки всех трёх архитектур:

```sh
mkdir -p runtime
python3 tests/container_artifact_acceptance.py
```

Проверка сравнивает SHA256 tar/gzip/ELF/image-config, single-layer rootfs, UID и Docker contexts. Содержимое `dist/` создаётся локально и исключено из Git. Опубликованные release-архивы сопровождаются `SHA256SUMS` и build report.

## Rust unit

```sh
RUSTUP_HOME="$PWD/runtime/toolchains/rustup" CARGO_HOME="$PWD/runtime/toolchains/cargo" CARGO_TARGET_DIR="$PWD/runtime/container-build" RUSTC="$PWD/runtime/toolchains/cargo/bin/rustc" runtime/toolchains/cargo/bin/cargo test --locked --manifest-path container-controller/Cargo.toml
```

Установка контейнера, устройство API и ограничения: [CONTAINER.md](CONTAINER.md).
