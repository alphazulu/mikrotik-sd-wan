# Проверка на WSL / QEMU / RouterOS — 26 октября 2026

Это результаты выполненных проверок, не обещание поддержки всех LTE-модемов.

| Проверка | Фактический результат |
|---|---|
| Хост | WSL Ubuntu 24.04.2, kernel 6.18.54.1-microsoft-standard-WSL2 |
| QEMU | 8.2.2, KVM |
| probe | usbredir-userspace; USB host support есть, gadget выключен, UDC нет |
| TAP / AF_PACKET | Для TAP получен EPERM; TAP-путь не объявляется рабочим |
| Использованный транспорт | socket:127.0.0.1:24322, реальные Ethernet-кадры в отдельный ISP CHR |
| x86 до обновления | RouterOS 7.24.4, x86_64, nlevel 6 |
| x86 после штатного обновления | RouterOS + wireless 7.24.5, nlevel 6, software-id прежний |
| Исходный QCOW2 | SHA256 после проверки совпал с SHA256 до копирования |
| x86 USB / LTE | hardware type=usb: 12d1:14db, HUAWEI Mobile; lte1 RUNNING |
| CHR USB / LTE | Чистый CHR 7.24.5; hardware type=usb: 12d1:14db; lte1 RUNNING |
| DHCP через LTE | x86 192.0.2.50/24, CHR 192.0.2.49/24, gateway 192.0.2.1 |
| ICMP через LTE x86 | 5 sent / 5 received / 0% loss |
| ICMP через LTE CHR | 5 sent / 5 received / 0% loss |
| TCP через LTE | На обоих DUT `/tool/fetch`: status finished, code 200, 1 KiB |
| APN на CHR | add-default-route=no/use-peer-dns=no отражены в динамическом DHCP-client |
| Управляемый обрыв на CHR | --gate, registered: 3/3; searching: 0/3; registered: 3/3 + HTTP200 |
| Unit / socket tests | 21 tests: 20 passed, 1 explicitly skipped privileged TAP test |
| Изоляция lab.py | Opt-in меняет только edge; команды остальных VM побайтно прежние |

TCP-цель — HTTP-сервер хоста через выделенный виртуальный ISP, не публичный
сотовый оператор. Узкие /32 маршруты и source LTE исключали обход через
management default. ISP имеет собственный NAT. DHCP не реализован в эмуляторе.
QEMU usbredir и RouterOS hardware подтверждены отдельно от synthetic enumerate.

Выдержки из вывода выполненной проверки (переносы и отступы сокращены):

```text
QMP info usb (CHR):
  Device 0.1, Port 1, Speed 480 Mb/s, Product USB Redirection Device, ID: lte-rndis

/system/resource/usb/print
syntax error (line 1 column 21)

/system/resource/hardware/print detail without-paging where type=usb
1 location="1-1" parent=1-0 type=usb vendor="HUAWEI" name="HUAWEI Mobile"
  serial-number="EMU00000001" vendor-id="0x12d1" device-id="0x14db"
  speed="480" usb-version=" 2.00" manufacturer-reported-max-power="500mA"
  irq=0 owner="system" device-path=""

/interface/lte/print detail without-paging
Flags: R - RUNNING
0 R default-name="lte1" name="lte1" mtu=1500 apn-profiles=default

/ping 198.18.79.1 src-address=192.0.2.49 count=5
sent=5 received=5 packet-loss=0%

/tool/fetch url="http://10.80.0.2:24406/manifest.json" src-address=192.0.2.49 output=none duration=5s
status: finished
code: 200
downloaded: 1KiB
```

Полные serial/JSON-логи (лабораторные пароли удалены из echo) сохранены локально в игнорируемом
`runtime/x86-lte-lab/runtime/`: probe.json, enumerate.json, chr-raw.log,
x86-raw.log, routeros-raw.log, qmp-chr-usb.json и validation.json.
Образы, лицензия, credentials, файлы рабочего MikroTik в публичную ветку не входят.

## Исправленные реальные ошибки

1. QEMU сначала отклонил устройство: `No interface info for device`. Исправлено:
   INTERFACE_INFO и EP_INFO отправляются **до** DEVICE_CONNECT.
2. Затем QEMU отвергал данные control IN: `unexpected extra data ep 00`.
   Исправлено сохранение endpoint 0x80 в ответе (ранее всегда 0).
3. Добавлены тесты этих случаев, реальный непривилегированный TCP L2 backend,
   отказ от любых modprobe при неподтверждённом UDC, ограничение очереди RX,
   обработка ошибочного JSON/HTTP и закрытие сокетов/потоков при выходе.

Порядок подключения и направление endpoint сверены с
[исходным кодом QEMU 8.2.2 hw/usb/redirect.c](https://github.com/qemu/qemu/blob/v8.2.2/hw/usb/redirect.c).
VID/PID и класс RNDIS для получения результата не менялись.

## Ограничения

HiLink создаёт реальный RouterOS LTE-интерфейс с Ethernet/DHCP, но не эмулирует
RF, SIM и радиооператора. `/interface/lte/monitor lte1 once` показал session-uptime;
RSSI/RSRP/оператор из JSON доступны в HTTP, не доказаны как RouterOS monitor.
Профиль AT отдельно в этих live-проверках не применялся. MBIM не реализован.
`--gate` имитирует потерю данных, не гарантирует аппаратное снятие RUNNING.
Старый QEMU socket netdev после рестарта сервиса требует отдельного переподключения.
Это тест LTE-пути, не полный SD-WAN failover/48h soak. Основная SD-WAN работа остаётся
на паузе владельца, существующие узлы и production не изменялись.
