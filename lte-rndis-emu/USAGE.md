# LTE RNDIS emulator — инструкция для агента

Программный USB-модем для CHR. Данные — мост L2 на интерфейс, который передаёт вызывающий. DHCP-сервера здесь нет. Радио нет: поля LTE — имитация управления.

Не утверждать, что VID/PID сам создаёт `/interface lte`. Дескрипторы повторяют Linux `f_rndis` (control `02/02/ff`, data `0a/00/00`). `12d1:14db` — это id, который MikroTik документирует как config-less E3372h, поверх этого класса, а не вместо него.

## Сначала probe на хосте, где запущен QEMU

Работать в WSL Ubuntu лаба, не в случайной песочнице. Первая команда:

```bash
python3 -m lte_rndis_emu probe
```

Дальше только то, что напечатал `decision.path`:

- `usbredir-userspace` — USB gadget в этом ядре нет. Не делать `modprobe` и не пересобирать ядро. Запускать `serve` и подключать QEMU через `usb-redir`. `lsusb` на хосте устройства не покажет; сравнимый вывод — `enumerate`.
- `configfs-dummy-hcd` — поднять `scripts/gadget-configfs.sh`, убедиться через `lsusb`, затем пробовать `usb-host`. Если libusb устройство не отдаёт, тот же гаджет отдать через `usbredirserver` на `127.0.0.1`. `usbip` с usbredir не смешивать.
- `unproven` — остановиться и приложить вывод probe. Не угадывать путь.

`scripts/gadget-configfs.sh` сначала выполняет `probe` и выходит с кодом 3 без загрузки модулей, если путь не `configfs-dummy-hcd`. Одного `CONFIG_USB_SUPPORT=y` недостаточно.

## Контракт команды

Рабочий каталог: корень этого проекта (`lte-rndis-emu`).

```bash
python3 -m lte_rndis_emu probe
python3 -m unittest discover -s tests -v
python3 -m lte_rndis_emu enumerate --json
python3 -m lte_rndis_emu qemu-args
```

Служба:

```bash
python3 -m lte_rndis_emu serve --uplink lte0
```

`--uplink` обязателен. `none` — только USB, кадры никуда не уходят. Позиционный аргумент тоже принимается: `serve lte0`.

Строка готовности на stdout, одна, её и ждать:

```text
ready usbredir=127.0.0.1:24320 control=127.0.0.1:24321 uplink=lte0 profile=hilink vid=0x12d1 pid=0x14db gate=0
```

Коды выхода `serve`: `0` по Ctrl+C, `2` если интерфейса нет, адрес не loopback, или порт занят.

Слушает только `127.0.0.1` или `::1`. Второй клиент usbredir закрывается: устройство принадлежит одному QEMU.

## Куда девается трафик

`--uplink` — существующий интерфейс (tap, veth, dummy, порт моста). Эмулятор открывает на нём `AF_PACKET` и копирует кадры Ethernet как есть.

```text
CHR lte  --usbredir/RNDIS-->  этот процесс  --L2-->  --uplink
```

- Кадр с хоста уходит на интерфейс только после того, как USB-хост сделал RNDIS `INITIALIZE` и `SET OID_GEN_CURRENT_PACKET_FILTER` с ненулевым фильтром. Драйвер RouterOS делает это сам.
- Встречный кадр с интерфейса заворачивается в `REMOTE_NDIS_PACKET_MSG` и уходит в bulk IN.
- IP, DHCP, NAT и DNS этот процесс не разбирает и не отвечает. Magic cookie DHCP, если он есть в кадре, уходит на uplink байт в байт.
- Адресацию вешает агент на этот tap или дальше по мосту. Пример, не часть эмулятора: `dnsmasq` на `lte0`.

### WSL без CAP_NET_ADMIN / CAP_NET_RAW

EPERM при TAP или AF_PACKET остаётся ошибкой этого способа. Эмулятор не создаёт
фиктивный `lte0`. Для такого хоста есть отдельный **реальный L2-транспорт** QEMU:

