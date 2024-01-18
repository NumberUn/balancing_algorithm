import requests
from enum import Enum

from configparser import ConfigParser

config = ConfigParser()
config.read('config.ini', "utf-8")


class TG_Groups(Enum):
    _main_id = int(config['TELEGRAM']['CHAT_ID'])
    _main_token = config['TELEGRAM']['TOKEN']
    _alert_id = int(config['TELEGRAM']['ALERT_CHAT_ID'])

    MainGroup = {'chat_id': _main_id, 'bot_token': _main_token}
    Alerts = {'chat_id': _alert_id, 'bot_token': _main_token}


class Telegram:
    def __init__(self):
        self.tg_url = "https://api.telegram.org/bot"

    def send_message(self, message: str, group_obj: TG_Groups = None):
        group = group_obj.value if group_obj else TG_Groups.MainGroup.value
        url = self.tg_url + group['bot_token'] + "/sendMessage"
        message_data = {"chat_id": group['chat_id'], "parse_mode": "HTML", "text": "<pre>" + str(message) + "</pre>"}
        try:
            r = requests.post(url, json=message_data)
            return r.json()
        except Exception as e:
            return e
