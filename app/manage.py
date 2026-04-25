import asyncio
import sys
import os
import importlib

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)


async def main():
    if len(sys.argv) < 2:
        return

    cmd_name = sys.argv[1]
    try:
        module = importlib.import_module(f"scripts.{cmd_name}")
        command = module.Command()
        await command.run()
    except Exception as e:
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
