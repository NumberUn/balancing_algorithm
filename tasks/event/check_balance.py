import asyncio
import time
import uuid
from datetime import datetime

from tasks.all_tasks import RabbitMqQueues
from core.wrappers import try_exc_regular, try_exc_async


class CheckBalance:

    def __init__(self, app, base_task):
        self.base_task = base_task
        self.app = app

        self.chat_id = None
        self.env = None
        self.telegram_bot = None
        self.context = None
        self.parent_id = None
        self.balances = []
        self.positions = []

    @try_exc_async
    async def run(self, payload: dict) -> None:
        await asyncio.sleep(5)
        self.parent_id = payload['parent_id']
        self.context = payload['context']
        self.env = payload['env']
        self.chat_id = payload['chat_id']
        self.telegram_bot = payload['telegram_bot']

        await self.__check_balances()

    @try_exc_async
    async def __check_balances(self) -> None:
        for client in self.base_task.clients.values():
            balance_id = uuid.uuid4()
            await self.__save_balance(client, balance_id)
            for symbol in client.get_positions().copy():
                while not client.orderbook.get(symbol):
                    await asyncio.sleep(0.5)
                    client.orderbook[symbol] = await client.get_orderbook_by_symbol(symbol)
                await self.__save_balance_detalization(symbol, client, balance_id)

    @try_exc_async
    async def __save_balance(self, client, balance_id) -> None:
        sum_amount_usd = sum([x.get('amount_usd', 0) for _, x in client.get_positions().items()])
        balance = client.get_balance()
        current_margin = round(abs(sum_amount_usd / balance), 1) if balance else 0
        message = {
            'id': balance_id,
            'datetime': datetime.utcnow(),
            'ts': int(time.time() * 1000),
            'context': self.context,
            'parent_id': self.parent_id,
            'exchange': client.EXCHANGE_NAME,
            'exchange_balance': round(client.get_balance(), 1),
            'available_for_buy': round(client.get_available_balance()['buy'], 1),
            'available_for_sell': round(client.get_available_balance()['sell'], 1),
            'env': self.env,
            'chat_id': self.chat_id,
            'bot_token': self.telegram_bot,
            'current_margin': current_margin
        }

        await self.base_task.publish_message(connect=self.app['mq'],
                                             message=message,
                                             routing_key=RabbitMqQueues.BALANCES,
                                             exchange_name=RabbitMqQueues.get_exchange_name(RabbitMqQueues.BALANCES),
                                             queue_name=RabbitMqQueues.BALANCES
                                             )

    @try_exc_async
    async def __save_balance_detalization(self, symbol, client, parent_id):
        position = client.get_positions()[symbol]
        mark_price = (client.get_orderbook(symbol)['asks'][0][0] +
                      client.get_orderbook(symbol)['bids'][0][0]) / 2
        position_usd = round(position['amount'] * mark_price, 1)
        real_balance = client.get_balance()
        current_margin = round(abs(position['amount_usd'] / real_balance), 1) if real_balance else 0
        message = {
            'id': uuid.uuid4(),
            'datetime': datetime.utcnow(),
            'ts': int(time.time() * 1000),
            'context': self.context,
            'parent_id': parent_id,
            'exchange': client.EXCHANGE_NAME,
            'symbol': symbol,
            'current_margin': current_margin,
            'position_coin': position['amount'],
            'position_usd': position_usd,
            'entry_price': position['entry_price'],
            'mark_price': mark_price,
            'grand_parent_id': self.parent_id,
            'available_for_buy': round(real_balance * client.leverage - position_usd, 1),
            'available_for_sell': round(real_balance * client.leverage + position_usd, 1)
        }
        await self.base_task.publish_message(connect=self.app['mq'],
                                             message=message,
                                             routing_key=RabbitMqQueues.BALANCE_DETALIZATION,
                                             exchange_name=RabbitMqQueues.get_exchange_name(
                                                 RabbitMqQueues.BALANCE_DETALIZATION),
                                             queue_name=RabbitMqQueues.BALANCE_DETALIZATION
                                             )
