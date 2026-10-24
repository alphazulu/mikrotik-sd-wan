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
