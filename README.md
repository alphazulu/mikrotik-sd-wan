# MikroTik SD-WAN

SD-WAN for RouterOS with local SLA monitoring, WAN failover, policy routing and a desktop configurator. The controller runs on the MikroTik itself: RouterOS scripts or a small Rust container built `FROM scratch`.

Контроллер выбирает интернет-канал по доступности, RTT, jitter, потерям и приоритетам. Для работы маршрутизации не нужен внешний сервер. Python используется для настройки, диагностики и лабораторных проверок; GUI можно закрыть после установки.

## Возможности

- IPv4 WAN: static, DHCP-client, PPPoE и LTE через существующий APN.
- Независимые контрольные цели, кворум, SLA-профили, окна отказа/восстановления, hold-down и защита от устаревших измерений.
- Общая очередь провайдеров и отдельные политики для клиентов, групп адресов, VLAN/L3-интерфейсов, протоколов и портов.
- Режимы `prefer` и `strict`, приоритет правил и закрытие политики при отсутствии допустимого канала.
- Connection marks и отдельные таблицы: ответы роутера и DNAT возвращаются через входящий WAN. При переключении очищаются соответствующие управляемые записи conntrack.
- GUI: чтение API, выбор WAN, редактор JSON, просмотр плана, установка, откат, диагностика и объяснение выбора канала для потока.
- Установка через локальный scheduler/worker/watchdog: зашифрованный backup, новое API-подтверждение, восстановление с перезагрузкой при ошибке или потере подтверждения.
- Rust backend: один статический процесс, постоянная API-сессия, RAM heartbeat, защита от старых команд и конкурирующих владельцев. При потере контейнера выбор продолжает нативный алгоритм.
- Опциональная RAM-статистика и встроенный read-only web в отдельном scratch-образе: графики SLA/RX/TX, события, политики, экспорт JSON на компьютер. По умолчанию выключены; [настройка](docs/STATISTICS.md).
- Точечные файловые API-запросы, пропуск одинаковых записей и опциональное хранение последних backup-групп после подтверждения установки: [обслуживание](docs/MAINTENANCE.md).

## Поддерживаемая среда

Исполнение и установка закреплены на **RouterOS 7.24.5**. Python GUI/CLI проверены с **Python 3.12**; pip-зависимостей нет, для GUI нужен Tkinter. Лаборатория требует Linux/WSL2, QEMU и около 3 ГиБ памяти для пяти CHR. KVM ускоряет проверки; доступен режим TCG.

Rust-образы собраны для `linux/amd64`, `linux/arm64`, `linux/arm/v5`. Запуск и импорт проверены на CHR amd64. Для физического MikroTik отдельно проверьте поддержку пакета `container`, архитектуру и device-mode. Физические ARM и LTE-модемы ещё не испытывались.

## Быстрый старт: GUI

```sh
git clone https://github.com/alphazulu/mikrotik-sd-wan.git
cd mikrotik-sd-wan
```

В Windows установите Python с Tkinter и откройте **[Configure-SD-WAN.cmd](Configure-SD-WAN.cmd)**. В Linux с графической сессией:

```sh
python3 configurator.py
```

1. Подключитесь к API MikroTik и получите настройки. Предпочтителен `apis://` с проверяемым сертификатом; обычный API используйте внутри доверенной сети управления.
2. Отметьте внешние интерфейсы и задайте приоритеты. Для DHCP выбирается интерфейс клиента, для PPPoE — логический PPPoE client, для LTE — интерфейс с существующим APN.
3. Создайте конфигурацию, задайте контрольные цели, SLA, локальные сети и политики клиентов. Сохраните JSON в локальный файл.
4. Выберите контроллер: **«Скрипт RouterOS»** либо **«Локальный контейнер Rust»**. Контейнер сначала нужно отдельно подготовить: [инструкция](docs/CONTAINER.md).
5. Изучите план изменений и выполните защищённую установку. После подтверждения проверьте вкладку диагностики.

Пошаговая инструкция: [конфигуратор](docs/CONFIGURATOR-WIZARD.md), [параметры JSON](docs/CONFIGURATION.md), [установка и восстановление](docs/DEPLOYMENT.md).

## CLI и файлы конфигурации

В репозитории находятся только лабораторные/синтетические примеры. `config/sdwan.json` содержит адреса и ускоренные таймеры CHR-стенда; для своего роутера создайте JSON через мастер. Файл `config/sdwan-intent.json` — исторический проектный документ, не входной файл установщика.

Локальная проверка и экспорт без подключения к роутеру:

```sh
python3 sdwan.py --config config/sdwan.json validate
python3 sdwan.py --config config/sdwan.json bundle --output build/native
python3 sdwan.py --config config/examples/clients-applications.json validate
python3 sdwan.py --config config/examples/container.json bundle --output build/container
```

CLI получает учётные данные из отдельного локального JSON, например `runtime/router-credentials.json`:

```json
{"username": "sdwan-operator", "password": "<your-router-password>"}
```

Файл создайте самостоятельно и ограничьте доступ к нему. Его нельзя добавлять в Git. Затем используйте URL, CA, identity и конфигурацию своего устройства:

