# LTE-поля внутри RouterOS: следующий профиль эмулятора

Цель: синтетическое состояние должно доходить до `/interface/lte/monitor` через
штатный драйвер модема, без скрипта, который рисует похожий вывод. Рабочий HiLink
с реальным трафиком остаётся отдельным проверенным профилем.

## Выбор протокола

Предпочтительный прототип — **MBIM**, затем AT-канал для полей, которые драйвер
RouterOS получает только vendor-командами. RouterOS v7 документирует автоматическую
загрузку MBIM-драйвера. Наличие AT-интерфейса рядом с RNDIS само по себе не означает,
что драйвер HiLink начнёт его опрашивать. Не менять VID/PID наугад и не выдавать JSON
управления за поля MikroTik.

MikroTik отдельно отмечает: набор полей monitor зависит от модема. Поэтому обещание
«все поля любых модемов» неверно. Приёмка должна перечислять конкретные поля, которые
фактически показали CHR и x86 7.24.5; неизвестное остаётся unknown, не нулём.

| Набор | Что реализовать в модеме | Где проверять |
|---|---|---|
| Идентификация | Device Caps, revision, IMEI, serial; AT manufacturer/model при запросе драйвера | monitor, hardware |
| SIM | Subscriber Ready, IMSI, ICCID, PIN query/set, absent/locked/ready | monitor, pin-status, ошибки |
| Сеть | Register State, Packet Service, provider/PLMN, registered/roaming/searching/denied, LTE/UMTS/GSM | monitor и переходы |
| Базовый сигнал | MBIM Signal State: RSSI и корректные unknown-коды | monitor, изменение через HTTP |
| Расширенный сигнал | MBIMEx/подтверждённые AT-запросы для RSRP, RSRQ, SINR | только по реальному trace и monitor |
| Ячейка | поддерживаемый Location/Cell Info service либо AT, CID/TAC/eNB/PCI/band/EARFCN | monitor/cell-monitor при поддержке |
| Сессия и APN | Connect query/set, Radio State, IP Configuration, адрес/DNS/gateway/MTU | APN RouterOS, IP, маршруты, трафик |

MBIM 1.0 сам по себе не гарантирует RSRP/RSRQ/SINR. MBIMEx 2.0 расширяет Signal
State RSRP/SNR, но RouterOS должен согласовать и реально использовать расширение.
Для оставшихся полей потребуется подтверждённый запрос драйвера, а не произвольная
добавка в ответ.

## Порядок реализации и приёмки

1. Добавить опциональный `mbim` USB-профиль с CDC-MBIM дескрипторами, interrupt
   notifications, SEND/GET_ENCAPSULATED_COMMAND, согласованием transfer size.
   Использовать отдельную тестовую VM и отдельные порты; текущий HiLink не ломать.
2. Записывать ограниченный trace запросов: transaction ID, service UUID, CID,
   query/set, статус и длина. Секреты APN/PIN скрывать. Сначала посмотреть запросы
   RouterOS 7.24.5, затем реализовать ответы и последовательность состояния.
3. Единое RAM-состояние для HTTP, MBIM и AT. Изменения registration/SIM/radio должны
   отправлять MBIM indications и менять доступность data session. RouterOS должен
   видеть изменение без ручного refresh/import или перезапуска эмулятора.
4. MBIM data plane — CDC-NCM/NTB с IP-датаграммами; это иной формат, чем Ethernet
   RNDIS. Реализовать отдельный кодек и явный IP↔Ethernet адаптер к выделенному ISP,
   включая разрешение next-hop/ARP, размеры, fragmentation/aggregation. Не называть
   старый RNDIS bulk транспорт MBIM только после замены descriptor.
5. Сначала Device Caps/SIM/registration/RSSI и рабочий Connect+IP. Снять настоящий
   monitor и двусторонний TCP. Затем расширенный сигнал/ячейка по запросам драйвера.
6. Unit-тесты кодеков и машины состояний: фрагменты, неверные lengths/offsets,
   неподдерживаемые CID, timeout/cancel, PIN, roaming, APN reject, radio-off,
   reconnect. Ограничить RAM-очереди; постоянная запись выключена по умолчанию.
7. Live-приёмка для каждого поля: POST HTTP → соответствующий ответ/indication →
   изменённое поле RouterOS. Не считать эмуляцию полного модема завершённой по
   enumerate или только unit-тестам. Сохранить сырые monitor/USB/trace и трафик.
8. Повторить SD-WAN APN ownership, failover/failback и scoped conntrack retirement
   с modem-data-session loss. HiLink и новый профиль проверять отдельно.

Отдельные задачи SMS, USSD, eSIM, carrier aggregation и modem firmware update не
следуют автоматически из monitor-полей; добавлять их только с явной приёмкой.
Физическое радио не моделируется: значения и отказы синтетические и воспроизводимые.

## Источники

- [Текущий RouterOS Manual: LTE/5G](https://manual.mikrotik.com/docs/mobile-networking/lte-5g/) — MBIM, AT, зависимость monitor от модема. Текущая страница маркирована 7.26; совместимость доказывать на целевой 7.24.5.
- [MikroTik LTE/5G, архив документации](https://help.mikrotik.com/docs/spaces/ROS/pages/30146563/LTE+5G) — MBIM в RouterOS v7, APN и примеры monitor.
- [MikroTik Peripherals](https://help.mikrotik.com/docs/spaces/ROS/pages/13500447/Peripherals) — классы MBIM/CDC/RNDIS и отдельная поддержка AT у моделей.
- [Microsoft MBIMEx 2.0](https://learn.microsoft.com/en-us/windows-hardware/drivers/network/mbimex-2.0-5g-nsa-support) — согласование расширений и RSRP/SNR.

Статус: **план, ещё не реализованный профиль**. Доказанный текущий результат —
HiLink RNDIS, LTE/DHCP/APN/двусторонний трафик и управляемая потеря данных.
