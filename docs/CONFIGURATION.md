# Конфигурация JSON

Один JSON описывает WAN, SLA, политики и backend. Нативный установщик создаёт из него согласованный комплект из восьми RSC и JSON. Генератор не создаёт учётные данные PPPoE/APN и не заменяет первоначальную настройку интерфейсов, NAT или базового firewall.

## Верхний уровень

| Поле | Назначение |
|---|---|
| `schema_version` | Целое `1` |
| `revision` | Непустая строка до 80 символов для статуса и подтверждения установки |
| `health` | Интервал, таймауты, кворум и окна состояний |
| `sla_profiles` | Именованные пороги RTT, jitter и потерь |
| `wans` | От 1 до 16 каналов |
| `local_networks` | Внутренние IPv4-префиксы, исключаемые из интернет-классификации |
| `policies` | От 1 до 64 политик, включая одну default |
| `takeover_route_comments` | Комментарии исходных default routes, которые можно принять под управление |
| `takeover_rule` | Исходное routing rule; пустые `src-address` и `table`, если его нет |
| `takeover_routes` | Необязательные точные селекторы прочитанных main/default routes |
| `disable_fasttrack` | Необязательные точные селекторы FastTrack, мешающего policy routing |
| `groups` | Необязательные группы адресов для селекторов |
| `controller_backend` | `routeros` по умолчанию либо `container` |
| `container` | Публичные параметры локального контейнера; пароля здесь нет |
| `container.telemetry` | Необязательный RAM/web модуль, выключен по умолчанию; [параметры и доступ](STATISTICS.md) |
| `maintenance` | Необязательный `backup_keep` (1–20), очистка завершённых архивов после committed; без поля выключена |

Поля takeover/FastTrack удобнее получать через API-мастер: он проверяет, что обнаруженные объекты не изменились. Не переносите их идентификаторы с другого устройства.

## SLA и измерения

```json
{
  "health": {
    "interval_seconds": 5,
    "timeout_ms": 700,
    "packet_count": 20,
    "packet_interval_ms": 25,
    "quorum": 2,
    "fail_windows": 3,
    "recover_windows": 6,
    "hold_down_seconds": 60,
    "stale_seconds": 15
  },
  "sla_profiles": {
    "default": {"rtt_ms": 150, "jitter_ms": 30, "loss_percent": 2},
    "voice": {"rtt_ms": 80, "jitter_ms": 15, "loss_percent": 1}
  }
}
```

Это фрагмент, а не полный входной файл. ICMP train с учётом timeout должен помещаться в интервал; `stale_seconds` покрывает как минимум два интервала. `quorum` не превышает число разных целей каждого WAN. Задайте собственные независимые цели, доступные через проверяемый канал. До появления адреса и свежего SLA dynamic WAN закрыт.

## WAN

Общие поля: `name`, `interface`, `probe_table` (уникальная `sdwan-*`), IPv4 `icmp_target` и `probes`. Статический канал дополнительно задаёт `address` без маски и `gateway`; `kind` может отсутствовать для обратной совместимости.

Для `kind=dhcp` или `kind=pppoe` укажите существующий логический интерфейс, не сохраняйте текущую аренду в `address/gateway`. Для `kind=lte` также укажите `apn_profile`; адрес берётся из LTE-сессии, gateway привязывается к интерфейсу. Подробности: [DYNAMIC-WAN.md](DYNAMIC-WAN.md), [LTE.md](LTE.md).

В `probes` поддерживаются `http-get`, `https-get`, `tcp-conn` с `host/port` и `dns` с `host/dns_server`. Имя цели допускает точки, дефисы и подчёркивания. Дублирование одной цели не увеличивает кворум. Измерения закреплены за WAN и не должны незаметно уходить через резервный провайдер.

## Политики

Default-политика имеет `source=""` и `table="main"`. У обычной клиентской политики IPv4 prefix в `source` и собственная таблица `sdwan-*`. Общие поля: `name`, `profile`, `mode`, упорядоченный список `wans`, `allow_degraded`.

- `prefer` выбирает первый допустимый WAN в порядке списка.
- `strict` задаёт ровно один WAN и закрывается при его недоступности.
- `allow_degraded` разрешает канал с нарушенным SLA при отсутствии healthy; это явный выбор политики.

Группы, destination, L3-интерфейс, protocol, порты, приоритеты и пересечения подробно описаны в [POLICIES.md](POLICIES.md). Пример: [clients-applications.json](../config/examples/clients-applications.json).

Неизменная повторная установка сохраняет потоки. Изменение классификатора/группы/порядка требует переклассификации управляемых исходящих соединений. При изменении выбранного WAN удаляются связанные управляемые записи conntrack; входящие WAN/probes имеют отдельные исключения.

## Примеры и проверка

- [sdwan.json](../config/sdwan.json) — полный пример для CHR-лаборатории.
- [clients-applications.json](../config/examples/clients-applications.json) — группы и составные политики.
- [container.json](../config/examples/container.json) — локальный Rust backend и management bypass.

```sh
python3 sdwan.py --config config/sdwan.json validate
python3 sdwan.py --config config/sdwan.json bundle --output build/native
```

Имена и ключи проверяются строго; неизвестные поля отвергаются. Точные контракты: [config.py](../sdwan/config.py), [policies.py](../sdwan/policies.py), [container_config.py](../sdwan/container_config.py). Все реальные credentials и обнаруженные конфигурации храните локально согласно [SECURITY.md](../SECURITY.md).
