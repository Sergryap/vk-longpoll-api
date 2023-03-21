import json


async def get_start_buttons():
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
    return json.dumps(keyboard, ensure_ascii=False)


async def get_menu_button(color, inline):
    button = [
        [
            {
                'action': {'type': 'text', 'payload': {'button': 'start'}, 'label': '☰ MENU'},
                'color': color
            }
        ]
    ]
    keyboard = {'inline': inline, 'buttons': button}
    return json.dumps(keyboard, ensure_ascii=False)


async def get_course_buttons(course_instances, back):
    buttons = []
    gallery_payload = None
    for course in course_instances:
        if course.name == 'Фотогалерея':
            gallery_payload = {'course_pk': course.pk, 'button': back}
            continue
        buttons.append(
            [
                {
                    'action': {
                        'type': 'text',
                        'payload': {'course_pk': course.pk, 'button': back},
                        'label': course.name
                    },
                    'color': 'secondary'
                }
            ],
        )
    buttons.append(
        [
            {
                'action': {
                    'type': 'text',
                    'payload': {'button': 'start'},
                    'label': '☰ MENU'
                },
                'color': 'primary'
            }
        ],
    )
    if gallery_payload:
        buttons[-1].append(
            {
                'action': {
                    'type': 'text',
                    'payload': gallery_payload,
                    'label': 'ГАЛЕРЕЯ'
                },
                'color': 'primary'
            }
        )
    keyboard = {'inline': True, 'buttons': buttons}
    return json.dumps(keyboard, ensure_ascii=False)
