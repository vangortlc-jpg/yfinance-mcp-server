import asyncio
import logging
from .server import main as server_main
from .server import main_sse as server_main_sse

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


def main() -> None:
    asyncio.run(server_main())


def main_sse() -> None:
    server_main_sse()


if __name__ == "__main__":
    main()