```bash
python3 -m lte_rndis_emu serve --uplink socket:127.0.0.1:24322 --gate
```

Дождаться `ready`, затем запустить виртуальный ISP с отдельной Ethernet NIC:

```text
-netdev socket,id=lte-uplink,connect=127.0.0.1:24322
-device virtio-net-pci,netdev=lte-uplink,mac=02:12:d1:14:db:01
```

USB подключается к DUT через `qemu-args`, Ethernet — к **другой** VM (ISP).
Порт 24322 принадлежит этому профилю; не подключать к нему действующие ISP стенда.
Пакеты идут как Ethernet в TCP: 4 байта длины в network byte order, затем кадр.
Принимается один loopback-клиент; частичные TCP-записи собираются, неверная длина
отключает клиента. Буферы ограничены. Привилегии, USB/IP и модули ядра не нужны.

На ISP настроить `192.0.2.1/24`, DHCP-пул `192.0.2.10-192.0.2.50`, gateway
`192.0.2.1` и, если нужен внешний доступ, NAT через отдельный uplink ISP.
DHCP обслуживает ISP, а не этот процесс. RouterOS создаёт для HiLink динамический
DHCP-client через `/interface/lte/apn`; его параметры изменять через APN.

При перезапуске эмулятора QEMU usbredir переподключится, если поддержан `reconnect`.
Старый QEMU socket netdev автоматически **не переподключается**: отдельно
перезапустить только выделенную ISP VM или пересоздать её socket netdev.
На физическом интерфейсе прежний способ `--uplink lte0` по-прежнему требует прав.

Создать tap на лабораторном хосте, где есть `ip` и `/dev/net/tun`:

```bash
sh scripts/prepare-uplink.sh lte0
```

Не передавать боевой NIC, если не нужно вливать L2 CHR в этот сегмент. Петлю «uplink снова в тот же CHR» не делать: свои кадры отфильтровываются через `PACKET_IGNORE_OUTGOING`, чужой мост туда-обратно — уже петля.

MAC, который RNDIS отдаёт хосту как permanent address: `02:12:d1:14:db:02` (`--host-mac`). Это адрес интерфейса на стороне RouterOS, не адрес uplink.

## TAP и виртуальный ISP: отключить offload на выделенном порту

AF_PACKET передаёт Ethernet-кадры, а не метаданные virtio-net checksum/GSO.
При подключении отдельной ISP VM к TAP задайте **только её LTE-side NIC**:

```text
-netdev tap,id=lte,ifname=lte0,script=no,downscript=no,vnet_hdr=off
-device virtio-net-pci,netdev=lte,csum=off,gso=off,guest_csum=off,guest_tso4=off,guest_tso6=off,guest_ecn=off,guest_ufo=off,host_tso4=off,host_tso6=off,host_ecn=off,host_ufo=off
```

Не менять management NIC или существующий LAN. Порт TAP не подключать обратно
к тому же DUT. Если используете другой backend, отдельно проверьте размер и
контрольные суммы кадров на его выходе.

На Ubuntu/QEMU 8.2.2 с обычным virtio offload в захват попал Ethernet-кадр 2598
байт с незавершённой TCP checksum; TLS не завершился. С указанными параметрами
проверено 7648 TCP-пакетов без неверных checksum и без кадров больше 1514 байт,
а также HTTPS, двусторонний TCP и управляемый обрыв/восстановление.
Это ограничение L2-транспорта, не оценка скорости LTE-радио. См. VALIDATION.md.

## Управление LTE

Это не радио и не APN-сессия. По умолчанию профиль `hilink`: на USB только RNDIS, без AT. Состояние читает и меняет агент.

`GET http://127.0.0.1:24321/health` → `{"ready": true}`

`GET http://127.0.0.1:24321/lte` → JSON.

`POST` или `PATCH` на `/lte` с частичным JSON. Чужие и неизменяемые ключи (`usb`, `counters`, `source`, `uplink`) игнорируются. Ошибка поля — HTTP 400 `{"error": "..."}`.

Меняемые поля:

