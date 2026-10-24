# Приёмка LTE/APN

После этой LTE-итерации добавлены группы/приложения и диагностика. Последняя общая регрессия — [POLICIES-VALIDATION.md](POLICIES-VALIDATION.md); ниже сохранён исторический результат LTE.

Итерация завершена: **109 unit, 105 проверок CHR и четыре Windows GUI-набора PASS**. Итоговый отчёт — `runtime/lte-final-validation.json`; аудит — `runtime/lte-final-clean-state.json`. Все 13 последовательных suite завершились exit0. Дата UTC: 2026-10-23T18:44:57.324800+00:00.

## Стенд и пределы проверки

Пять CHR RouterOS 7.24.5: edge, три ISP и клиент. Контроллер работает локальными RouterOS scripts/scheduler; Python используется для установки, GUI и тестов. Рабочий MikroTik не подключался и не менялся.

APN menu и его настройки настоящие. CHR не содержит LTE-радиомодема. В LTE-тестовом пакете заменяется только функция чтения LTE inventory: данные передаются по реальной PPP point-to-point линии. Маршруты, probes, marks, NAT, API и controller исполняются на CHR. Production reader возвращается после теста; production test-mode отсутствует. Проверка не подтверждает SIM, радиорегистрацию, driver/firmware или совместимость конкретного модема.

## LTE проверки

| Набор | Проверок | Что проверяется |
|---|---:|---|
| LTE APN | 6 | Read-only capture, выключение automatic default, сохранение distance/DNS/authentication, baseline rollback, исходный add=no, ручной drift, удалённый профиль |
| Native LTE resolver | 7 | APN name/ID arrays, текущий dynamic IPv4/interface gateway, APN drift, default adoption, disconnect/new-IP, shared disabled unselected modem |
| LTE lifecycle | 10 | Установка без data session, reapply, ingress/DNAT, три TCP/NAT потока, silent failover/failback, scoped CT, new-IP/fresh SLA, APN drift, reboot, baseline |
| LTE protection | 4 | Один baseline общего APN, reapply, исходный add=yes/distance, injected worker error после изменения APN и полный binary restore с reboot |

Отчёты: `runtime/lte-apn-acceptance.json`, `runtime/lte-native-acceptance.json`, `runtime/lte-acceptance.json`, `runtime/lte-protection-acceptance.json`. Unit-набор:109 PASS, включая прежние static/DHCP/PPP и новые LTE контракты.

## Общая регрессия и GUI

Общая матрица включает mixed static/DHCP/PPP lifecycle, provider protection, resolver/reconciler, protected deployment, deployment/legacy, native SLA faults, connections, wizard и 14 базовых проверок. Fault suites запускаются последовательно, без параллельных изменений стенда. Сводка выполнений — `runtime/lte-regression-suites.json`.

Windows GUI проверяется отдельно: LTE с APN и экспортом девяти файлов на сохранённом CHR inventory с LTE adapter; mixed WAN через настоящий native API; static wizard через API; шесть offline сценариев кнопки «Создать конфигурацию» на сохранённом inventory, без обращения к рабочему устройству.

Первые два mixed lifecycle запуска остановились на сохранности DHCP-потока при PPP reconnect. Observer показал самостоятельное нарушение voice jitter SLA: 20–48 мс при пороге 15 мс, затем штатное переключение client102 и его conntrack cleanup. Это не доказательство удаления посторонних меток. Для изоляции session lifecycle в test cfg задан jitter 100 мс. `config/sdwan.json`, production controller и отдельная native SLA fault acceptance сохраняют исходные строгие пороги. Диагностика — `runtime/lte-mixed-failure-evidence.json` и два сохранённых observer файла.

## Что остаётся открытым

Миграция существующих OSPF/VPN-политик и защита филиальных префиксов требуют [отдельного согласования](OSPF.md). Guard сторонних mark rules сохраняется. LTE Internet failover не подтверждает резервирование GRE/IPIP/EoIP с фиксированным WAN source, WireGuard endpoints или достижимость через CGNAT. Аппаратные, нагрузочные и длительные испытания остаются следующими этапами проекта.

## Финальный аудит

Все восемь установленных RSC совпадают с исходниками native; production LTE reader не содержит адаптер. На пяти CHR нет временных APN/PPP/VLAN, тестовых правил и фоновых TCP fetch jobs. Тестовые host forwards удалены. Baseline не содержит provider_clients/lte_apns fixtures. Proxy без impairments; lab-v1 healthy, default/client101 WAN1, client102 WAN2, strict103 WAN3. Автопродолжение этой завершённой итерации отключено.


Локальные `runtime/` отчёты, учётные данные и снимки устройств не входят в
репозиторий. Методика повторения проверок: [TESTING.md](TESTING.md).
