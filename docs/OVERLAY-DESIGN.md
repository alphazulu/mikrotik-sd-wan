# Реализация филиального overlay

Русский | [English](OVERLAY-DESIGN.en.md)

Первый native overlay установлен на трёх CHR: четыре туннеля и восемь OSPF
соседств здоровы. Настоящий inner TCP сохраняется при отказе/возврате WAN;
all-down включает remote-LAN blackhole. GUI/ключи проверены 5 offline и
4 live Windows/Tk случаями: [мастер](OVERLAY-GUI.md). Последующие native/rollback/
container проверки пройдены; длительная приёмка ещё идёт. [Текущий статус](CURRENT-STATUS.md).
Версия не объявляется выпущенной.

## CGNAT и тестовая сеть

Оба филиала могут находиться за CGNAT. Каждый открывает два независимых
WireGuard-пути с keepalive к доступному публичному MikroTik/CHR-хабу; hub только
отвечает. Прямая CGNAT→CGNAT-доступность, relay-сервис и платная инфраструктура
не предполагаются. Рабочая адресация пока не задана.

`tools/overlay_lab.py --project-root <private project>` управляет только своими
`runtime/overlay-lab` дисками, портами, credentials и bootstrap-маркерами.
Команды: up/status/baseline/keys/down. Не повторяйте ожидающую mutation.
Management/API привязаны к loopback; пять CHR используют отдельные qcow2 overlays
закреплённого официального raw 7.24.5.

- hub: API 55728, management10.78.0.15, public198.18.100.1/30, ether2 WAN.
- sitea: API 55729, management10.78.1.15, WAN100.64.10.2/30 и 100.65.10.2/30,
  LAN 10.201.1.1/24 на ether4.
- siteb: API 55730, management10.78.2.15, WAN100.64.20.2/30 и 100.65.20.2/30,
  LAN 10.201.2.1/24 на ether4.
- nata: API 55731, management10.78.3.15, public198.18.100.2 ether2,
  внутренние gateways ether3/4, Internet transit198.18.200.1 ether5.
- natb: API 55732, management10.78.4.15, public198.18.200.2 ether2,
  внутренние gateways ether3/4, default через 198.18.200.1.

NAT-A переводит только 100.64.0.0/16, сохраняя публичный source NAT-B.
NAT-B переводит 100.65.0.0/16. Входящих mappings в филиалы нет. Все четыре WAN
достигают одного IPv4 hub. HTTP58081..58083 — тестовые цели, не контроллеры.
Loopback проб NAT-A/B198.19.100.1/198.19.200.1 DNAT к QEMU host service addresses.
Клиентские адреса за филиалами —10.201.N.2.

## Конфигурация и ключи

`sdwan/overlay.py` проверяет optional overlay через основной JSON validator и
native installer. Роли site/hub; MTU по умолчанию 1380, MSS clamp выключен,
внутренние SLA-таймеры ограничены. Туннель задаёт имя, WAN, уникальный local
listen port, /30 или /31 local address, peer address, local/peer PUBLIC keys,
peer prefixes и OSPF cost. Site требует endpoint/endpoint_port, keepalive25 с.
Hub запрещает endpoints/keepalives. Максимум 16 туннелей на роутер, private keys нет.
Local/remote prefixes не пересекаются; default/multicast/loopback, пересечения
с линками и рекурсивные endpoints отклоняются. Derived bypass включает явно
заданные local/remote prefixes и link subnets.

Подготовка создаёт только выключенные `sdwan-wg-<name>`, комментарий владения
`sdwan:v1:overlay:interface:<name>`. `sdwan/overlay_runtime.py` читает явный набор
только публичных полей, без private-key, проверяет чужие name/port collisions и
pending deployments. После частичной API-ошибки удаляются только новые, ещё не
используемые выключенные интерфейсы. Install сверяет актуальный local public key,
никогда не пересоздаёт молча потерянную identity. Существующие настройки меняются
защищённой транзакцией. Восемь тестовых identities подготовлены; публичный обмен
лежит в приватном `runtime/overlay-lab/runtime/overlay-public-keys.json`.

Пары стенда: sitea hub-wan1/2 ↔ hub sitea-wan1/2, аналогично siteb. Site порты
51821/22; hub51821/22 для A и 51823/24 для B. Раздельные 10.203.N.0/31: site.0,
hub.1; Router ID из 10.202.0.0/24. Ключи берутся с подготовленных интерфейсов,
не выдумываются; exports не публикуются. Peer prefixes филиалов охватывают LAN
другого филиала; hub допускает только LAN своего peer и inner peer IP.
Для OSPF multicast каждому отдельному интерфейсу нужен allowed-address224.0.0.5/32.

