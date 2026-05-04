import asyncio
import sys
import os
import importlib
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)


async def main():
    if len(sys.argv) < 2:
        logger.warning("No command name provided to script runner")
        return

    cmd_name = sys.argv[1]
    try:
        module = importlib.import_module(f"scripts.{cmd_name}")
        command = module.Command()
        logger.info(f"Running command: {cmd_name}")
        await command.run()
    except Exception as e:
        logger.critical(
            f"Failed to execute command '{cmd_name}': {str(e)}", exc_info=True
        )
        import traceback


if __name__ == "__main__":
    asyncio.run(main())