| ключ | значения |
|---|---|
| `registration_status` | `registered`, `roaming`, `searching`, `denied`, `unknown` |
| `access_technology` | `LTE`, `UMTS`, `GSM`, `NR` |
| `pin_status` | `ready`, `sim-pin`, `absent` |
| `rssi`, `rsrp`, `rsrq`, `sinr`, `link_bps` | целые; `rssi` в dBm |
| `operator`, `operator_numeric`, `manufacturer`, `model`, `revision`, `imei`, `imsi`, `iccid`, `lac`, `cell_id`, `functionality`, `apn` | строки 1..64 |

`link_bps` только попадает в RNDIS `OID_GEN_LINK_SPEED` (единицы NDIS = бит/с / 100). Кадры не шейпятся.

`registration_status` не `registered` и не `roaming` → `OID_GEN_MEDIA_CONNECT_STATUS` = disconnected. Кадры при этом всё равно мостятся, пока не передан `--gate`.

`--gate` роняет кадры в обе стороны, пока регистрация не `registered` или `roaming`. Для проверки failover SD-WAN. По умолчанию выключен, чтобы поднятие USB не зависело от радио-флага.

`--state path.json` — загрузка при старте и запись после POST. Если файл меняют с диска, следующее чтение подхватывает новый mtime.

`--control none` выключает HTTP. Состояние тогда только из `--state` и значений по умолчанию.

### Профиль `at`

```bash
python3 -m lte_rndis_emu serve --uplink lte0 --profile at
```

К RNDIS добавляются USB-интерфейсы CDC ACM (class `02/02/01`, interfaces 2 и 3). Это канал управления для хоста, не второй канал данных. Если с ним CHR не создаёт `lte`, вернуться на `hilink`: лишние интерфейсы — отклонение от чистого `f_rndis`, который на RouterBOARD уже показывали как `lte1`.

AT, которые отвечают сразу (неизвестный AT — `ERROR`, без паузы):

| команда | ответ |
|---|---|
| `AT`, `ATE0`, `ATE1` | OK, эхо по умолчанию включено |
| `ATI`, `AT+CGMI`, `AT+CGMM`, `AT+CGMR` | manufacturer / model / revision |
| `AT+CGSN`, `AT+GSN` | imei |
| `AT+CIMI` | imsi |
| `AT+CCID` | iccid |
| `AT+CPIN?` | `READY`, `SIM PIN`, или `+CME ERROR: 10` если `pin_status=absent` |
| `AT+CSQ` | `(rssi+113)/2` и `,99`; иначе `99,99` если не registered/roaming |
| `AT+CREG?`, `AT+CGREG?`, `AT+CEREG?` | `0,1` registered, `0,5` roaming, `0,2` searching, `0,3` denied, `0,4` unknown |
| `AT+COPS?` | `"operator",7` для LTE, `2` UMTS, `0` GSM, `12` NR |
| `AT+CGDCONT?` | показ `apn`; PDP не открывается |

Не обещать, что RouterOS на config-less `12d1:14db` вообще откроет ACM. Для hilink мониторные поля могут остаться пустыми, пока жив только JSON.

## Как подключить к существующему лабу CHR

Репозиторий `alphazulu/mikrotik-sd-wan`, функция `node_command` в `lab.py`. Сейчас у VM нет USB-контроллера. Добавлять аргументы только узлу `edge`, не меняя lifecycle `up`/`down` и не трогая остальные узлы.

Порядок: сначала `serve`, потом QEMU. QEMU — TCP-клиент. Если CHR уже запущен, новый chardev сам не появится.

`qemu-args` печатает аргументы. Если в этом `qemu-system-x86_64 -chardev socket,help` есть `reconnect-ms` или `reconnect=`, суффикс добавляется сам. Иначе строка без reconnect: старт эмулятора после QEMU устройство не подхватит, пока процесс QEMU не перезапущен.

Вставка:

```python
if name == "edge" and os.environ.get("LTE_RNDIS_EMU") == "1":
    args.extend([
        "-device", "qemu-xhci,id=xhci",
        "-chardev", "socket,id=lteusb,host=127.0.0.1,port=24320",
        "-device", "usb-redir,chardev=lteusb,id=lte-rndis,bus=xhci.0",
    ])
```

