# Runbook index

Run commands from the project directory. Examples use `.env`; substitute `.env.example` for an unchanged demonstration configuration. Never paste tokens into shared incident reports.

- [Startup](local-startup.md)
- [Reset and stop](local-reset.md)
- [Booking failures](booking-failures.md)
- [Queue recovery](queue-recovery.md)
- [Market-data failures](market-data-failures.md)
- [Position reconciliation](position-reconciliation.md)
- [Valuation failures](valuation-failures.md)
- [Database backup and restore](database-backup-restore.md)
- [Load testing](load-testing.md)

Owner: the local developer. Diagnose first, contain the affected workflow, recover, verify business state, then record findings. Do not blindly replay messages, erase volumes or rerun requests with new keys after unknown outcomes.
