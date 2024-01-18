import asyncio

import aiohttp

from tasks.all_tasks import RabbitMqQueues
from core.wrappers import try_exc_async


class GetOrdersResults:
    __slots__ = 'app', 'clients', 'order_result', 'base_task'

    def __init__(self, app, base_task):
        self.app = app
        self.base_task = base_task

    @try_exc_async
    async def run(self, payload) -> None:
        for data in payload:
            if not self.base_task.clients.get(data['exchange']):
                continue
            if res := self.base_task.clients[data['exchange']].get_order_by_id(data['symbol'], data['order_ids']):
                await asyncio.sleep(2)
                print(f'GET_ORDER_BY_ID {data["exchange"]}: {res=}')
                await self.base_task.publish_message(connect=self.app['mq'],
                                                     message=res,
                                                     routing_key=RabbitMqQueues.UPDATE_ORDERS,
                                                     exchange_name=RabbitMqQueues.get_exchange_name(
                                                         RabbitMqQueues.UPDATE_ORDERS),
                                                     queue_name=RabbitMqQueues.UPDATE_ORDERS)


