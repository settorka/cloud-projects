import argparse
import logging

from v1.settings import Settings


def main(*, fetch_references_locally=True):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "role", choices=["api", "ingest", "process", "references", "fetch", "import", "migrate"]
    )
    args = parser.parse_args()
    settings = Settings.load()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(message)s")
    from v1.telemetry import configure

    telemetry = configure(args.role) if args.role != "migrate" else None
    try:
        if args.role == "api":
            import uvicorn

            from v1.adapters.postgres import PostgresRepository
            from v1.api import create_app

            uvicorn.run(
                create_app(PostgresRepository(settings), settings, telemetry),
                host=settings.api_host,
                port=settings.api_port,
            )
        elif args.role == "migrate":
            from v1.adapters.migrate import migrate

            migrate(settings)
        else:
            from v1 import workers

            if args.role == "import":
                workers.reference_cycle(settings, do_fetch=False)
            elif args.role == "references":
                workers.reference_loop(settings, do_fetch=fetch_references_locally)
            else:
                {"ingest": workers.ingest, "process": workers.process, "fetch": workers.fetch}[
                    args.role
                ](settings)
    finally:
        if telemetry:
            telemetry.shutdown()


if __name__ == "__main__":
    main()
