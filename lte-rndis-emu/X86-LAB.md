# Изолированный x86 / CHR стенд LTE

[English](X86-LAB.en.md)

Рабочий MikroTik не используется. Исходный лицензированный образ не изменять,
не публиковать и не включать в Docker. Здесь тестируется его отдельная полная
копия; переносимость лицензии на другую топологию не предполагается.

## Диск и запуск x86

Из корня локального SD-WAN проекта:

```bash
mkdir -p runtime/x86-lte-lab/images runtime/x86-lte-lab/runtime
cp --sparse=always --reflink=auto images/mikrotik-routeros-kvm-disk.qcow2 \
  runtime/x86-lte-lab/images/routeros-x86-l6.qcow2
```

**Копировать только при первом создании**, не поверх уже обновлённой VM.
Сохранить SHA256 исходника и копии перед первым запуском. Не создавать новый MBR,
не переустанавливать систему, не менять software-id и не подменять ключ.

Сначала запустить эмулятор и дождаться `ready`, затем x86 (из корня проекта;
порты предварительно проверить на занятость):

```bash
qemu-system-x86_64 \
  -name sdwan-x86-lte -machine pc -accel kvm -cpu host -m 1024 -smp 1 \
  -display none \
  -drive file=runtime/x86-lte-lab/images/routeros-x86-l6.qcow2,format=qcow2,bus=0,unit=0,media=disk \
  -serial tcp:127.0.0.1:24401,server=on,wait=off \
  -qmp tcp:127.0.0.1:24400,server=on,wait=off \
  -netdev user,id=mgmt,net=10.79.0.0/24,dhcpstart=10.79.0.15,ipv6=off \
  -device e1000,netdev=mgmt,mac=52:54:00:79:00:01 \
  -device qemu-xhci,id=xhci \
  -chardev socket,id=lteusb,host=127.0.0.1,port=24320,reconnect=2 \
  -device usb-redir,chardev=lteusb,id=lte-rndis,bus=xhci.0
```

Параметры chardev получать через `python3 -m lte_rndis_emu qemu-args` из
`lte-rndis-emu`: `reconnect=2` подтверждён именно для QEMU 8.2.2.
Если новая группа kvm ещё не применена к текущей WSL-сессии, запускать команду
через `sg kvm -c '...full command...'`. Не добавлять пользователя в root-группы.

В serial войти как `admin+ct`. Имя management Ethernet определять по
`/interface/print detail`: в предоставленном образе оно было `ether3`.
Задать отдельный лабораторный пароль. Management только через loopback; доступ
USB и Ethernet внутрь RouterOS не означает безопасный внешний management.

## Обновление штатными средствами

На предоставленной копии до обновления получены `7.24.4`, `x86_64`, `nlevel: 6`.
Для x86 у MikroTik пакет называется **routeros-7.24.5.npk**, без суффикса x86_64.
Обновлять вместе с установленным wireless. Проверить доступность сервера и место:

```routeros
/system/resource/print without-paging
/system/license/print
/system/package/print without-paging
/tool/fetch url="https://download.mikrotik.com/routeros/7.24.5/routeros-7.24.5.npk" dst-path=routeros-7.24.5.npk
/tool/fetch url="https://download.mikrotik.com/routeros/7.24.5/wireless-7.24.5.npk" dst-path=wireless-7.24.5.npk
/file/print without-paging
/system/reboot
```

В выполненной проверке официальные NPK предварительно скачаны хостом по HTTPS,
затем RouterOS получил их через `/tool/fetch` с loopback HTTP-сервера хоста,
доступного guest как `10.79.0.2:24406`. Установка — обычная перезагрузка RouterOS.
Пакеты, ключи и диски остаются в игнорируемых каталогах. После обновления повторить
проверки версии/пакетов/лицензии; фактически получены 7.24.5 и nlevel 6.
Исходный QCOW2 остался байт-в-байт прежним.

Документация MikroTik: [обновление и установка](https://help.mikrotik.com/docs/spaces/ROS/pages/328142/Upgrading+and+installation),
[лицензии](https://help.mikrotik.com/docs/spaces/ROS/pages/328149/RouterOS+license+keys).

## Отдельный ISP и проверка трафика

Создать отдельный CHR overlay на чистом `chr-7.24.5.img`, не на дисках текущих VM.
Две NIC: management usernet `10.80.0.0/24`, DHCP start `10.80.0.15`; вторая —
`socket,connect=127.0.0.1:24322` из USAGE. QMP 24410, serial 24411.
Чистый CHR по умолчанию имеет DHCP-client на ether1; второй не добавлять.

```routeros
/ip/address/add address=192.0.2.1/24 interface=ether2
/ip/address/add address=198.18.79.1/32 interface=lo
/ip/pool/add name=lte ranges=192.0.2.10-192.0.2.50
/ip/dhcp-server/network/add address=192.0.2.0/24 gateway=192.0.2.1 dns-server=10.80.0.3
/ip/dhcp-server/add name=lte interface=ether2 address-pool=lte disabled=no
/ip/firewall/nat/add chain=srcnat out-interface=ether1 action=masquerade
```

На DUT дождаться DHCP `bound` именно для lte1. Для тестов адресов добавить
узкие маршруты через LTE, чтобы management default не дал ложный успех:

```routeros
/ip/route/add dst-address=198.18.79.1/32 gateway=192.0.2.1%lte1 comment=lte-emulator-test
/ip/route/add dst-address=10.80.0.2/32 gateway=192.0.2.1%lte1 comment=lte-emulator-test
/ping 198.18.79.1 interface=lte1 count=5
```

Для TCP запустить HTTP на loopback хоста 24406 с небольшим тестовым файлом,
в fetch задать фактический DHCP-адрес LTE как src-address и `output=none`.
`output=user` с длинным JSON включает pager и мешает автоматическому serial.

Чтобы проверить CHR как DUT, создать ещё один чистый overlay, QMP24420 / serial24421,
management usernet10.81.0.0/24, virtio disk и NIC, те же USB-аргументы.
**Один эмулятор принадлежит одному DUT**: сначала отключить x86 USB frontend и
его chardev через QMP, затем стартовать CHR. Для одновременной работы нужны разные
экземпляры эмулятора и непересекающиеся порты; в выполненном тесте переключались
последовательно. Не заменять работающий edge и не использовать его порты.

Проверка APN: `/interface/lte/apn/set [find where default=yes] add-default-route=no use-peer-dns=no`.
Дождаться пересоздания динамического клиента и сравнить его параметры.
Для управляемого обрыва служба запускается с `--gate`, затем POST `/lte` меняет
registration_status на searching и обратно registered. Снять ping до/во время/после.

Результаты: [VALIDATION.md](VALIDATION.md). Радио и внешняя сотовая сеть не эмулируются.
