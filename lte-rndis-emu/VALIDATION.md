# Проверка на WSL / QEMU / RouterOS — 26 октября 2026

[English](VALIDATION.en.md)

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
| Unit / socket | 21 тест: 20 PASS, один привилегированный TAP-тест явно пропущен |
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
Это тест LTE-пути, не полный SD-WAN failover/48h soak. На дату этого исторического этапа основная SD-WAN работа была
на паузе владельца; это не текущее состояние проекта. Существующие узлы и production
в том тесте не менялись.


## Повторная проверка TAP на отдельной Ubuntu VM — 28 октября 2026

Использована отдельная Ubuntu 24.04 / KVM лаборатория; прежний длительный
SD-WAN soak и production не менялись. QEMU 8.2.2, x86 RouterOS 7.24.5 с L6;
геометрия IDE сохранена. Отдельный виртуальный ISP отвечает на DHCP и выполняет
NAT. Эмулятор не выдаёт адреса. USB/control endpoints только loopback.

| Проверка | Результат |
| --- | --- |
| Probe | usbredir-userspace; USB gadget modules/usbip не использовались |
| Unit | 24/24 PASS; privileged TAP test выполнен, ResourceWarning считаются ошибкой |
| Hardware RouterOS | type=usb, HUAWEI Mobile, 12d1:14db; реальный вывод CLI |
| LTE / APN | lte1 RUNNING; динамический DHCP bound; add-default-route=no, use-peer-dns=no задаются через APN |
| Интернет | HTTPS к публичной цели с LTE source и узким маршрутом через LTE завершён |
| Расширенный TCP | 40 GET: 6 225 920 байт; 40 POST: 1 310 720 байт, сервер проверял тело каждого POST |
| TAP capture | 7732 Ethernet-кадра; 7648 TCP-пакетов, неверных TCP checksum 0, кадров больше 1514 байт 0 |
| Обрыв / восстановление | registered 3/3, searching 0/3, registered снова 3/3 |
| Cleanup | Все собственные маршруты/APN/USB frontend и процессы удалены; L6 сохранена |

В отдельной изолированной рабочей копии исправлен bulk OUT completion:
в поле length возвращается реальное число принятых байтов, без повторения данных.
Регрессионный тест воспроизводит старую нулевую длину и проверяет исправление,
включая перенос старших 16 бит. Это соответствует
[usbredir protocol](https://gitlab.freedesktop.org/spice/usbredir/-/blob/main/docs/usb-redirection-protocol.md)
и usbredirhost bulk completion.

Неудачные попытки сохранены отдельно. В одной из них QEMU завершился по assert
usb_packet_complete_one; его точная причина не доказана и универсальное
исправление QEMU здесь не заявлено. Позднейший TLS timeout локализован по pcap:
виртуальный ISP с offload передал кадр 2598 байт с неверной TCP checksum.
После отключения offload только у выделенного TAP-порта функциональная серия
выше прошла. Это не повод менять VID/PID или делать USB modprobe.

В тестовом launcher также устранено наследование игнорируемого SIGINT от фоновой
оболочки. Один прогон прошёл трафик, но завершился ошибкой остановки службы;
он не объявлен полным PASS. После ручной очистки новый launcher подтвердил
автоматическую очистку. Cached inactive LTE entry после USB detach — поведение
RouterOS; перед повторным использованием проверялась принадлежность стенду.

Это функциональная приёмка изолированного LTE data path. Она не проверяет
SD-WAN переключение политик, радио, SIM или полную выдачу полей monitor/scanner;
не доказывает полосу реального LTE и аппаратную производительность MikroTik.
Измеренная скорость промежуточного CHR не используется как capacity-профиль.

## Дополнительная проверка MTU / QEMU 8.2.2 (2026-10-28)

На новой одноразовой CHR без Ethernet-подключения исходный вариант и вариант
только с исправлением OUT length воспроизводят `usb_packet_complete_one` на
смешанной серии кадров 64/2598 bytes. Контрольная серия 64-byte кадров проходит.
Backtrace: `usb_packet_complete_one` ← `usb_combined_input_packet_complete` ←
`hw-usb-redirect.so`. В trace пять BABBLE completions, затем отмены запросов;
нарушений FIFO bulk completions не обнаружено. Это локализует входное условие,
но не доказывает универсальную причину/исправление всех ошибок QEMU.

В новом кандидате RX отбрасывает Ethernet-кадры больше 1514 bytes до упаковки
RNDIS: объявленный IP MTU равен 1500. 25/25 тестов прошли, включая настоящий
privileged TAP test. Новый тест на исходном коде ожидаемо падает: слишком
большой кадр завершает pending USB request с BABBLE вместо отбрасывания.
Исправленный вариант сохраняет pending request для следующего допустимого кадра.
Смешанная серия: все 450 допустимых кадров переданы, QEMU не завершился по assert,
BABBLE нет, cleanup успешен. Jumbo и VLAN frames этим профилем не поддерживаются.

Предыдущая HTTPS/gate приёмка выше относится к предыдущему варианту исходника.
После изменения MTU выполнены unit и отдельные USB серии, HTTPS/gate заново
не проверялись. Эти результаты нельзя объединять в полную приёмку нового кода.

## MTU guard: полная CHR data-path проверка (2026-10-28)

После изменения MTU выполнена отдельная серия на двух новых CHR 7.24.5/KVM:
DUT с RNDIS и ISP с DHCP/NAT. Licensed x86 и существующие VM не использовались.
USB12d1:14db и lte1 RUNNING подтверждены; APN управляет dynamic DHCP client,
add-default-route=no/use-peer-dns=false. Публичный HTTPS fetch выполнен с LTE
source и /32 route. Затем 40TLSGET/40TLSPOST:6225920/1310720 bytes, сервер проверил
тело каждого POST. Локальный TLS fixture использует тестовый самоподписанный
сертификат с отключённой проверкой сертификата только для этой цели.
Gate ICMP3/3→0/3→3/3. QEMU не завершался по assert.

PCAP:8563Ethernetframes/8434IPv4TCP,0frames>1514,0IPv4/TCPchecksumerrors,
0uncheckedTCPfragments. Инспектор обнаруживает намеренно испорченную TCP checksum
и усечённый capture. Cleanup успешен: own QEMU/emulator/capture остановлены,
own TAP удалён, raw CHR backing image SHA не изменился. Диски/ключи/credentials
сохранены только в private workspace и не предназначены для публикации.

Предыдущие неуспешные попытки относятся к bootstrap/строгому сравнению API:
динамический DHCP нельзя удалить; LTE REST может вернуть add-default-route=no,
а не false. Эти условия исправлены в тестовом сценарии, код эмулятора не менялся.
Эта серия подтверждает MTU-кандидат на CHR, но не является тестом RF/SIM,
производительности MikroTik или SD-WAN переключения политик.
