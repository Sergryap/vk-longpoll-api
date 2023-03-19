import requests
import random
import redis
import json

from pprint import pprint
from environs import Env
from textwrap import dedent





def get_long_poll_server(token: str, group_id: int, /):
    get_album_photos_url = 'https://api.vk.com/method/groups.getLongPollServer'
    params = {'access_token': token, 'v': '5.131', 'group_id': group_id}
    response = requests.get(get_album_photos_url, params=params)
    response.raise_for_status()
    key = response.json()['response']['key']
    server = response.json()['response']['server']
    ts = response.json()['response']['ts']
    return key, server, ts


def connect_server(key, server, ts):
    params = {'act': 'a_check', 'key': key, 'ts': ts, 'wait': 25}
    response = requests.get(server, params=params)
    response.raise_for_status()
    return response.json()


def send_message(
        token: str,
        user_id: int,
        message: str,
        keyboard: str = None,
        attachment: str = None,
        payload: str = None,
        sticker_id: int = None,
        lat: str = None,
        long: str = None
):
    send_message_url = 'https://api.vk.com/method/messages.send'
    params = {
        'access_token': token, 'v': '5.131',
        'user_id': user_id,
        'random_id': random.randint(0, 1000),
        'message': message,
        'attachment': attachment,
        'keyboard': keyboard,
        'payload': payload,
        'sticker_id': sticker_id,
        'lat': lat,
        'long': long
    }
    response = requests.post(send_message_url, params=params)
    response.raise_for_status()
    return response.json()


def get_user(token: str, user_ids: str):
    get_users_url = 'https://api.vk.com/method/users.get'
    params = {
        'access_token': token, 'v': '5.131',
        'user_ids': user_ids
    }
    response = requests.get(get_users_url, params=params)
    response.raise_for_status()
    return response.json().get('response')


def event_handler(token: str, event: dict, db: redis.Redis):
    """Главный обработчик событий"""

    user_id = event['object']['message']['from_id']
    start_buttons = ['start', '/start', 'начать', 'старт', '+']
    text = event['object']['message']['text'].lower().strip()
    if not db.get(f'{user_id}_first_name'):
        user_data = get_user(token, user_id)
        if user_data:
            db.set(f'{user_id}_first_name', user_data[0].get('first_name'))
            db.set(f'{user_id}_last_name', user_data[0].get('last_name'))
    if text in start_buttons:
        user_state = 'START'
        msg = f'''
            Привет, я бот этого чата.
            Здесь вы можете узнать всю актуальную информацию о наших курсах и при желании оставить заявку.
            Для записи на курс нажмите:
            "Предстоящие курсы"             
            '''
        button = [
            [
                {
                    'action': {'type': 'text', 'payload': {'button': 'start'}, 'label': '☰ MENU'},
                    'color': 'positive'
                }
            ]
        ]
        keyboard = {'inline': False, 'buttons': button}
        send_message(
            token=token,
            user_id=user_id,
            message=dedent(msg),
            keyboard=json.dumps(keyboard, ensure_ascii=False)
        )
    else:
        user_state = db.get(user_id).decode("utf-8")
        print(user_state)

    states_functions = {
        'START': start,
        'MAIN_MENU': main_menu_handler,
        # 'COURSE': handle_course_info,
        # 'PHONE': enter_phone,
    }
    state_handler = states_functions[user_state]
    next_state = state_handler(token, event, db)
    db.set(user_id, next_state)


def start(token: str, event: dict, db: redis.Redis):
    user_id = event['object']['message']['from_id']
    start_buttons = [
        ('Предстоящие курсы', 'future_courses'),
        ('Ваши курсы', 'client_courses'),
        ('Прошедшие курсы', 'past_courses'),
        ('Написать администратору', 'admin_msg'),
        ('Как нас найти', 'search_us')
    ]
    buttons = []
    for label, payload in start_buttons:
        buttons.append(
            [
                {
                    'action': {'type': 'text', 'payload': {'button': payload}, 'label': label},
                    'color': 'secondary'
                }
            ],
        )
    keyboard = {'inline': True, 'buttons': buttons}

    send_message(
        token=token,
        user_id=user_id,
        message='MENU:',
        keyboard=json.dumps(keyboard, ensure_ascii=False)
    )
    return 'MAIN_MENU'


def main_menu_handler(token: str, event: dict, db: redis.Redis):
    if event['object']['message'].get('payload'):
        print(event['object']['message'].get('payload'))
        # return send_main_menu_answer(token, event, db)
    else:
        print(event['object']['message']['text'])
        # return answer_arbitrary_text(token, event, db)
    return 'START'


def listen_server(token: str, group_id: int, db: redis.Redis, /):
    key, server, ts = get_long_poll_server(token, group_id)
    while True:
        response = connect_server(key, server, ts)
        ts = response['ts']
        events = response['updates']
        for event in events:
            if event['type'] in ['message_typing_state', 'message_reply']:
                continue
            event_handler(token, event, db)


if __name__ == '__main__':
    env = Env()
    env.read_env()
    redis_password = env.str('REDIS_PASSWORD')
    redis_host = env.str('REDIS_HOST')
    redis_port = env.str('REDIS_PORT')
    redis_db = redis.Redis(host=redis_host, port=redis_port, password=redis_password)
    TOKEN = env.str('TOKEN')
    GROUP_ID = env.int('GROUP_ID')
    listen_server(TOKEN, GROUP_ID, redis_db)
