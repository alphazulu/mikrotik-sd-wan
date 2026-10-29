# Static, DHCP-client, PPPoE и LTE WAN

Русский | [English](DYNAMIC-WAN.en.md)

Здесь описаны четыре способа физической адресации. Настроенные VPN тоже являются
WAN в общей политике; их транспорт описан в [VPN-EGRESS.md](VPN-EGRESS.md).

Контроллер, установщик и GUI поддерживают четыре способа адресации IPv4. LTE/APN добавлен отдельной итерацией: [LTE.md](LTE.md). Приведённые ниже 79/78 — историческая приёмка первых трёх типов. Интеграция и приёмка на CHR 7.24.5 завершены: 79 unit и 78 приёмочных проверок, включая полный mixed lifecycle и аварийное восстановление. Windows GUI также прошёл регрессию. Итоги: [DYNAMIC-WAN-VALIDATION.md](DYNAMIC-WAN-VALIDATION.md).

## Конфигурация

У каждого WAN есть `kind`: `static`, `dhcp`, `pppoe` или `lte`. Отсутствующий `kind` означает `static`, старые JSON совместимы.

- `static`: обязательны `interface`, назначенный статический `address` и `gateway`. Маршрут закрепляется как `IP%interface@main`.
- `dhcp`: `interface` — интерфейс существующего DHCP-client (Ethernet или VLAN). Поля `address` и `gateway` отсутствуют или пусты; снимок аренды отвергается валидатором.
- `pppoe`: `interface` — имя существующего логического PPPoE-client, например `pppoe-out1`; физический родитель не является этим WAN. Адрес и шлюз в JSON не задаются.

- `lte`: `interface` — native LTE, `apn_profile` — назначенный ему существующий APN-профиль; адрес/шлюз не задаются. Automatic default управляется через `/interface/lte/apn`, а не DHCP-client. Подробности и ограничения — [LTE.md](LTE.md).

Остальные параметры WAN одинаковы: уникальное имя, probe_table, icmp_target, набор прикладных probes. Приоритеты и клиентские prefer/strict политики задаются обычным способом. DHCP/PPPoE клиент, его провайдерские credentials и NAT должны существовать заранее. Конфигуратор не создаёт клиент провайдера и не читает его пароль.

Мастер получает тип и текущие параметры через API. Для dynamic WAN адрес/шлюз доступны только для просмотра и не копируются в конфигурацию. Включённый клиент можно выбрать без текущей аренды/сессии. Текущий стандартный экспорт содержит JSON и 11 RSC, включая `sdwan-links.rsc`.

## Работа на RouterOS

`sdwanResolveWANs` читает фактическую аренду DHCP либо согласованный динамический /32 PPPoE. На CHR 7.24.5 `pppoe-client monitor once as-value` в скрипте возвращает nil; используется назначенный address и network=peer. Для DHCP берётся настоящий dynamic default из выделенной таблицы, включая правила option121; отсутствие единственного default делает канал unavailable. DHCP next hop — `IP%interface@main`, PPPoE — логический интерфейс.

Установщик сохраняет исходные routing options провайдерских клиентов. DHCP default изолируется в probe_table; PPPoE automatic default отключается. Поэтому автоматический маршрут провайдера не может обойти SLA через main. Существующие DHCP lease-script, PPP credentials, профиль и DNS options не переписываются. Удалённый из SD-WAN DHCP клиент остаётся без automatic default до отката к исходному, чтобы не вернуть обход SLA.

`sdwanReconcileWANs` реагирует на изменение ready/address/gateway/interface. Он закрывает затронутые policy routes/classifiers, удаляет conntrack точных policy marks этого WAN и входящих/router сессий этого WAN, обновляет source pins, маршруты и probes. Другие WAN и их входящие API-сессии сохраняются. Старые probe tuples истекают отдельно.

Перед запуском проб проверяется готовность маршрута и mangle bindings. Новые Netwatch объекты создаются с валидным source и задержкой первого запуска 3 секунды. На CHR запуск сразу после изменения правил воспроизводил неправильную метку первого ICMP tuple и NAT через main WAN; захват QEMU подтвердил выход через WAN1. С задержкой ICMP метки и фактический путь стали правильными. Контроллер ждёт нового поколения всех probes, полного окна измерения, recover_windows и hold-down; старые метрики не могут сразу открыть канал. Reconciler сам не включает policy routes.

При стабильных параметрах переписывания конфигурации нет. Статус публикует kind, текущие address/gateway/route_gateway, carrier, link_ready, link_reason и warming. Исполнение полностью локальное: GUI и Python после установки не нужны.

Откат к исходному возвращает сохранённые add-default-route/default-route-tables только при совпадении identity клиента и управляемых значений. Ручные изменения оператора не затираются. Аварийный watchdog возвращает полный зашифрованный binary backup, файлы и перезагружает CHR; подробности в [DEPLOYMENT.md](DEPLOYMENT.md).

## Ограничения и проверки

Совпадающие первичные WAN IP закрываются: для их поддержки нужна отдельная VRF изоляция. Текущий контракт не реализует IPv6, создание PPPoE/DHCP клиентов или перенос NAT TCP-сессии между публичными IP. LTE reconnect/new-IP реализован; радиорегистрация и конкретные модемы требуют аппаратной проверки. Постоянные alias IP учитываются при установке; временный lease не становится alias pin.

Исторический unit-набор до LTE: 79 PASS; LTE расширяет его до 109 проверок. Компонентные resolver/reconciler и полный mixed lifecycle проверены скриптами `tests/link_resolver_acceptance.py`, `tests/link_reconcile_acceptance.py`, `tests/dynamic_wan_acceptance.py`. Результаты сохранены в `runtime/dynamic-final-validation.json` и связанных отчётах. Исторические static отчёты не подтверждают dynamic lifecycle.

## Документация MikroTik

- [DHCP Client](https://manual.mikrotik.com/docs/network-management/dhcp/client/): аренда, route tables, option121.
- [Netwatch](https://manual.mikrotik.com/docs/diagnostics-monitoring-and-troubleshooting/netwatch/): source address, start-delay и статистика ICMP.
- [Scripting](https://manual.mikrotik.com/docs/developer-guides/scripting/): JSON десериализация с `json.no-string-conversion`. Она используется во всём native пакете, чтобы строковые yes/no и IP не меняли тип и не ломали восстановление routing options.
- [PPPoE monitor](https://manual.mikrotik.com/docs/cli-reference/interface/pppoe-client/monitor/): параметры сессии; формат выполнения проверен отдельно на целевой версии.

Историческая общая приёмка после исходной LTE-итерации: 109 unit и 105 проверок CHR, Windows GUI и чистый итоговый стенд. См. [LTE-VALIDATION.md](LTE-VALIDATION.md). Актуальные проверки кандидата — [CURRENT-STATUS.md](CURRENT-STATUS.md).


Локальные `runtime/` отчёты, учётные данные и снимки устройств не входят в
репозиторий. Методика повторения проверок: [TESTING.md](TESTING.md).
