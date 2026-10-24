# Руководства MikroTik SD-WAN

## Установка и настройка

- [Быстрый старт](../README.md) — возможности, требования, GUI и CLI.
- [Конфигуратор](CONFIGURATOR-WIZARD.md) — API, выбор интерфейсов, генерация и план.
- [Конфигурация JSON](CONFIGURATION.md) — структура, SLA, WAN, политики и примеры.
- [Нативный контроллер](NATIVE-CONTROLLER.md) — файлы, команды и работа RouterOS.
- [Защищённая установка](DEPLOYMENT.md) — scheduler, backup, ACK и восстановление.
- [API и архивы установки](MAINTENANCE.md) — точечный поиск, минимум записей, место и retention.
- [Диагностика](DIAGNOSTICS.md) — состояние, история и объяснение выбора канала.

## Маршрутизация и WAN

- [Маркировка и conntrack](DATAPLANE.md) — симметричные WAN/DNAT-ответы и переключение.
- [Static, DHCP-client и PPPoE](DYNAMIC-WAN.md) — адреса, события и прогрев SLA.
- [LTE/APN](LTE.md) — существующий профиль, автоматические маршруты и ограничения.
- [Реализация LTE](LTE-IMPLEMENTATION.md) — resolver, installer и rollback.
- [Группы и правила клиентов](POLICIES.md) — адреса, VLAN/L3, протоколы, порты и приоритет.
- [OSPF/VPN](OSPF.md) — локальные и филиальные сети, маркировки и маршруты.
- [Архитектура и SLA](SD-WAN.md) — ранний проектный обзор; текущие границы см. в README.

## Локальный Rust-контейнер

- [Подготовка и запуск](CONTAINER.md) — пакет, veth, API, GUI/CLI и heartbeat.
- [Сборка](BUILD.md) — закреплённый Rust SDK, musl, три архитектуры и scratch.
- [Завершённый план backend](CONTAINER-PLAN.md).
- [Проект RAM-статистики и web](STATISTICS-DESIGN.md) — опциональный режим, бюджет и ограничения; сервер ещё не реализован.
- [Приёмка и расход ресурсов](CONTAINER-VALIDATION.md).

## Проверки

- [Лаборатория CHR](LAB.md) и [порядок тестирования](TESTING.md).
- [Итоговая контейнерная приёмка](CONTAINER-VALIDATION.md) — текущие 155 Python / 9 Rust / 120 CHR.
- [Нативные SLA-сценарии](NATIVE-VALIDATION.md).
- [Соединения и симметрия](CONNECTIONS-VALIDATION.md).
- [Динамические WAN](DYNAMIC-WAN-VALIDATION.md).
- [LTE/APN](LTE-VALIDATION.md).
- [Политики и диагностика](POLICIES-VALIDATION.md).
- [GUI и мастер](WIZARD-VALIDATION.md).
- [Исходная маршрутизация стенда](VALIDATION.md).

Исторические числа описывают отдельные этапы и не складываются в число уникальных тестов. Файлы `runtime/`, упоминаемые в отчётах, создаются локально и не публикуются вместе с исходниками.

[План развития](../ROADMAP.md) · [Хранение секретов](../SECURITY.md)
