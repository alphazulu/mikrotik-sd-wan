# Реализация LTE/APN

Русский | [English](LTE-IMPLEMENTATION.en.md)

Контроллер, installer, rollback, API discovery и GUI поддерживают `kind=lte`. Пользовательская инструкция — [LTE.md](LTE.md). Рабочий MikroTik не изменялся; совместимость с существующими OSPF/VPN-политиками требует [отдельного согласования](OSPF.md).

## Контракт и API

`sdwan/wan.py` и `sdwan/config.py` принимают static/dhcp/pppoe/lte. Для LTE обязательны имя логического интерфейса и `apn_profile`: ссылка на уже назначенный профиль. Снимки address/gateway не допускаются. Discovery определяет LTE по native inventory, читает только разрешённые поля интерфейса/APN и не запрашивает credentials, PIN или идентификаторы SIM. GUI показывает текущий адрес и профиль, а экспорт хранит только ссылку на профиль. Не зарегистрированный, но включённый интерфейс можно выбрать заранее.

`sdwan/lte.py` проверяет ровно один routed IPv4 APN, совпадение ожидаемого профиля и отсутствие passthrough. Общий профиль допустим только при совместном управлении всеми использующими его интерфейсами, включая отключённые. Неизвестные routing flags и недостаточные права чтения не принимаются за безопасный default.

## RouterOS

Все функции включены в существующий `native/sdwan-links.rsc`; на этапе исходной LTE-итерации использовалась версия библиотеки 4. Текущий стандартный пакет содержит 11 RSC и JSON. Production reader сначала читает `apn-profiles` целевой 7.24.5, затем singular `apn-profile` новых версий. `sdwanLTENormalizeProfiles` сохраняет native массивы и нормализует имена/ID профилей.

Resolver требует running/enabled interface, правильный APN без automatic default и единственный назначенный динамический IPv4. Source — текущий адрес; raw-IP использует LTE interface как gateway, RNDIS/HiLink — шлюз внутренней bound DHCP lease, закреплённый за интерфейсом. Reconciler обновляет bindings, source pins, routes и Netwatch при disconnect/new-IP; старые метрики не открывают WAN. Возврат требует свежего поколения probes, recover windows и hold-down. Очистка conntrack ограничена затронутыми метками.

Installer отдельно обрабатывает LTE, не направляя его в DHCP/PPPoE ветку. `sdwanLTEAPNCapture` проверяет владение и сохраняет routing metadata без credentials. `backup.lte_apns` содержит одну исходную запись на профиль; baseline записывается на диск до `sdwanLTEAPNApply`. Перед mutation проверяются exact identity и ожидаемый текущий flag. Если automatic default уже выключен, setter не выполняется. Reapply сохраняет исходный baseline. Retired APN остаётся без automatic default до явного baseline rollback.

`sdwanLTEAPNRestore` возвращает только принадлежащий установке `add-default-route`, проверяя identity, управляемое значение и отсутствие новых невыбранных пользователей профиля. Ручные изменения пропускаются с предупреждением. Distance, DNS, APN оператора, authentication, SIM и credentials не меняются. При `add-default-route=no` RouterOS скрывает distance; его внутреннее значение сохраняется, обратной записи guessed distance нет. Аварийный watchdog использует полный binary restore с перезагрузкой, как описано в [DEPLOYMENT.md](DEPLOYMENT.md).

## Проверка

`tests/lte_apn_acceptance.py` использует настоящее меню APN CHR. В первичном наборе `tests/lte_native_acceptance.py`, `tests/lte_acceptance.py` и `tests/lte_protection_acceptance.py` проверяются resolver, трафик, SLA failover, переподключение, baseline и аварийный restore. Только в том тестовом пакете подменяется reader LTE inventory: настоящая PPP point-to-point линия служит data plane, а APN и весь RouterOS controller исполняются реально. Позже отдельно проверен USB RNDIS на x86. Production test-mode отсутствует. Физический модем, SIM и радиорегистрация требуют аппаратной приёмки.

Первоначальная последовательная LTE-регрессия завершена: 109 unit и 105 проверок CHR. Сводка — [LTE-VALIDATION.md](LTE-VALIDATION.md), `runtime/lte-final-validation.json` и `runtime/lte-regression-suites.json`; [текущий статус](CURRENT-STATUS.md) описан отдельно. Подробные внутренние журналы и снимки устройств в публичную поставку не включены.

## Источники

- [LTE/5G](https://manual.mikrotik.com/docs/mobile-networking/lte-5g/) — параметры маршрутизации APN, routed/passthrough.
- [APN CLI](https://manual.mikrotik.com/docs/cli-reference/interface/lte/apn/) — отдельное меню параметров маршрутизации.
- [LTE CLI](https://manual.mikrotik.com/docs/cli-reference/interface/lte/) — имена полей профиля новых версий; целевая 7.24.5 проверяется отдельно.
- [Default configurations](https://manual.mikrotik.com/docs/getting-started/configuration-management/default-configurations/) — шлюз через интерфейс LTE.


Локальные `runtime/` отчёты, учётные данные и снимки устройств не входят в
репозиторий. Методика повторения проверок: [TESTING.md](TESTING.md).
