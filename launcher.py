# extremely old code (2+ years)

import asyncio
import logging
import multiprocessing
import signal
import os
import sys
import time
import requests

from bot import ClusterBot

TOKEN = "tokenHere"

shardsPerCluster = 20 # how many shards you'd like per cluster e.g. cluster 1 = shard 0-14, cluster 2 = shard 15-29, etc.
shardCount = "auto" # keep as "auto" if you want to automatically get the shard count from discord, otherwise set to a number.

log = logging.getLogger("Cluster#Launcher")
log.setLevel(logging.DEBUG)
hdlr = logging.StreamHandler()
hdlr.setFormatter(logging.Formatter("[Launcher] %(message)s"))
log.handlers = [hdlr]


CLUSTER_NAMES = (
    'Alpha', 'Beta', 'Charlie', 'Delta', 'Echo', 'Foxtrot', 'Golf', 'Hotel',
    'India', 'Juliett', 'Kilo', 'Mike', 'November', 'Oscar', 'Papa', 'Quebec',
    'Romeo', 'Sierra', 'Tango', 'Uniform', 'Victor', 'Whisky', 'X-ray', 'Yankee', 'Zulu'
)
NAMES = iter(CLUSTER_NAMES)


class Launcher:
    def __init__(self, loop, *, ipc=False):
        log.info("Cluster Launcher Starting")
        self.cluster_queue = []
        self.clusters = []

        self.fut = None
        self.loop = loop
        self.alive = True

        self.keep_alive = None
        self.init = time.perf_counter()

        self.start_ipc = ipc
        self.ipc = None

    def get_shard_count(self):
        if shardCount != "auto":
            return int(shardCount)
        else:
            data = requests.get('https://discordapp.com/api/v7/gateway/bot', headers={
                "Authorization": "Bot "+TOKEN,
                "User-Agent": "DiscordBot (https://github.com/Rapptz/discord.py 1.3.0a) Python/3.7 aiohttp/3.6.1"
            })
            data.raise_for_status()
            content = data.json()
            log.info(f"Successfully got shard count of {content['shards']} ({data.status_code, data.reason})")
            #return 16
            return content['shards']

    def start(self):
        self.fut = asyncio.ensure_future(self.startup(), loop=self.loop)

        try:
            self.loop.run_forever()
        except KeyboardInterrupt:
            self.loop.run_until_complete(self.shutdown())
        finally:
            self.cleanup()

    def cleanup(self):
        self.loop.stop()
        if sys.platform == 'win32':
            print("press ^C again")
        self.loop.close()

    def task_complete(self, task):
        if task.exception():
            task.print_stack()
            self.keep_alive = self.loop.create_task(self.rebooter())
            self.keep_alive.add_done_callback(self.task_complete)

    async def startup(self):
        if self.start_ipc:
            log.info("IPC server starting up")
            import ipc  # pylint: disable=import-outside-toplevel
            self.ipc = multiprocessing.Process(target=ipc.start, daemon=True)
            self.ipc.start()
        shards = list(range(self.get_shard_count()))
        size = [shards[x:x + shardsPerCluster] for x in range(0, len(shards), shardsPerCluster)]
        log.info(f"Preparing {len(size)} clusters")
        for shard_ids in size:
            self.cluster_queue.append(Cluster(self, next(NAMES), shard_ids, len(shards)))

        await self.start_cluster()
        self.keep_alive = self.loop.create_task(self.rebooter())
        self.keep_alive.add_done_callback(self.task_complete)
        log.info(f"Startup completed in {time.perf_counter()-self.init}s")

    async def shutdown(self):
        log.info("Shutting down clusters")
        self.alive = False
        if self.keep_alive:
            self.keep_alive.cancel()
        for cluster in self.clusters:
            cluster.stop()
        self.cleanup()
        if self.ipc and self.ipc.is_alive():
            os.kill(self.ipc.pid, signal.SIGINT)

    # return the name of the cluster    
    def get_cluster_name(self):
        return self.clusters[0].name

    async def rebooter(self):
        while self.alive:
            # log.info("Cycle!")
            if not self.clusters:
                log.warning("All clusters appear to be dead")
                asyncio.ensure_future(self.shutdown())
            if self.ipc and not self.ipc.is_alive():
                log.critical("IPC websocket server dead, require reboot")
                self.ipc = None
            to_remove = []
            for cluster in self.clusters:
                if not cluster.process.is_alive():
                    if cluster.process.exitcode != 0:
                        # ignore safe exits
                        log.info(f"Cluster#{cluster.name} exited with code {cluster.process.exitcode}")
                        log.info(f"Restarting cluster#{cluster.name}")
                        await cluster.start()
                    else:
                        log.info(f"Cluster#{cluster.name} found dead")
                        to_remove.append(cluster)
                        cluster.stop()  # ensure stopped
            for rem in to_remove:
                self.clusters.remove(rem)
            await asyncio.sleep(5)

    async def start_cluster(self):
        if self.cluster_queue:
            cluster = self.cluster_queue.pop(0)
            log.info(f"Starting Cluster#{cluster.name}")
            await cluster.start()
            log.info("Done!")
            self.clusters.append(cluster)
            await self.start_cluster()
        else:
            log.info("All clusters launched")


class Cluster:
    def __init__(self, launcher, name, shard_ids, max_shards):
        self.launcher = launcher
        self.process = None
        self.kwargs = dict(
            token=TOKEN,
            command_prefix="-",
            shard_ids=shard_ids,
            shard_count=max_shards,
            cluster_name=name
        )
        self.name = name
        self.log = logging.getLogger(f"Cluster#{name}")
        self.log.setLevel(logging.DEBUG)
        hdlr = logging.StreamHandler()
        hdlr.setFormatter(logging.Formatter("[Cluster] %(message)s"))
        self.log.handlers = [hdlr]
        self.log.info(f"Initialized with shard ids {shard_ids}, total shards {max_shards}")

    def wait_close(self):
        return self.process.join()

    

    async def start(self, *, force=False):
        if self.process and self.process.is_alive():
            if not force:
                self.log.warning("Start called with already running cluster, pass `force=True` to override")
                return
            self.log.info("Terminating existing process")
            self.process.terminate()
            self.process.close()

        stdout, stdin = multiprocessing.Pipe()
        kw = self.kwargs
        kw['pipe'] = stdin
        self.process = multiprocessing.Process(target=ClusterBot, kwargs=kw, daemon=True)
        self.process.start()
        self.log.info(f"Process started with PID {self.process.pid}")

        if await self.launcher.loop.run_in_executor(None, stdout.recv) == 1:
            stdout.close()
            self.log.info("Process started successfully")

        return True

    def stop(self, sign=signal.SIGINT):
        self.log.info(f"Shutting down with signal {sign!r}")
        try:
            os.kill(self.process.pid, sign)
        except ProcessLookupError:
            pass


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    Launcher(loop).start()
