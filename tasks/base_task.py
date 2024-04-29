import orjson
from aio_pika import Message, ExchangeType, connect_robust
from clients.core.all_clients import ALL_CLIENTS
from core.wrappers import try_exc_async
import configparser
import sys
config = configparser.ConfigParser()
config.read(sys.argv[1], "utf-8")

leverage = float(config['SETTINGS']['LEVERAGE'])


class BaseTask:
    __slots__ = 'mq', 'clients', 'chat_id', 'chat_token', 'alert_id', 'alert_token', 'exchanges'

    def __init__(self):
        self.mq = None
        self.chat_id = int(config['TELEGRAM']['CHAT_ID'])
        self.chat_token = config['TELEGRAM']['TOKEN']
        self.alert_id = int(config['TELEGRAM']['ALERT_CHAT_ID'])
        self.exchanges = config['SETTINGS']['EXCHANGES'].split(',')
        self.clients = {}
        for exchange in self.exchanges:
            client = ALL_CLIENTS[exchange](keys=config[exchange], leverage=leverage, state='Balancer')
            self.clients.update({exchange: client})

    @staticmethod
    @try_exc_async
    async def publish_message(connect, message, routing_key, exchange_name, queue_name):
        channel = await connect.channel()
        exchange = await channel.declare_exchange(exchange_name, type=ExchangeType.DIRECT, durable=True)
        queue = await channel.declare_queue(queue_name, durable=True)
        await queue.bind(exchange, routing_key=routing_key)
        message_body = orjson.dumps(message)
        message = Message(message_body)
        await exchange.publish(message, routing_key=routing_key)
        await channel.close()
        return True

    @try_exc_async
    async def setup_mq(self, event_loop) -> None:
        rabbit = config['RABBIT']
        rabbit_url = f"amqp://{rabbit['USERNAME']}:{rabbit['PASSWORD']}@{rabbit['HOST']}:{rabbit['PORT']}/"
        self.mq = await connect_robust(rabbit_url, loop=event_loop)
        print('SETUP MQ')