## Требования интеграции native

Первый overlay добавил девятую RSC-библиотеку. Теперь стандартный пакет —
11RSC+JSON; FILES, SDK payload и recovery archive включают optional modules.
Отсутствие файла в прежнем пакете архивируется как отсутствие для его удаления
при rollback. Ниже архитектурные требования, а не перечень всё ещё неготовых
шагов. Optional helpers не импортируются каждый выключенный такт; installer и
controller используют одинаковые bypass prefixes.

Preflight проверяет все планируемые объекты и владение до mutation. Нужны уже
подготовленные WG с совпадающими public keys. Чужие OSPF instances/templates/routes
сохраняются. Включённый чужой template, совпадающий с новым WG/подсетью, запрещён:
ключи подготовлены до адресов, фактические списки интерфейсов уже доступны.
Учитываются all/static и широкие сети; автоматической миграции legacy OSPF нет.

Core cleanup удаляет ненужные управляемые routes/rules/Netwatch/sdwan-таблицы;
dataplane отдельно учитывает mangle wanted map. Overlay добавляет свои ожидаемые
объекты или сохраняет namespace до своего reconciler. Active WG/peers не должны
удаляться/создаваться на каждом apply; teardown убирает только свои объекты.

Outer UDP по local listen port закрепляется за WAN probe table раньше общих
source/router marks и local bypass. Входящие ответы симметричны: responder hub
отвечает через принявший WAN. Listener принадлежит своему WAN. Branch outer UDP
требует точного SNAT этого WAN, даже если initial main lookup выбрал другой
source. Dynamic ready/bindings сверяются; старый outer conntrack выводится при смене.

Для inner peer создаётся `sdwan-ol-<name>` lookup-only table, /32 через свой WG
и default blackhole. Source/peer rule раньше общего local bypass. Netwatch привязан
к local IP туннеля: другая линия не отвечает вместо неработающей. Inner RTT/jitter/
loss/quorum и physical ready независимы от публичного Internet quorum. RAM ограничена,
свежие поколения, fail/recover/hold-down обязательны. Drain/down отзывает допуск
пути, но один drain не выключает WG.

Свой OSPFv2 instance/area никогда не originates default. Connected redistribution
через output filter принимает только local_prefixes, затем всё отклоняет. У hub
local prefixes могут быть пустыми. Templates только на собственных WG: ptp,
hello1 с/dead4 с и заданная cost. Плохой template отключается, а не только получает
высокую cost: all-bad отзывает путь. Меняются только переходы состояния. Каждый
remote LAN защищён высоким main blackhole; site prefixes обходят Internet
classifiers. Стабильные inner address/conntrack переживают WAN/OSPF-переход.
Optional MSS clamp действует только на forward TCP SYN собственных WG и вычисляется
из явного IPv4 MTU.

## Условия приёмки

- Native import/schema/ownership и protected rollback новой библиотеки; повторная
  подготовка ключей/public-only inventory.
- Два WAN-туннеля каждого CGNAT-site, inner SLA, OSPF и только явные site-prefix
  advertisements, без default/WAN leak.
- Outer pinning/SNAT, отказы/возврат, all-down blackholes, NAT endpoint/dynamic
  source changes и границы чужого OSPF.
- Настоящий inner TCP siteA→hub→siteB остаётся established. Тестовые сервисы могут
  жить на QEMU-хосте, решения — на MikroTik. Lab-only site-B LAN SNAT допустим,
  если тестовому endpoint нужен напрямую подключённый return source.
- GUI/ключи/topology/per-node JSON, диагностика, bounded web, MTU/MSS, Rust/native parity.
- После функционального freeze один 48–72 чsoak с PID/lock/checkpoints. Затем
  privacy/CI/release и сверенная синхронизация root source, без duplicate soak.

Drain/down всех WAN default допускается узким derived allow_no_default в
protected journal. Commit требует свежего RouterOS-подтверждения, что admission
всех default WAN отключён, и нового management connection. Одного unavailable
состояния недостаточно. Четыре unit combinations и 3 single-WAN CHR drain/down/
re-enable прошли, дополнительно 6 multi-WAN TCP cases. Incoming management/probes
остаются независимыми.

## Основные источники