```sh
python3 sdwan.py --config config/local-router.json --url apis://router.example.net:8729 --ca /path/to/ca.pem --credentials runtime/router-credentials.json --expect-identity my-router plan
python3 sdwan.py --config config/local-router.json --url apis://router.example.net:8729 --ca /path/to/ca.pem --credentials runtime/router-credentials.json --expect-identity my-router apply
```

Команды `status`, `events`, `rollback`, `enable`, `disable` используют те же параметры подключения. `disable` замораживает последний выбор, а `rollback` возвращает исходное состояние проекта. Подробности: [нативный контроллер](docs/NATIVE-CONTROLLER.md).

## Минимальный контейнер

База `scratch` не содержит дистрибутива. В образе один Rust/musl ELF, UID `65532:65532`; пароль и настройки подключаются отдельными mounts только для чтения.

| Архитектура | Base tar / gzip, байт | Web tar / gzip, байт |
|---|---:|---:|
| amd64 | 563 200 / 273 417 | 778 240 / 376 733 |
| ARM64 | 512 000 / 268 997 | 696 320 / 370 503 |
| ARMv5 | 512 000 / 266 619 | 706 560 / 368 635 |

CI-сборка 0.2.0: базовый профиль без HTTP, web-профиль с модулем, выключенным по умолчанию.

Готовые архивы и контрольные суммы: [Releases](https://github.com/alphazulu/mikrotik-sd-wan/releases). Инструкции по подготовке Rust SDK, сборке и запуску: [BUILD.md](docs/BUILD.md), [CONTAINER.md](docs/CONTAINER.md).

В 66-секундном замере на CHR с CI web-образом RSS процесса составлял 832–836 КиБ для трёх WAN,
двух SLA-профилей и четырёх политик. Во время опроса/экспорта проверяемые файлы не
изменялись. Это не гарантия максимального расхода памяти для 16 WAN или поведения
на физическом ARM. [Проверки web и ресурсов](docs/STATISTICS-VALIDATION.md),
[предыдущая приёмка базового контроллера](docs/CONTAINER-VALIDATION.md).

## Лаборатория и проверки

```sh
# Linux/WSL2: нужны qemu-system-x86_64 и qemu-img
python3 lab.py up
python3 lab.py verify
python3 sdwan.py --url api://127.0.0.1:18728 apply
python3 tests/native_acceptance.py
python3 lab.py down
```

`up` скачивает официальный CHR 7.24.5 и создаёт пять VM с отдельными дисками и случайными паролями. Все управляющие порты привязаны к loopback. Лабораторные воздействия запускайте последовательно; проверку на существующем роутере эти команды не выполняют.

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
python3 tools/audit_public_tree.py
```

Перед публикацией прошли **155 Python unit-тестов**, **9 Rust unit-тестов**, **50 контейнерных + 70 нативных CHR-проверок** и **четыре набора GUI**. Исторические и текущие матрицы разделены в документации. Подробности: [LAB.md](docs/LAB.md), [TESTING.md](docs/TESTING.md), [приёмка контейнера](docs/CONTAINER-VALIDATION.md).

Этап оптимизации API/архивов расширил unit-набор до183, добавил17 целевых CHR-проверок и проверил28 baseline-сценариев двух стендов. CI выполняет проверки и собирает три scratch-образа автоматически. [Результаты и измерения](docs/RESOURCE-VALIDATION.md).

## Границы версии

Реализованы IPv4 и выбор приоритетного канала, а также политики по L3/L4. IPv6, DPI, PCC/взвешенная балансировка, QoS, шифрованный overlay и централизованное управление площадками остаются в [плане развития](ROADMAP.md).

Существующие OSPF/VPN, VRF и чужие connection/routing marks требуют согласования. Защита от конфликтующих маркировок сохранена; автоматическая миграция произвольной сети не реализована. LTE за CGNAT не гарантирует входящую доступность. [Совместимость OSPF/VPN](docs/OSPF.md).

## Документация и структура

Полный [индекс руководств](docs/README.md) охватывает настройку, SLA, WAN, политики, маркировку, восстановление, контейнеры и повторение проверок. Правила хранения конфигураций и учётных данных: [SECURITY.md](SECURITY.md).

Опциональный слой статистики/web спроектирован с хранением истории в RAM и выключенным по умолчанию listener; HTTP-сервер ещё не включён в текущий образ. [Архитектура и бюджет записи](docs/STATISTICS-DESIGN.md).

| Каталог | Содержимое |
|---|---|
| `native/` | Восемь RSC ядра и защищённой установки |
| `sdwan/`, `sdwan.py` | Проверка JSON, API, генератор, установка и диагностика |
| `configurator.py` | Tkinter GUI |
| `container-controller/` | Rust-контроллер, мост RouterOS и сборка scratch |
| `config/` | Лабораторная конфигурация и синтетические примеры |
| `lab.py`, `routeros/`, `tools/` | Лаборатория QEMU/CHR и вспомогательные инструменты |
| `tests/` | Unit-тесты и явным образом запускаемые CHR/GUI-сценарии |

Образы CHR, диски, пароли, экспорты устройств, backups, screenshots и содержимое `runtime/` не поставляются с исходниками.