Порты `24320` и `24321` не пересекаются с QMP `24100+`, serial `25100+`, сокетами `23100`/`22100` и hostfwd этого лаба. Держать их на `127.0.0.1`.

Не использовать `usbip` вместе с usbredir. У QEMU нет универсального `-device usbip`. `usbredirserver` оборачивает реальное устройство из libusb; пока гаджета в `lsusb` нет, запускать его незачем. `probe` сохраняет `usbredirserver --help` только если бинарник есть, и сам редирект не делает.

Горячее добавление контроллера и устройства после старта службы проверено на отдельном x86; базовый lab использует аргументы запуска. Надёжный путь — аргументы до старта edge.

## Критерии по шагам

1. Для AF_PACKET интерфейс существует (`ip link show lte0`); EPERM означает отказ этого способа. Для явно выбранного `socket:` проверить реальный Ethernet с отдельным ISP. Наличие `enumerate` не заменяет передачу кадров ни в одном способе.
2. `enumerate` или, на ядре с USB, `lsusb`: id `12d1:14db`, RNDIS `02/02/ff`.
3. QEMU: монитор или QMP `info usb` показывает устройство на `xhci`. Это ещё не RouterOS.
4. В CHR: `/system/resource/usb/print` (и `/system/resource/hardware/print detail`, если эта команда в данной версии есть). Устройство видно как USB.
5. Только потом `/interface/lte/print detail`. Пока шаги 3–4 не зелёные, отсутствие `lte` не лечится сменой одного лишь PID.
6. Трафик: кадр с CHR появляется на uplink, ответный кадр возвращается. DHCP должен ответить тот, кого агент посадил на uplink, не эмулятор.

Если USB в RouterOS есть, а `lte` нет — это шаг E из постановки: снять usbmon с живого совместимого модема и не подменять вывод догадкой. Следующий обоснованный класс после RNDIS — MBIM, не случайный VID.

## Чего процесс не делает

- Не выдаёт DHCP, не назначает адрес CHR, не прячет NAT.
- Не отвечает на AT в профиле `hilink`.
- Не эмулирует SIM, регистрацию в сети оператора и полосу радио. `imei`/`imsi` в JSON синтетические.
- Само по себе не доказывает `/interface lte`. Это проверяется только на живом CHR по шагам выше, с сырым выводом команд.

## Проверено на RouterOS 7.24.5

См. [VALIDATION.md](VALIDATION.md): на отдельных x86 L6 и CHR получены настоящий
`lte1`, DHCP через APN, ICMP и TCP через RNDIS. В этой версии команда
`/system/resource/usb/print` отсутствует (syntax error); USB-устройство видно в
`/system/resource/hardware/print detail without-paging where type=usb`.

`lab.py` уже добавляет `qemu-args` только при `LTE_RNDIS_EMU=1` и только для `edge`.
По умолчанию команды всех VM прежние; up/down не менялись. Не перезапускать
чужие запущенные узлы для этой проверки. Отдельный x86 запускается по
[X86-LAB.md](X86-LAB.md), с сохранением IDE `bus=0,unit=0,media=disk`.

Ограничение HiLink: `/interface/lte/monitor lte1 once` показывает время сессии,
но синтетические RSSI/APN/оператор из HTTP не становятся радиоданными RouterOS.
`--gate` меняет передачу пакетов при POST регистрации; это имитация потери
доступности для SLA, а не аппаратного отключения SIM или смены оператора.
Тесты TAP выполняются только с явным `LTE_EMU_TAP_TEST=1`.

RX принимает Ethernet frames до 1514 bytes (IP MTU 1500); большие кадры
отбрасываются до USB completion. TAP/veth offload следует выключить на выделенной
стороне источника: GSO/checksum-offload кадры не соответствуют обычным Ethernet
кадрам для RNDIS. Ограничение размера не исправляет неверную TCP checksum и не
заменяет эту настройку offload. Jumbo/VLAN data path отдельно не реализован.
