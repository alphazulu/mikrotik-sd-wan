# lte-rndis-emu

[English](README.en.md)

Пользовательское RNDIS-устройство для лаборатории MikroTik CHR. QEMU подключает
его через `usb-redir`. Ethernet-кадры передаются в интерфейс, указанный в
`--uplink`. В этом процессе DHCP-сервера нет.

Обязательный порядок действий для запуска: [USAGE.md](USAGE.md).

```bash
python3 -m lte_rndis_emu probe
python3 -m unittest discover -s tests -v
python3 -m lte_rndis_emu serve --uplink lte0
```
