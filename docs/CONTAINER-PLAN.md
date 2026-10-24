# План локального контейнерного backend — завершён

Выбран Rust для небольшого процесса без GC/async framework; статический musl,
FROM scratch. Один процесс, одна постоянная native API-сессия. JSON/пароль
отдельно, mounts read-only, UID65532, ограниченные буферы/таймауты.

- [x] Cross-build ARMv5/ARM64/amd64, минимальный single-layer Docker-save без daemon.
- [x] Shadow и настоящий запуск внутри CHR7.24.5.
- [x] Typed fenced intent, RAM heartbeat, owner/sequence/boot/config epochs.
- [x] Одна RouterOS точка записи маршрутов с тёплым native fallback.
- [x] SDK/GUI backend, отдельная подготовка и защищённая локальная установка.
- [x] Реальные TCP/NAT/SLA/failover, остановка/обрыв API/HB, competing owner и reboot.
- [x] Ошибки, отсутствие lease/metadata, преждевременный ACK и полный package rollback.
- [x] Проверка прав/ownership/mounts/пересечений и отсутствие idle flash writes.
- [x] Ресурсный замер, GUI и нативная регрессия, оба стенда очищены и запущены.

Результаты и точные ограничения — [CONTAINER-VALIDATION.md](CONTAINER-VALIDATION.md).
Установка — [CONTAINER.md](CONTAINER.md). Физические ARM/LTE и внедрение в
рабочую OSPF/VPN-схему остаются отдельными этапами, без автоматического продолжения.


Локальные `runtime/` отчёты, учётные данные и снимки устройств не входят в
репозиторий. Методика повторения проверок: [TESTING.md](TESTING.md).
