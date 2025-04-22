import asyncio
import signal
import time
import os
from watchfiles import awatch

start_time = time.time()

async def watch(stop_event):
    async for changes in awatch('templates', stop_event=stop_event):
        print(f"watch elapsed: {(time.time() - start_time) * 1000:.2f} ms")
        print(changes)
        stop_event.set()

async def main():
    stop_event = asyncio.Event()

    # Setup signal handler for Ctrl-C
    def handle_sigint():
        print('Ctrl-C detected, stopping watcher...')
        stop_event.set()

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGINT, handle_sigint)
    loop.create_task(watch(stop_event))
    print(f"elapsed: {(time.time() - start_time) * 1000:.2f} ms")
    # create a file in templates
    with open('templates/test.txt', 'w') as f:
        f.write('test')
    print(f"elapsed2: {(time.time() - start_time) * 1000:.2f} ms")
    await stop_event.wait()
    print(f"elapsed3: {(time.time() - start_time) * 1000:.2f} ms")
    os.remove('templates/test.txt')
    print('Watcher stopped.')

asyncio.run(main())