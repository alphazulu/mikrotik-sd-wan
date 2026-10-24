# Проверка static/DHCP-client/PPPoE

Итерация завершена 23.10.2026. Контроллер работает локально на RouterOS 7.24.5; внешний GUI используется для конфигурации через API. Все изменения и аварийные проверки выполнены на пяти CHR. Рабочий MikroTik не менялся.

**79 unit и 78 приёмочных проверок прошли.** Дополнительно прошли Windows GUI smoke и шесть проверок прежней ошибки «Создать конфигурацию». Сводка с SHA256 исходников: `runtime/dynamic-final-validation.json` (локальный отчёт).

| Набор | PASS | Что подтверждает |
|---|---:|---|
| Mixed lifecycle | 14 | Static + DHCP VLAN + logical PPPoE, Windows API GUI, TCP/NAT/marks, симметрия, смена адресов, reboot, baseline rollback |
| Dynamic protection | 3 | Option121 без default закрывает WAN; восстановление default; реальный binary restore после ошибки worker |
| Resolver | 7 | Текущие адреса/peer/gateway, option121, loss/reconnect, duplicate IP guard |
| Reconciler | 4 | Обновление pins/routes/probes, idempotence, действительные ICMP, закрытые policy routes до SLA |
| Protected deployment | 3 | Fresh API ACK, отсутствие ACK, ошибка после отключения API; автономный restore/reboot |
| Deployment | 4 | Дополнительные WAN IP, local bypass, доступ при отключённых main defaults, полный откат |
| Legacy migration | 2 | Старый пакет без mangle; возврат старых файлов и удаление новых объектов после ошибки |
| Native SLA | 15 | Quorum, потери, деградация, приоритеты, строгие политики, hold-down, stale telemetry, fail-closed |
| Connections | 8 | Входящий API/DNAT, настоящие TCP-потоки, selective conntrack при failover/failback |
| API wizard | 4 | Discovery, генерация, установка и сохранение политик |
| Итоговый стенд | 14 | Пять CHR, реальные пробы, LAN, маршрутизация и приоритеты |

Отчёты отдельных наборов находятся в `runtime/*acceptance.json`; последовательность и коды завершения — `runtime/dynamic-regression-suites.json` (локальный отчёт). Fault suites запускались последовательно.

## Что проверено на динамических WAN

Установка допускает включённые клиенты без аренды/сессии: WAN остаётся закрытым, рабочий резерв доступен. После получения адреса контроллер обновляет source pins, таблицы, mangle и Netwatch, ждёт свежие измерения и recover/hold-down. Lease address/gateway не сохраняются в JSON.

Три настоящих фоновых TCP/NAT-потока используют разные WAN. Потеря DHCP и возврат на него удаляют только затронутую policy conntrack; потоки другого клиента и входящий API через PPPoE сохраняются. DHCP new-IP/new-gateway, option121 gateway change и PPPoE new-IP проверены вместе с новым source NAT и строгой политикой. Удаление старых сессий не означает бесшовного переноса TCP между публичными IP.

Входящие ping/API к IP каждого WAN отвечают через свой канал. PPPoE DNAT к клиенту, предпочитающему DHCP для исходящего трафика, сохраняет исходный PPPoE канал ответа. Automatic defaults провайдерских клиентов изолированы и не обходят SLA через main.

Reboot восстанавливает библиотеку и контроллер без внешнего процесса. Baseline rollback возвращает исходные DHCP/PPPoE routing options и сохраняет DHCP hook. Отдельная аварийная установка успевает исключить DHCP WAN, затем намеренно завершается ошибкой: watchdog возвращает encrypted backup, все восемь прежних core/config файлов, routing options и работающий mixed controller после перезагрузки.

При отладке немедленный запуск Netwatch после изменения bindings воспроизводил ICMP tuple с меткой WAN1 и NAT через него. Захват пакетов QEMU показал фактический неверный путь. Добавлены ожидание готовности route/mangle и start-delay=3s; итоговые lifecycle и regression проходят с исходными порогами SLA. Один предыдущий прогон совпал с отдельным переключением WAN2 по SLA; запись окон в последующем прогоне также зафиксировала реальный jitter выше voice-порога 15ms. Приёмочный сценарий сохранения потоков в последнем полном прогоне прошёл. Пороги не ослаблялись.

## Windows GUI

- `runtime/gui-dynamic-wan-validation.json` (локальный отчёт): static/DHCP/PPPoE из реального API, поля dynamic readonly, editor удаляет lease snapshot, валидный комплект из девяти файлов, API plan и неизменная active JSON.
- `runtime/gui-wizard-validation.json` (локальный отчёт): выбор WAN реальными checkbox событиями, сохранение политик, экспорт и plan без изменения роутера.
- `runtime/gui-create-regression.json` (локальный отчёт): шесть проверок, включая прежнюю ошибку с пустым адресом и offline inventory; сетевых обращений нет.

## Итоговое состояние и границы

`runtime/dynamic-final-clean-state.json` (локальный отчёт): временных ресурсов на всех пяти CHR нет, фоновые тестовые fetch завершены, временные hostfwd удалены, fault proxy без неисправностей. Все восемь установленных RSC точно совпадают с исходниками. На edge работает исходная `lab-v1`: default/client101 → WAN1, client102 → WAN2, strict103 → WAN3, все SLA healthy. Baseline не содержит временных provider clients.

Проверены CHR 7.24.5 и admin/full. VRF для совпадающих WAN IP, IPv6, LTE lifecycle, реальные RouterBOARD, ограниченные роли и нагрузочная приёмка остаются отдельными задачами. PCC/веса, QoS и overlay также остаются в [плане](../ROADMAP.md); эта итерация завершает поддержку трёх типов WAN, а не весь production SD-WAN.


Локальные `runtime/` отчёты, учётные данные и снимки устройств не входят в
репозиторий. Методика повторения проверок: [TESTING.md](TESTING.md).
