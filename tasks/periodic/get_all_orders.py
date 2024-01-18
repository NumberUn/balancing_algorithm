import aiohttp

from tasks.all_tasks import RabbitMqQueues
from tasks.base_task import BaseTask
from core.wrappers import try_exc_regular, try_exc_async


class GetMissedOrders(BaseTask):

    def __init__(self, app):
        super().__init__()
        self.app = app

    @try_exc_async
    async def run(self, payload: dict) -> None:
        orders = []

        async with aiohttp.ClientSession() as session:
            for client in self.clients.values():
                orders += await client.get_all_orders(payload[client.EXCHANGE_NAME], session)

        # print(orders)
        for order in orders:
            if 'web-' in order['context']:
                await self.publish_message(connect=self.app['mq'],
                                           message=order,
                                           routing_key=RabbitMqQueues.ORDERS,
                                           exchange_name=RabbitMqQueues.get_exchange_name(RabbitMqQueues.ORDERS),
                                           queue_name=RabbitMqQueues.ORDERS
                                           )
