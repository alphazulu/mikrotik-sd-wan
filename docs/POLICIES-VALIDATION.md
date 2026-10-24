# Приёмка диагностики и расширенных политик

**Итерация завершена: 147 unit, 121 проверка CHR и пять Windows GUI-наборов PASS.** Все 17 последовательных suite завершились exit0; установленные восемь RSC совпадают с frozen исходниками. Итог: `runtime/policies-final-validation.json`; аудит: `runtime/policies-final-clean-state.json`. Дата UTC: 2026-10-24T00:35:31.381990+00:00.

## Новый функциональный набор

`tests/policies_acceptance.py` проверяет настоящий трафик пяти CHR RouterOS 7.24.5. Создаются временный тегированный VLAN 993 между клиентом и edge, изолированные TCP-сервисы и API-сессия через WAN3. Рабочий MikroTik не подключался.

| Проверка | Подтверждённое поведение |
|---|---|
| Порядок и guard | Явные приоритеты, группы и blackhole policy tables; у составных селекторов нет широкого source-only routing rule |
| Четыре TCP/NAT потока | Совпадение source/destination group, подсети, портов и реального VLAN ingress; остальные клиенты/порты используют свои политики |
| UDP | UDP-specific rule не наследует TCP приложение; проверены connection marks и настоящий проход через ISP |
| Диагностика | IP/interface, возраст проб, recovery/hold, причины выбора, bounded events и объяснение нового потока соответствуют RouterOS |
| Windows GUI | Чтение live API, группы/диалог/перестановка правил, диагностика, объяснение, экспорт 9 файлов и JSON без пароля; роутер не изменён |
| Группа | Редакция membership пересоздаёт managed outbound flows, сохраняя входящий API |
| Reapply | Неизменные селекторы/группы/порядок сохраняют установленные клиентские потоки |
| Порядок | Изменение priority меняет правило для нового потока, в том числе при том же WAN |
| Снятие условий | Старые protocol/src-port/dst-port matcher не остаются после редактирования; UDP получает новую политику |
| Strict | При silent outage WAN2 подходящий поток не выходит через исправные WAN1/WAN3; VLAN и входящий API сохраняются |
| История | Отказ/возврат приложения видны в локальном RAM журнале |
| Удаление политики | Старые marks удалены, счётчик отражает очистку, входящий API сохраняется |
| Baseline | Откат удаляет собственные группы, селекторы и blackholes |

Отчёт: `runtime/policies-acceptance.json`. Windows дополнительно проверяет локальное старение снимка, автоопрос, очистку после ошибки API и смены подключения: `runtime/gui-policies-diagnostics-validation.json`. Unit-набор 147 PASS покрывает совместимость старых JSON, пересечения/полное перекрытие, границы портов, группы, flow explanation и SLA-диагностику.

## Защита и история

`tests/policies_protection_acceptance.py`:105 вызовов event helper оставляют ровно 100 последних последовательных событий; native installer отвергает селектор на main/default; ошибка worker после реального создания группы/правила возвращает encrypted binary backup, восемь RSC и прежний JSON с reboot. Отчёт `runtime/policies-protection-acceptance.json`.

В первом компонентном запуске функция не была загружена в его API-контекст (`typeof=nothing`), хотя имя было видно в environment. Исправлен тест: он явно загружает ту же библиотеку links. После этого граница 100 прошла. Нативные исходники не менялись: `runtime/policies-component-scope-evidence.json`.

На этом CHR UDP-traceroute с size28 имел нулевую длину UDP header и не создавал ожидаемый conntrack. В fixture явно заданы size64 и ожидание публикации conntrack. Захват и сведения — `runtime/policies-udp-fixture-note.json`; production правила для обхода этой особенности не менялись.

## Общая регрессия

К новым 16 проверкам добавлен прежний набор 105 CHR: APN/LTE resolver/lifecycle/protection, static/DHCP/PPPoE mixed lifecycle, динамические resolver/reconciler, worker/watchdog/legacy deployment, строгие SLA fault tests, соединения, wizard и базовый verify. Они выполняются последовательно. Полная матрица прошла: 147 unit, 121 CHR и пять Windows GUI-наборов. Все 17 suite завершены успешно.

SHA256 нативных файлов зафиксирован до регрессии; итоговый audit сравнивает установленные RSC, проверяет все пять CHR, отсутствие fixture групп/VLAN/правил/jobs/host forwards, точный набор managed tags и здоровый lab-v1. Автоматический повтор уже успешных наборов не запускается.

## Границы

Поддерживаются IPv4 селекторы по адресам/группам/L3 интерфейсам/протоколам/портам. DPI, FQDN feeds, долговременные графики/журнал, миграция существующих OSPF/VPN-политик, аппаратные и нагрузочные испытания не входят в эту итерацию. История ограничена RAM и начинается заново после reboot. Контроллер полностью локален; GUI не требуется для маршрутизации.

## Финальное состояние

Пять CHR проверены. Нет временных групп/VLAN/правил, фоновых test/fetch jobs, component файлов и host forwards 18996/18997/18998/18999. Набор managed tags точно соответствует baseline config; все 8 RSC равны исходникам, LTE test adapter отсутствует. lab-v1 healthy; default/client101 WAN1, client102 WAN2, strict103 WAN3. Proxy без impairments. Рабочий MikroTik не подключался и не менялся. Нативная итерация завершена; контейнерная разработка продолжается отдельно.


Локальные `runtime/` отчёты, учётные данные и снимки устройств не входят в
репозиторий. Методика повторения проверок: [TESTING.md](TESTING.md).
