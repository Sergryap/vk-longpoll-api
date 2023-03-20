import requests
import random
import redis
import json
import aiohttp
import asyncio

from pprint import pprint
from environs import Env
from textwrap import dedent
from time import sleep
from asgiref.sync import sync_to_async


async def get_long_poll_server(session: aiohttp.ClientSession, token: str, group_id: int, /):
    get_album_photos_url = 'https://api.vk.com/method/groups.getLongPollServer'
    params = {'access_token': token, 'v': '5.131', 'group_id': group_id}
    async with session.get(get_album_photos_url, params=params) as res:
        res.raise_for_status()
        response = json.loads(await res.text())
        key = response['response']['key']
        server = response['response']['server']
        ts = response['response']['ts']
        return key, server, ts


async def connect_server(session: aiohttp.ClientSession, key, server, ts):
    params = {'act': 'a_check', 'key': key, 'ts': ts, 'wait': 25}
    async with session.get(server, params=params) as res:
        res.raise_for_status()
        return json.loads(await res.text())


async def send_message(
        session: aiohttp.ClientSession,
        token: str,
        user_id: int,
        message: str,
        keyboard: str = None,
        attachment: str = None,
        payload: str = None,
        sticker_id: int = None,
        lat: str = None,
        long: str = None,
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
    for param, value in params.copy().items():
        if value is None:
            del params[param]
    async with session.post(send_message_url, params=params) as res:
        print(await res.text())
        res.raise_for_status()
        return json.loads(await res.text())


async def get_user(session: aiohttp.ClientSession, token: str, user_ids: str):
    get_users_url = 'https://api.vk.com/method/users.get'
    params = {
        'access_token': token, 'v': '5.131',
        'user_ids': user_ids
    }
    async with session.get(get_users_url, params=params) as res:
        res.raise_for_status()
        response = json.loads(await res.text())
        return response.get('response')


async def event_handler(session: aiohttp.ClientSession, token: str, event: dict, db: redis.Redis):
    """Главный обработчик событий"""

    user_id = event['object']['message']['from_id']
    start_buttons = ['start', '/start', 'начать', 'старт', '+']
    text = event['object']['message']['text'].lower().strip()
    payload = json.loads(event['object']['message'].get('payload', '{}'))
    if not db.get(f'{user_id}_first_name'):
        user_data = await get_user(session, token, user_id)
        if user_data:
            db.set(f'{user_id}_first_name', user_data[0].get('first_name'))
            db.set(f'{user_id}_last_name', user_data[0].get('last_name'))
    if text in start_buttons or payload.get('button') == 'start':
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

        await send_message(
            session,
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
    next_state = await state_handler(session, token, event, db)
    db.set(user_id, next_state)


async def start(session: aiohttp.ClientSession, token: str, event: dict, db: redis.Redis):
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
    await send_message(
        session,
        token=token,
        user_id=user_id,
        message='MENU:',
        keyboard=json.dumps(keyboard, ensure_ascii=False)
    )
    return 'MAIN_MENU'


async def main_menu_handler(session: aiohttp.ClientSession, token: str, event: dict, db: redis.Redis):
    if event['object']['message'].get('payload'):
        print(event['object']['message'].get('payload'))
        # return send_main_menu_answer(token, event, db)
    else:
        print(event['object']['message']['text'])
        # return answer_arbitrary_text(token, event, db)
    return 'START'


async def listen_server():
    env = Env()
    env.read_env()
    redis_password = env.str('REDIS_PASSWORD')
    redis_host = env.str('REDIS_HOST')
    redis_port = env.str('REDIS_PORT')
    redis_db = redis.Redis(host=redis_host, port=redis_port, password=redis_password)
    token = env.str('TOKEN')
    group_id = env.int('GROUP_ID')
    async with aiohttp.ClientSession() as session:
        key, server, ts = await get_long_poll_server(session, token, group_id)
        while True:
            try:
                response = await connect_server(session, key, server, ts)
                ts = response['ts']
                events = response['updates']
                pprint(events)
                for event in events:
                    if event['type'] != 'message_new':
                        continue
                    await event_handler(session, token, event, redis_db)
            except ConnectionError as err:
                sleep(5)
                print(err)
                continue
            except requests.exceptions.ReadTimeout as err:
                print(err)
                continue
            except Exception as err:
                print(err)


if __name__ == '__main__':

    asyncio.run(listen_server())
