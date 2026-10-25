# Минимальный локальный SD-WAN controller

Rust/musl, `FROM scratch`, один исполняемый файл, без shell/дистрибутива/БД.
Конфигурация и пароль — отдельные mounts read-only. Controller работает на
самом MikroTik; RouterOS измеряет SLA, применяет решения и держит нативный резерв.

[Установка, JSON/GUI, сборка и ограничения](../docs/CONTAINER.md).
[Приёмка](../docs/CONTAINER-VALIDATION.md).

Из корня проекта: `python3 container-controller/build.py`.
Архивы, SHA256 и готовые Docker build contexts: `dist/container/`.
Для запуска не нужен внешний Docker daemon. Физический ARM ещё не проверен.

Приёмка завершена; результаты — `runtime/container-final-validation.json`. Рабочий MikroTik не изменялся.


Optional `web` feature (0.2.0): separate scratch image and entrypoint, bounded RAM
history/events and embedded read-only UI, runtime disabled by default. No database,
access logs, CDN or automatic disk checkpoints. See [statistics guide](../docs/STATISTICS.md).

Unit coverage is mandatory on every change, before building either profile.
See [coverage commands and CI gates](../docs/CONTAINER-TESTING.md).
