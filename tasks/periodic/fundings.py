import asyncio
import uuid

import aiohttp

from tasks.all_tasks import RabbitMqQueues
from tasks.base_task import BaseTask
from core.wrappers import try_exc_regular, try_exc_async

import configparser
import sys
config = configparser.ConfigParser()
config.read(sys.argv[1], "utf-8")


class Funding(BaseTask):
    __slots__ = 'clients', 'mq', 'session', 'app', 'env'

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.env = config['SETTINGS']['ENV']

    @try_exc_async
    async def run(self, payload: dict) -> None:
        async with aiohttp.ClientSession() as session:
            await self.__get_fundings(session)

    @try_exc_async
    async def __get_fundings(self, session) -> None:
        for client_name, client in self.clients.items():
            fundings = await client.get_funding_payments(session)
            for fund in fundings:
                if fund.get('datetime'):
                    await self.save_funding(fund, client_name)
                else:
                    print(fund)

    @try_exc_async
    async def save_funding(self, funding, exchange):
        message = {
            'id': uuid.uuid4(),
            'datetime': funding['datetime'],
            'ts': funding['time'],
            'exchange_funding_id': funding['tranId'],
            'exchange': exchange,
            'symbol': funding['market'],
            'amount': float(funding['payment']),
            'asset': funding['asset'],
            'position': float(funding['positionSize']),
            'price': float(funding['price'])
        }
        print(message)

        await self.publish_message(connect=self.app['mq'],
                                   message=message,
                                   routing_key=RabbitMqQueues.FUNDINGS,
                                   exchange_name=RabbitMqQueues.get_exchange_name(RabbitMqQueues.FUNDINGS),
                                   queue_name=RabbitMqQueues.FUNDINGS)


if __name__ == '__main__':
    from aio_pika import connect_robust
    from aiohttp.web import Application

    async def connect_to_rabbit():
        app['mq'] = await connect_robust(rabbit_url, loop=loop)
        # Other code that depends on the connection
    rabbit = config['RABBIT']
    rabbit_url = f"amqp://{rabbit['USERNAME']}:{rabbit['PASSWORD']}@{rabbit['HOST']}:{rabbit['PORT']}/"  # noqa
    app = Application()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(connect_to_rabbit())
    worker = Funding(app)
    loop.run_until_complete(worker.run({}))