- [WireGuard и multi-WAN replies](https://manual.mikrotik.com/docs/virtual-private-networks/wireguard/)
- [OSPF instance](https://manual.mikrotik.com/docs/cli-reference/routing/ospf/instance/)
- [OSPF templates](https://manual.mikrotik.com/docs/cli-reference/routing/ospf/interface-template/)
- [OSPF areas/redistribution](https://manual.mikrotik.com/docs/user-guides/routing-and-networking-protocols/unicast/ospf/areas-and-virtual-links/)

Manual описывает 7.26; нужные responder/instance/template/filter команды отдельно
проверены на hub7.24.5 с выключенными временными объектами, затем удалены.
Существующие OSPF-объекты не менялись.

## Подтверждённый первый срез

Валидатор, bypass, native install/dataplane/controller, SDK payload и recovery
manifest включили overlay. Тогда пакет имел 10RSC+JSON с VPN-egress, сейчас —
11RSC+JSON. Core сохраняет overlay namespace для своего reconciler. Initial peer
активируется после outer pinning/NAT/firewall. Настоящий failed install вернул
pre-overlay encrypted config и удалил прежне отсутствовавшую девятую библиотеку.
Исправленный пакет установлен на hub и обоих sites. Свежие счётчики нормализуются:
nil done-tests до первого Netwatch иначе навсегда мешал recover. Проверка /31
требует каноническую subnet, а не prefix с host bits.

Четыре TCP-кейса: initial OSPF, reception на ТОМ ЖЕ conntrack ID после WAN1 fail,
preferred failback, all-down blackhole. Native API blackhole — пустой flag,
не строка true. Первоначальный hardening охватывал partial config/peer/endpoint,
точный outer cleanup, health/key bounds, foreign OSPF/list, off/on/rollback,
диагностику и новый container parity. Последующие targeted gates — в
[текущем статусе](CURRENT-STATUS.md); один smoke не является полным release gate.

## Windows к существующему CHR

Hyper-V/WSL может резервировать порты диапазона 55728. QEMU/Linux API 55728..55732
доступны. Windows GUI использует loopback aliases45728hub/45729siteA/45730siteB/
45731NATA/45732NATB. `python3 tools/overlay_lab.py windows-api --project-root PRIVATE_ROOT`
добавляет/переиспользует forwards существующих NIC, не перезапускает гостей и
не создаёт fabric. Новые запуски включают aliases автоматически.

QEMU TCP links могут задерживать пакеты даже с KVM/здоровыми physical probes.
Functional lab явно использует inner jitter250 мс; продукт default50 мс. За 90 с
с default все три native routers, включая нетронутый второй site, кратко отзывали
OSPF: потери 0, jitter>50 мс. Functional routing проверяется с lab budget, strict
SLA — отдельно. Это не разрешение расширять SLA рабочей сети.

Outer geometry хранится в bounded RAM. Изменение learned endpoint, parent IP/gateway
или peer/listener удаляет только прежний remote UDP tuple этого listener в обоих
направлениях. Снимок local IPv4 учитывает кэширование WireGuard source другого WAN
до NAT. Стабильная структура сохраняет conntrack, inner TCP не входит в очистку.
CGNAT port-change retire занял 1,444 с при оставшемся timeout2 м 59 с, сохранив SiteB UDP
и обычный/private TCP. Forced geometry тест проверяет standby cached source,
но не заменяет реальную смену DHCP. [DNS bootstrap](DNS-BOOTSTRAP.md).

## Неполный адресный кэш

Изолированная регрессия 7.24.5 обнаружила incoming standby UDP, чей local WAN IP
отсутствовал в кэше. Cached WAN source был верен, fresh inventory содержал адрес;
старый retire вернул 0. Доказана ошибочная membership-проверка, не время/причина
возникновения неполного кэша.

Теперь retire объединяет прошлый socket snapshot, прошлый resolved WAN source
и текущие valid local IP. Старые адреса сохраняются после исчезновения аренды.
Текущие flags читаются из строк, disabled/invalid исключены; оба inventory≤1024.
Unknown geometry, чужой endpoint/ports, неверные типы/слишком большой inventory
не дают удаления. Exact UDP/listener filters и оба направления сохранены.
Дополнительный inventory читается только при retirement; stable путь не получает
новый polling/flash writes. Overlay library revision2 обновляет runtime loader.

Запуск old/new функции на собственном пяти-CHR-стенде:

```sh
python3 tests/overlay_retirement_cache_acceptance.py \
  --lab-root /srv/sdwan/private/project \
  --previous-source /srv/sdwan/private/previous/native/sdwan-overlay.rsc
```

Пятнадцать проверок прошли: old воспроизводит 0, new удаляет настоящий standby;
комбинации кэша/WAN hint/current inventory и flags/bounds соблюдены, primary/SiteB
UDP и обычный/private TCP сохранены. Fault inventory подменяет только read expression,
не удаляет адреса. Live cache/config сохраняются. Первая попытка драйвера прочитала
незавершённый marker и упала; теперь ждёт полный JSON. Её failed report сохранён.
Это отдельные проверки, не замена native DHCP/PPPoE/rollback/cold-boot и matching soak.
