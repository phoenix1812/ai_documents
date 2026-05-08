from app.logging_config import setup_logging
from app.worker import Worker


def main() -> None:
    setup_logging()

    worker = Worker()
    worker.run()


if __name__ == "__main__":
    main()