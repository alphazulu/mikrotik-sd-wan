# Индекс документации

Русский | [English](README.en.md)

Готовность выпуска описана в текущем статусе. Проектные документы и отчёты
этапов имеют собственные границы; их числа не складываются как уникальные тесты.
В каждом руководстве есть переключение языка; ссылки ниже ведут на русские версии.

## Начать здесь

- [Возможности и быстрый старт](../README.md)
- [Текущее состояние кандидата и проверок](CURRENT-STATUS.md)
- [План развития](../ROADMAP.md)
- [Правила документации RU/EN](LANGUAGES.md)
- [Конфигурации и учётные данные](../SECURITY.md)

## Установка и эксплуатация

- [Конфигуратор: от API до установки](CONFIGURATOR-WIZARD.md)
- [Платформа, пакеты, device-mode и носитель](CONFIGURATOR-PROVISIONING.md)
- [Существующие проверки готовности](CONFIGURATOR-CHECKS.md)
- [Структура JSON и примеры](CONFIGURATION.md)
- [Защищённая установка и восстановление](DEPLOYMENT.md)
- [Порядок эксплуатации и восстановления](OPERATIONS.md)
- [API, место и архивы](MAINTENANCE.md)
- [Диагностика и объяснение выбора](DIAGNOSTICS.md)
- [Переход со сторонних mangle](MIGRATION.md)
- [Нативный контроллер RouterOS](NATIVE-CONTROLLER.md)

## Маршрутизация и WAN

- [Маркировка, симметрия и conntrack](DATAPLANE.md)
- [Static, DHCP-client и PPPoE](DYNAMIC-WAN.md)
- [LTE и APN](LTE.md)
- [Клиенты, адресные списки и L3/L4](POLICIES.md)
- [Совместимость существующих OSPF/VPN](OSPF.md)
- [Существующие VPN как WAN](VPN-EGRESS.md)
- [Филиальный overlay и ключи](OVERLAY-GUI.md)
- [DNS bootstrap для endpoints](DNS-BOOTSTRAP.md)
- [Исчезающие записи conntrack](CONNTRACK-EXPIRY.md)

## Контейнер и статистика

- [Обзор Rust/scratch](../container-controller/README.md)
- [Установка и ограничения контейнера](CONTAINER.md)
- [Сборка и проверка точных CI-артефактов](BUILD.md)
- [Обязательное unit-покрытие](CONTAINER-TESTING.md)
- [Настройка работающего web и RAM-истории](STATISTICS.md)

## Лаборатория и методика

- [Лаборатория QEMU/CHR](LAB.md)
- [Порядок запуска проверок](TESTING.md)
- [Длительная приёмка](NETWORK-SOAK.md)
- [Методика сравнения производительности](PERFORMANCE-PLAN.md)
- [Внешние генераторы и наблюдатели](../labtools/README.md)
- [Изолированный x86 DUT](../labtools/DUT-ADAPTER.md)
- [Обзор USB LTE-эмулятора](../lte-rndis-emu/README.md)
- [Запуск LTE-эмулятора](../lte-rndis-emu/USAGE.md)
- [Лаборатория x86 с LTE](../lte-rndis-emu/X86-LAB.md)

## Проектные документы

- [Сетевая итерация и её проверки](NEXT-NETWORK-PLAN.md)
- [Архитектура филиального overlay](OVERLAY-DESIGN.md)
- [Усиление нативного overlay](OVERLAY-NATIVE-HARDENING.md)
- [План VPN WAN](VPN-EGRESS-PLAN.md)
- [Первоначальная архитектура статистики](STATISTICS-DESIGN.md)
- [Следующая итерация статистики: проект](STATISTICS-NEXT.md)
- [Первоначальный план контейнера](CONTAINER-PLAN.md)
- [Первоначальный обзор SD-WAN](SD-WAN.md)
- [Реализация LTE resolver и отката](LTE-IMPLEMENTATION.md)
- [План полей управления модемом](../lte-rndis-emu/MODEM-CONTROL-PLAN.md)

## Отчёты отдельных этапов

- [Результаты сравнения и ограничения](PERFORMANCE-RESULTS.md)
- [Сетевые проверки контейнера](NETWORK-CONTAINER-VALIDATION.md)
- [Первоначальная приёмка контейнера](CONTAINER-VALIDATION.md)
- [Приёмка статистики](STATISTICS-VALIDATION.md)
- [Нативные SLA-сценарии](NATIVE-VALIDATION.md)
- [Соединения и симметрия](CONNECTIONS-VALIDATION.md)
- [Динамические WAN](DYNAMIC-WAN-VALIDATION.md)
- [LTE/APN](LTE-VALIDATION.md)
- [Политики и диагностика](POLICIES-VALIDATION.md)
- [VPN WAN](VPN-EGRESS-VALIDATION.md)
- [GUI и мастер](WIZARD-VALIDATION.md)
- [API, архивы и ресурсы](RESOURCE-VALIDATION.md)
- [Исходная маршрутизация стенда](VALIDATION.md)
- [Внешние инструменты](../labtools/VALIDATION.md)
- [LTE-эмулятор](../lte-rndis-emu/VALIDATION.md)

Сырые runtime-отчёты, учётные данные и снимки устройств остаются локальными.
