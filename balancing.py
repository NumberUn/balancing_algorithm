import asyncio
import time
import traceback
from datetime import datetime
import uuid
import aiohttp
from tasks.all_tasks import RabbitMqQueues
from tasks.base_task import BaseTask
import configparser
import sys
from core.wrappers import try_exc_regular, try_exc_async
import random
from core.telegram import Telegram, TG_Groups

config = configparser.ConfigParser()
config.read(sys.argv[1], "utf-8")


class Balancing(BaseTask):
    __slots__ = 'clients', 'positions', 'total_position', 'disbalances', \
                'side', 'mq', 'session', 'open_orders', 'app', \
                'chat_id', 'chat_token', 'env', 'disbalance_id', 'average_price', \
                'orderbooks', 'telegram', 'last_positions', 'last_tot_balance' # noqa

    def __init__(self):
        super().__init__()
        self.positions = {}
        self.last_positions = {}
        self.last_tot_balance = 1
        self.__set_default()
        self.telegram = Telegram()
        self.orderbooks = {}
        self.env = config['SETTINGS']['ENV']

        time.sleep(15)

    @try_exc_async
    async def run(self, loop) -> None:
        print('START BALANCING')
        async with aiohttp.ClientSession() as session:
            while True:
                await self.setup_mq(loop)
                for exchange, client in self.clients.items():
                    client.get_position()
                await self.__close_all_open_orders()
                await self.update_balances()
                await self.__get_positions()
                await self.__get_total_positions()
                await self.send_positions_message(self.create_positions_message())
                if self.check_for_empty_positions():
                    await self.__balancing_positions(session)
                else:
                    message = f"ALERT: SIGNIFICANT POSITIONS CHANGE. SKIP BALANCING.\n"
                    message += f"POSES: {self.positions}\nLAST POSES: {self.last_positions}"
                    self.telegram.send_message(message, TG_Groups.Alerts)
                print(f"MQ CLOSED")
                await self.mq.close()
                self.__set_default()
                time.sleep(int(config['SETTINGS']['TIMEOUT']))

    @try_exc_regular
    def __set_default(self) -> None:
        self.last_positions = self.positions
        self.positions = {}
        self.open_orders = {}
        self.total_position = 0
        self.disbalances = {}
        self.disbalance_id = uuid.uuid4()

    @try_exc_async
    async def update_balances(self):
        for client_name, client in self.clients.items():
            client.get_real_balance()

    @try_exc_async
    async def __get_positions(self):
        for client_name, client in self.clients.items():
            for symbol, position in client.get_positions().items():
                coin = [i for i in client.markets.keys() if client.markets[i] == symbol][0]
                # orderbook = self.orderbooks[client_name][symbol]
                position.update({'symbol': symbol})
                if not self.positions.get(coin):
                    self.positions.update({coin: {client_name: position}})
                else:
                    self.positions[coin].update({client_name: position})

    @try_exc_regular
    def check_for_empty_positions(self):
        for client in self.clients.values():
            if not client.get_positions():
                return False
        # len_new_pos = 0
        # len_old_pos = 0
        # for positions in self.positions.values():
        #     len_new_pos += len(list(positions))
        # for positions in self.last_positions.values():
        #     len_old_pos += len(list(positions))
        # if abs(len_old_pos - len_new_pos) >= 3:
        #
        return True

    @staticmethod
    @try_exc_regular
    def get_coin(symbol: str):
        coin = ''
        if '_' in symbol:
            coin = symbol.split('_')[1].upper().split('USD')[0]
        elif '-' in symbol:
            coin = symbol.split('-')[0]
        elif 'USDT' in symbol:
            coin = symbol.split('USD')[0]
        return coin

    @try_exc_async
    async def get_mark_price(self, coin: str) -> float:
        clients_list = list(self.clients.values())
        random_client = clients_list[random.randint(0, len(clients_list) - 1)]
        if market := random_client.markets.get(coin):
            ob = await random_client.get_orderbook_by_symbol(market)
            if ob and ob.get('asks') and ob.get('bids'):
                random_client.orderbook[market] = ob
            else:
                ob = random_client.get_orderbook(market)
            mark_price = (ob['asks'][0][0] + ob['bids'][0][0]) / 2
            return mark_price
        else:
            for client in clients_list:
                if market := client.markets.get(coin):
                    ob = await client.get_orderbook_by_symbol(market)
                    if ob and ob.get('asks') and ob.get('bids'):
                        client.orderbook[market] = ob
                    else:
                        ob = client.get_orderbook(market)
                    mark_price = (ob['asks'][0][0] + ob['bids'][0][0]) / 2
                    return mark_price

    @try_exc_async
    async def __get_total_positions(self) -> None:
        for coin, exchanges in self.positions.items():
            mark_price = await self.get_mark_price(coin)
            pos_sum = {'coin': 0, 'usd': 0}
            for exchange, position in exchanges.items():
                pos_sum['coin'] += position['amount']
                pos_sum['usd'] += position['amount'] * mark_price
            self.disbalances.update({coin: pos_sum})  # noqa

    @try_exc_regular
    def create_positions_message(self) -> str:
        refactored_positions = {}
        for coin, exchanges in self.positions.items():
            for exchange, position in exchanges.items():
                if refactored_positions.get(exchange):
                    refactored_positions[exchange]['total_position'] += int(round(position['amount_usd']))
                    refactored_positions[exchange]['abs_position'] += abs(int(round(position['amount_usd'])))
                    refactored_positions[exchange]['num_positions'] += 1
                else:
                    refactored_positions.update({exchange: {'total_position': int(round(position['amount_usd'])),
                                                            'abs_position': abs(int(round(position['amount_usd']))),
                                                            'num_positions': 1}})
        return self.compose_message(refactored_positions)

    @try_exc_regular
    def compose_message(self, refactored_positions: dict) -> str:
        tot_pos = 0
        abs_pos = 0
        message = "    POSITIONS:"
        for exchange, data in refactored_positions.items():
            tot_pos += data['total_position']
            abs_pos += data['abs_position']
            message += f"\n  {exchange}"
            message += f"\nTOT POS, USD: {data['total_position']}"
            message += f"\nABS POS, USD: {data['abs_position']}"
            message += f"\nPOSITIONS, NUM: {data['num_positions']}"
        total_balance = 0
        message += f"\n    BALANCES:"
        for exc_name, client in self.clients.items():
            exc_bal = client.get_balance()
            message += f"\n{exc_name}, USD: {int(round(exc_bal, 0))}"
            total_balance += exc_bal
        message += f"\n    TOTAL:"
        message += f"\nBALANCE, USD: {int(round(total_balance, 0))}"
        message += f"\nTOT POSITION, USD: {tot_pos}"
        message += f"\nABS POSITION, USD: {abs_pos}"
        message += f"\nEFFECTIVE LEVERAGE: {round(abs_pos / total_balance, 2)}"
        for coin, disbalance in self.disbalances.items():
            if abs(disbalance['usd']) > int(config['SETTINGS']['MIN_DISBALANCE']):
                message += f"\nDISB, {coin}: {round(disbalance['coin'], 4)}"
                message += f" (USD: {int(round(disbalance['usd'], 0))})"
        if total_balance / self.last_tot_balance <= 0.99:
            message += f"\n\nALERT! SIGNIFICANT BALANCE CHANGE: {self.last_tot_balance} -> {total_balance}"
        self.last_tot_balance = total_balance
        return message

    @try_exc_async
    async def send_positions_message(self, message: str) -> None:
        send_message = {
            "chat_id": self.chat_id,
            "msg": message,
            'bot_token': self.chat_token
        }
        await self.publish_message(connect=self.mq,
                                   message=send_message,
                                   routing_key=RabbitMqQueues.TELEGRAM,
                                   exchange_name=RabbitMqQueues.get_exchange_name(RabbitMqQueues.TELEGRAM),
                                   queue_name=RabbitMqQueues.TELEGRAM)

    @try_exc_async
    async def __close_all_open_orders(self) -> None:
        for _, client in self.clients.items():
            client.cancel_all_orders()

    @try_exc_async
    async def get_top_price_exchange(self, amount: float, exchanges: list, coin: str, side: str) -> list:
        top_exchange = None
        best_price = None
        for exchange in exchanges:
            symbol = self.clients[exchange].markets[coin]
            tick = self.clients[exchange].instruments[symbol]['tick_size']
            ob = await self.clients[exchange].get_orderbook_by_symbol(symbol)
            self.clients[exchange].orderbook[symbol] = ob
            if side == 'buy':
                pretend_price = ob['asks'][0][0] + 5 * tick
                top_exchange = exchange
                if best_price:
                    if pretend_price < best_price:
                        top_exchange = exchange
                        best_price = pretend_price
                else:
                    top_exchange = exchange
                    best_price = pretend_price
            else:
                pretend_price = ob['bids'][0][0] - 5 * tick
                top_exchange = exchange
                if best_price:
                    if pretend_price > best_price:
                        top_exchange = exchange
                        best_price = pretend_price
                else:
                    top_exchange = exchange
                    best_price = pretend_price
        if top_exchange:
            symbol = self.clients[top_exchange].markets[coin]
            price, size = self.clients[top_exchange].fit_sizes(best_price, amount, symbol)
            return top_exchange, price, size
        return None, None, None

        # max_amount = max([client.expect_amount_coin for client in self.clients.values()])
        #
        # for client in self.clients.values():
        #     client.expect_amount_coin = max_amount

    @try_exc_async
    async def __balancing_positions(self, session: aiohttp.ClientSession) -> None:
        for coin, disbalance in self.disbalances.items():
            if abs(disbalance['usd']) > int(config['SETTINGS']['MIN_DISBALANCE']):
                print(coin, disbalance)
                side = 'sell' if disbalance['usd'] > 0 else 'buy'
                self.disbalance_id = uuid.uuid4()  # noqa
            else:
                continue
            exchange, price, size = await self.get_exchange_and_price(abs(disbalance['coin']), coin, side)
            print(f"BALANCING ON {exchange=}")
            if exchange:
                print(f"{exchange} BALANCING COIN FOR: {size}")
                symbol = self.clients[exchange].markets[coin]
                client_id = f"api_balancing_{str(uuid.uuid4()).replace('-', '')[:20]}"
                time_sent = time.time()
                result = await self.clients[exchange].create_order(symbol=symbol, side=side, price=price, size=size,
                                                                   session=session, client_id=client_id)
                await self.save_orders(result, price, size, coin, side, time_sent)
                await self.save_disbalance(coin, price)
                await self.save_balance()
                await self.send_balancing_message(exchange, coin, side, size, price)
            await asyncio.sleep(1)

    @try_exc_async
    async def get_exchange_and_price(self, size: float, coin: str, side: str) -> str:
        exchanges = []
        for ex, client in self.clients.items():
            try:
                mrkt = client.markets[coin]
                if client.instruments[mrkt]['min_size'] <= abs(size):
                    av_balances = client.get_available_balance()
                    av_coin = av_balances.get(mrkt, {}).get(side)
                    if not av_coin:
                        av_coin = av_balances.get(side)
                    print(f"{mrkt=} {av_coin=}")
                    if av_coin > 0:
                        ob = await client.get_orderbook_by_symbol(mrkt)
                        change = ob['asks'][0][0] + ob['bids'][0][0]
                        print(f"{size=} {size * change}")
                        if av_coin >= size * change:
                            exchanges.append(ex)
                        elif av_coin >= size * change * 0.99:
                            exchanges.append(ex)
                            size = size * 0.99
            except:
                traceback.print_exc()
        if not len(exchanges):
            for ex, client in self.clients.items():
                mrkt = client.markets[coin]
                if not client.instruments.get(mrkt) and ex == 'BITKUB':
                    continue
                if client.instruments[mrkt]['min_size'] <= abs(size):
                    av_balances = client.get_available_balance()
                    av_coin = av_balances.get(mrkt, {}).get(side)
                    if not av_coin:
                        av_coin = av_balances.get(side)
                    if av_coin > 0:
                        ob = client.get_orderbook(mrkt)
                        change = ob['asks'][0][0] + ob['bids'][0][0]
                        size = av_coin / change
                        exchanges.append(ex)
        print(exchanges)
        top_exchange, price, size = await self.get_top_price_exchange(size, exchanges, coin, side)
        return top_exchange, price, size

    @try_exc_async
    async def send_balancing_message(self, exchange: str, coin: str, side: str, size: float, price: float) -> None:
        message = 'BALANCING PROCEED:\n'
        message += f"COIN: {coin}\n"
        message += f"SIDE: {side}\n"
        message += f"{exchange} ORDER SIZE, {coin}: {size}\n"
        message += f"{exchange} PRICE: {price}\n"
        send_message = {
            "chat_id": self.chat_id,
            "msg": message,
            'bot_token': self.chat_token
        }
        await self.publish_message(connect=self.mq,
                                   message=send_message,
                                   routing_key=RabbitMqQueues.TELEGRAM,
                                   exchange_name=RabbitMqQueues.get_exchange_name(RabbitMqQueues.TELEGRAM),
                                   queue_name=RabbitMqQueues.TELEGRAM)

    @try_exc_async
    async def save_balance(self) -> None:
        message = {
            'parent_id': self.disbalance_id,
            'context': 'post-balancing',
            'env': self.env,
            'chat_id': self.chat_id,
            'telegram_bot': self.chat_token,
        }
        await self.publish_message(connect=self.mq,
                                   message=message,
                                   routing_key=RabbitMqQueues.CHECK_BALANCE,
                                   exchange_name=RabbitMqQueues.get_exchange_name(RabbitMqQueues.CHECK_BALANCE),
                                   queue_name=RabbitMqQueues.CHECK_BALANCE)

    @try_exc_async
    async def save_orders(self, res: dict, expect_price: float, amount: float, coin: str,  side: str, time_sent: float):
        exchange = res['exchange_name']
        client = self.clients[exchange]
        order_id = uuid.uuid4()
        message = {
            'id': order_id,
            'datetime': datetime.utcnow(),
            'ts': int(time.time() * 1000),
            'context': 'balancing',
            'parent_id': self.disbalance_id,
            'exchange_order_id': client.LAST_ORDER_ID,
            'type': 'GTT' if client.EXCHANGE_NAME == 'DYDX' else 'GTC',
            'status': 'Processing',
            'exchange_name': client.EXCHANGE_NAME,
            'side': side,
            'symbol': client.markets[coin],
            'expect_price': expect_price,
            'expect_amount_coin': amount,
            'expect_amount_usd': amount * expect_price,
            'expect_fee': client.taker_fee * (amount * expect_price),
            'factual_price': 0,
            'factual_amount_coin': 0,
            'factual_amount_usd': 0,
            'factual_fee': client.taker_fee,
            'order_place_time': res['timestamp'],
            'env': self.env,
            'oneway_ping_orderbook': 0,
            'oneway_ping_order': res['timestamp'] / 1000 - time_sent,
            'inner_ping': 0}

        if client.LAST_ORDER_ID == 'default':
            error_message = {
                "chat_id": self.chat_id,
                "msg": f"ALERT NAME: Order Mistake\nCOIN: {coin}\nCONTEXT: BOT\nENV: {self.env}\nEXCHANGE: "
                       f"{client.EXCHANGE_NAME}\nOrder Id:{order_id}\nError:{client.error_info}",
                'bot_token': self.chat_token
            }
            await self.publish_message(connect=self.mq,
                                       message=error_message,
                                       routing_key=RabbitMqQueues.TELEGRAM,
                                       exchange_name=RabbitMqQueues.get_exchange_name(RabbitMqQueues.TELEGRAM),
                                       queue_name=RabbitMqQueues.TELEGRAM)
            client.error_info = None

        await self.publish_message(connect=self.mq,
                                   message=message,
                                   routing_key=RabbitMqQueues.ORDERS,
                                   exchange_name=RabbitMqQueues.get_exchange_name(RabbitMqQueues.ORDERS),
                                   queue_name=RabbitMqQueues.ORDERS)

    @try_exc_async
    async def save_disbalance(self, coin: str, price: float) -> None:
        message = {
            'id': self.disbalance_id,
            'datetime': datetime.utcnow(),
            'ts': int(datetime.utcnow().timestamp() * 1000),
            'coin_name': coin,
            'position_coin': self.disbalances[coin]['coin'],
            'position_usd': round(self.disbalances[coin]['usd'], 1),
            'price': price,
            'threshold': float(config['SETTINGS']['MIN_DISBALANCE']),
            'status': 'Processing'
        }

        await self.publish_message(connect=self.mq,
                                   message=message,
                                   routing_key=RabbitMqQueues.DISBALANCE,
                                   exchange_name=RabbitMqQueues.get_exchange_name(RabbitMqQueues.DISBALANCE),
                                   queue_name=RabbitMqQueues.DISBALANCE)


if __name__ == '__main__':
    worker = Balancing()
    loop = asyncio.new_event_loop()
    loop.run_until_complete(worker.run(loop))
