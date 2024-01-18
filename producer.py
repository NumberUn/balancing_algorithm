import asyncio
import logging
from logging.config import dictConfig
import orjson
from aio_pika import connect, ExchangeType, Message
from tasks.all_tasks import PERIODIC_TASKS
from core.wrappers import try_exc_async

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


class WorkerProducer:
    def __init__(self, loop):
        self.loop = loop
        rabbit = config['RABBIT']
        self.rabbit_url = f"amqp://{rabbit['USERNAME']}:{rabbit['PASSWORD']}@{rabbit['HOST']}:{rabbit['PORT']}/"
        self.periodic_tasks = []

    @try_exc_async
    async def run(self):
        for task in PERIODIC_TASKS:
            self.periodic_tasks.append(self.loop.create_task(self._publishing_task(task)))

    @try_exc_async
    async def _publishing_task(self, task):
        if task['delay']:
            await asyncio.sleep(task['delay'])

        while True:
            connection = await connect(url=self.rabbit_url, loop=self.loop)

            channel = await connection.channel()

            exchange = await channel.declare_exchange(task['exchange'], type=ExchangeType.DIRECT, durable=True)
            queue = await channel.declare_queue(task['queue'], durable=True)
            await queue.bind(exchange, routing_key=task['routing_key'])

            message = Message(orjson.dumps(task['payload']) if task.get('payload') else b'{}')
            await exchange.publish(message, routing_key=task['routing_key'])

            logger.info(f'Published message to queue {task["queue"]}')

            await connection.close()

            await asyncio.sleep(task['interval'])


if __name__ == '__main__':
    loop = asyncio.get_event_loop()

    worker = WorkerProducer(loop)
    loop.run_until_complete(worker.run())

    loop.run_forever()
    loop.close()
