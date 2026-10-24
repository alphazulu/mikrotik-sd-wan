# Повторение проверок

## Без подключения к роутеру

Из корня проекта с Python 3.12:

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall -q sdwan tools configurator.py sdwan.py
python3 sdwan.py --config config/sdwan.json validate
python3 sdwan.py --config config/examples/clients-applications.json validate
python3 sdwan.py --config config/examples/container.json validate
python3 tools/audit_public_tree.py
```

Текущий unit-набор содержит179 проверок и использует временные файлы/mocks. Сетевые CHR acceptance имеют другие имена и не запускаются `unittest discover`. Rust unit и проверка scratch archives описаны в [BUILD.md](BUILD.md). Для Tk GUI нужен дисплей; offline-сценарий `python3 tests/gui_wizard_regression.py` не подключается к устройству и использует только вымышленные данные.

## Исходная пятиузловая лаборатория

Подготовьте QEMU/WSL по [LAB.md](LAB.md). Затем:

```sh
python3 lab.py up
python3 lab.py verify
python3 sdwan.py --url api://127.0.0.1:18728 apply
python3 tests/native_acceptance.py
python3 tests/connections_acceptance.py
python3 tests/dynamic_wan_acceptance.py
python3 tests/lte_acceptance.py
python3 tests/lte_protection_acceptance.py
python3 tests/protected_deployment_acceptance.py
python3 lab.py verify
```

Запускайте fault suites последовательно, из одной оболочки, после окончания предыдущего набора. Они изменяют только тестовые CHR и восстанавливают fixtures. После аварийного прерывания проверьте журнал установки и выполните `python3 lab.py heal`, не запускайте новую установку поверх незавершённой транзакции.

Дополнительные наборы: `tests/policies_acceptance.py`, `tests/policies_protection_acceptance.py`, `tests/link_resolver_acceptance.py`, `tests/link_reconcile_acceptance.py`. LTE в CHR проверяется inventory adapter поверх настоящего PPP-пути; это не испытание физического модема.

`tests/legacy_update_acceptance.py` требует путь к сохранённому прежнему пакету отдельным аргументом. Он не является самостоятельным quickstart-тестом и не восстанавливает отсутствующую историческую версию из текущих исходников. Флаг `--resume-negatives` у protected deployment нужен только для продолжения прерванного набора при уже сохранённом положительном результате той же версии.

## Контейнерный стенд

Он создаётся отдельно в `runtime/container-lab/project`, с портами +20000 и независимыми writable qcow2. Сначала загрузите базовый CHR: `python3 lab.py prepare`. Затем `python3 tools/container_lab.py up` и `python3 tools/container_lab_native.py`. Пакет MikroTik container7.24.5 должен быть заранее помещён в `runtime/container-packages/container-7.24.5.npk`; `tools/container_lab_package.py` устанавливает его и подтверждает device-mode холодным стартом только отдельной VM.

Для установки backend используйте текущий `container-prepare/apply` из [CONTAINER.md](CONTAINER.md). В [container.json](../config/examples/container.json) заданы лабораторная identity, порты и образ. Подготовьте image в Files перед `container-prepare`.

Основные сценарии: `container_bridge_acceptance.py`, `container_provision_acceptance.py`, `container_active_acceptance.py`, `container_fencing_acceptance.py`, `container_protection_acceptance.py`, `container_missing_metadata_acceptance.py`, `container_resources_acceptance.py`. Они требуют подготовленного активного SDK backend и собственных fixtures; результаты сохраняются в `runtime/`.

Shadow/image bootstrap scripts отражают ранние прототипы и могут требовать их отдельной раскладки файлов; для текущей установки используйте SDK/GUI. Сборка проверяется без Docker daemon. При измерении таймингов избегайте одновременной нагрузки двух пятиузловых стендов.

## Что было выполнено

Текущая матрица:155 Python unit,9 Rust unit,50 контейнерных CHR checks,70 нативных regression checks и4 набора Windows GUI. Подробности и ограничения: [CONTAINER-VALIDATION.md](CONTAINER-VALIDATION.md). Предыдущие этапы имеют отдельные отчёты; число проверок нельзя суммировать как уникальные сценарии.

Сырые журналы, пароли, screenshots, архивы восстановления и экспорты устройств намеренно не опубликованы. После клонирования они отсутствуют и создаются только вашим локальным запуском.

## CI

`.github/workflows/ci.yml` запускает unit/schema/bundle/security проверки на Linux/Windows,
офлайн GUI в Windows, Gitleaks и Rust unit. После них собираются три scratch-образа
и сверяются архивы. Actions закреплены полными SHA, Gitleaks —версией и SHA256;
обычные jobs имеют только contents:read. Публикация release включается только
для явно отправленного тега v* после всех проверок; write-права есть лишь у release job.
CHR fault suites в облаке не запускаются, доступ к рабочему MikroTik CI не требуется.
