import asyncio
import logging
from logging.config import dictConfig
import time
import random
from tasks.base_task import BaseTask

import orjson
from aio_pika import connect_robust
from aiohttp.web import Application
from tasks.all_tasks import QUEUES_TASKS
from core.wrappers import try_exc_async, try_exc_regular


import configparser
import sys
config = configparser.ConfigParser()
config.read(sys.argv[1], "utf-8")


dictConfig({'version': 1, 'disable_existing_loggers': False, 'formatters': {
                'simple': {'format': '[%(asctime)s][%(threadName)s] %(funcName)s: %(message)s'}},
            'handlers': {'console': {'class': 'logging.StreamHandler', 'level': 'DEBUG', 'formatter': 'simple',
                'stream': 'ext://sys.stdout'}},
            'loggers': {'': {'handlers': ['console'], 'level': 'INFO', 'propagate': False}}})
logger = logging.getLogger(__name__)


class Consumer:
    """
    Producer get periodic and events tasks from RabbitMQ
    """

    def __init__(self, loop, queue=None):
        time.sleep(random.randint(1, 10))
        self.app = Application()
        self.loop = loop
        self.queue = queue
        rabbit = config['RABBIT']
        self.rabbit_url = f"amqp://{rabbit['USERNAME']}:{rabbit['PASSWORD']}@{rabbit['HOST']}:{rabbit['PORT']}/"  # noqa
        self.periodic_tasks = []
        self.base_task = BaseTask()

    @try_exc_async
    async def run(self) -> None:
        """
        Init setup mq connection and start getting tasks from queue
        :return: None
        """
        await self.setup_mq()

        logger.info(f"Queue: {self.queue}")
        logger.info(f"Exist queue: {self.queue in QUEUES_TASKS}")

        if self.queue and self.queue in QUEUES_TASKS:
            logger.info("Single work option")
            self.periodic_tasks.append(self.loop.create_task(self._consume(self.app['mq'], self.queue)))

    @try_exc_async
    async def setup_mq(self):
        self.app['mq'] = await connect_robust(self.rabbit_url, loop=self.loop)

    @try_exc_async
    async def _consume(self, connection, queue_name) -> None:
        channel = await connection.channel()
        queue = await channel.declare_queue(queue_name, durable=True)
        await queue.consume(self.on_message)

    @try_exc_async
    async def on_message(self, message) -> None:
        logger.info(f"\n\nReceived message {message.routing_key}")
        if 'logger.periodic' in message.routing_key:
            await message.ack()
        task = QUEUES_TASKS.get(message.routing_key)(self.app, self.base_task)
        await task.run(orjson.loads(message.body))
        logger.info(f"Success task {message.routing_key}")
        if 'logger.event' in message.routing_key:
            await message.ack()


if __name__ == '__main__':
    # parser = argparse.ArgumentParser()
    # parser.add_argument('-q', nargs='?', const=True, dest='queue', default='logger.periodic.get_missed_orders')
    # args = parser.parse_args()
    import multiprocessing

    @try_exc_regular
    def async_process(queue):
        loop = asyncio.get_event_loop()
        asyncio.set_event_loop(loop)

        worker = Consumer(loop, queue=queue)
        loop.run_until_complete(worker.run())
        loop.run_forever()
        loop.close()

    queues = config['SETTINGS']['QUEUES'].split(',')

    processes = []
    for queue in queues:
        process = multiprocessing.Process(target=async_process, args=(queue,))
        processes.append(process)
        process.start()

    for process in processes:
        process.join()


