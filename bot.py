import re
from datetime import timedelta
import discord
from discord.ext import commands
import requests
import asyncio
import logging


class ClusterBot(commands.AutoShardedBot):
    def __init__(self, **kwargs):
        self.pipe = kwargs.pop('pipe')
        self.cluster_name = kwargs.pop('cluster_name')

        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        super().__init__(**kwargs, loop=loop)
        self.websocket = None
        self._last_result = None
        self.ws_task = None
        self.responses = asyncio.Queue()
        log = logging.getLogger(f"Cluster#{self.cluster_name}")
        log.setLevel(logging.DEBUG)
        log.handlers = [logging.FileHandler(f'cluster-{self.cluster_name}.log', encoding='utf-8', mode='a')]
        log.info(f'[Cluster#{self.cluster_name}] {kwargs["shard_ids"]}, {kwargs["shard_count"]}')
        self.log = log
        self.run(kwargs['token'])
        #self.loop.create_task(self.ensure_ipc())

    async def on_ready(self, **kwargs):
        print("[Client] All Shards Loaded!")
        self.pipe.send(1)
        self.pipe.close()
        #keep_alive()
    

  
    async def close(self, *args, **kwargs):
        self.log.info("shutting down")
        await self.websocket.close()
        await super().close()
    


    async def on_shard_ready(self, shard_id):
        self.log.info(f'[Cluster#{self.cluster_name}] Shard {shard_id} ready')
    

