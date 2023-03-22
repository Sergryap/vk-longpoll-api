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
from more_itertools import chunked

from buttons import get_start_buttons, get_menu_button, get_course_buttons


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
        connect,
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
        'access_token': connect['token'], 'v': '5.131',
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
    async with connect['session'].post(send_message_url, params=params) as res:
        print(await res.text())
        res.raise_for_status()
        return json.loads(await res.text())


async def get_user(connect, user_ids: str):
    get_users_url = 'https://api.vk.com/method/users.get'
    params = {
        'access_token': connect['token'], 'v': '5.131',
        'user_ids': user_ids
    }
    async with connect['session'].get(get_users_url, params=params) as res:
        res.raise_for_status()
        response = json.loads(await res.text())
        return response.get('response')


async def event_handler(connect, event):
    """Главный обработчик событий"""

    user_id = event['object']['message']['from_id']
    start_buttons = ['start', '/start', 'начать', 'старт', '+']
    text = event['object']['message']['text'].lower().strip()
    payload = json.loads(event['object']['message'].get('payload', '{}'))
    if not connect['redis_db'].get(f'{user_id}_first_name'):
        user_data = await get_user(connect, user_id)
        if user_data:
            connect['redis_db'].set(f'{user_id}_first_name', user_data[0].get('first_name'))
            connect['redis_db'].set(f'{user_id}_last_name', user_data[0].get('last_name'))
    if text in start_buttons or payload.get('button') == 'start':
        user_state = 'START'
        msg = f'''
            Привет, я бот этого чата.
            Здесь вы можете узнать всю актуальную информацию о наших курсах и при желании оставить заявку.
            Для записи на курс нажмите:
            "Предстоящие курсы"             
            '''
        await send_message(
            connect,
            user_id=user_id,
            message=dedent(msg),
            keyboard=await get_menu_button(color='positive', inline=False)
        )
    else:
        user_state = connect['redis_db'].get(user_id).decode("utf-8")
        print(user_state)

    states_functions = {
        'START': start,
        'MAIN_MENU': main_menu_handler,
        # 'COURSE': handle_course_info,
        # 'PHONE': enter_phone,
    }
    state_handler = states_functions[user_state]
    next_state = await state_handler(connect, event)
    connect['redis_db'].set(user_id, next_state)


async def start(connect, event):
    user_id = event['object']['message']['from_id']
    await send_message(
        connect,
        user_id=user_id,
        message='MENU:',
        keyboard=await get_start_buttons()
    )
    return 'MAIN_MENU'


async def main_menu_handler(connect, event):
    payload = json.loads(event['object']['message'].get('payload', '{}'))
    if payload:
        return await send_main_menu_answer(connect, event)
    else:
        print(event['object']['message']['text'])
        # return answer_arbitrary_text(connect, event)
    return 'START'


#######################################
## Функции, не являющиеся хэндлерами ##
#######################################
async def send_main_menu_answer(connect, event):
    user_id = event['object']['message']['from_id']
    payload = json.loads(event['object']['message'].get('payload', '{}'))
    user_instance = await Client.objects.async_get(vk_id=user_id)
    user_info = {
        'first_name': connect['redid_db'].get(f'{user_id}_first_name').decode('utf-8'),
        'last_name': connect['redid_db'].get(f'{user_id}_last_name').decode('utf-8')
    }
    # отправка курсов пользователя
    if payload.get('button') == 'client_courses':
        client_courses = await sync_to_async(user_instance.courses.filter)(published_in_bot=True)
        return await send_courses(
            connect, event, client_courses,
            'Вы еше не записаны ни на один курс:',
            'Курсы, на которые вы записаны или проходили:',
            'Еще ваши курсы',
            back='client_courses',
        )
    # отправка предстоящих курсов
    elif payload.get('button') == 'future_courses':
        future_courses = await Course.objects.async_filter(scheduled_at__gt=timezone.now(), published_in_bot=True)
        return await send_courses(
            connect, event, future_courses,
            'Пока нет запланированных курсов:',
            'Предстоящие курсы. Выберите для детальной информации',
            'Еще предстоящие курсы:',
            back='future_courses',
        )
    # отправка прошедших курсов
    elif payload.get('button') == 'past_courses':
        past_courses = await Course.objects.async_filter(scheduled_at__lte=timezone.now(), published_in_bot=True)
        return await send_courses(
            connect, event, past_courses,
            'Еше нет прошедших курсов:',
            'Прошедшие курсы',
            'Еще прошедшие курсы:',
            back='past_courses',
        )
    elif payload.get('button') == 'admin_msg':
        user_msg = f'{user_info["first_name"]}, введите и отправьте ваше сообщение:'
        await send_message(connect, user_id, message=user_msg)


async def send_courses(connect, event, courses, msg1, msg2, msg3, /, *, back):
    user_id = event['object']['message']['from_id']
    i = 0
    for client_courses_part in await sync_to_async(chunked)(courses, 5):
        i += 1
        msg = msg2 if i == 1 else msg3
        keyboard = await get_course_buttons(client_courses_part, back=back)
        await send_message(
            connect, user_id, message=msg,
            keyboard=keyboard
        )
    if i == 0:
        await send_message(
            connect, user_id, message=msg1,
            keyboard=await get_menu_button(color='secondary', inline=True)
        )
    return 'COURSE'


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
        connect = {'session': session, 'token': token, 'redis_db': redis_db}
        while True:
            try:
                params = {'act': 'a_check', 'key': key, 'ts': ts, 'wait': 25}
                async with session.get(server, params=params) as res:
                    res.raise_for_status()
                    response = json.loads(await res.text())
                if 'failed' in response:
                    if response['failed'] == 1:
                        ts = response['ts']
                    elif response['failed'] == 2:
                        key, __, __ = await get_long_poll_server(session, token, group_id)
                    elif response['failed'] == 3:
                        key, __, ts = await get_long_poll_server(session, token, group_id)
                    continue
                ts = response['ts']
                events = response['updates']
                pprint(events)
                for event in events:
                    if event['type'] != 'message_new':
                        continue
                    await event_handler(connect, event)
            except ConnectionError as err:
                sleep(5)
                print(err)
                key, server, ts = await get_long_poll_server(session, token, group_id)
                continue
            except requests.exceptions.ReadTimeout as err:
                sleep(5)
                print(err)
                key, server, ts = await get_long_poll_server(session, token, group_id)
                continue
            except Exception as err:
                sleep(5)
                key, server, ts = await get_long_poll_server(session, token, group_id)
                print(err)

if __name__ == '__main__':
    asyncio.run(listen_server())
