import json
import os
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from telegram_bot_calendar import DetailedTelegramCalendar, LSTEP
from dateutil.relativedelta import relativedelta
import asyncio
from config import TOKEN
from cryptography.fernet import Fernet

# Читаем TOKEN из config

DATA_FILE = 'reminders.json'


# Функция для загрузки ключа шифрования
def load_key():
    if os.path.exists('secret.key'):
        with open('secret.key', 'rb') as key_file:
            return key_file.read()
    else:
        key = Fernet.generate_key()
        with open('secret.key', 'wb') as key_file:
            key_file.write(key)
        return key


KEY = load_key()  # Загружаем ключ
cipher = Fernet(KEY)


# Словарь для хранения временных данных пользователя
user_data = {}
# Добавим словарь для хранения ID сообщений
user_messages = {}

# Настройка логирования
log_filename = 'remind_me_bot.log'
logging.basicConfig(
    filename=log_filename,
    filemode='a',
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    encoding='utf-8'
)
logger = logging.getLogger(__name__)

# Инициализация данных
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, 'w') as f:
        json.dump({}, f)


# Функция для загрузки напоминаний
def load_reminders() -> dict:
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as file:
            content = file.read()
            if content:
                return json.loads(content)
            return {}
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Error loading reminders: {e}")
        return {}


# Функция для сохранения напоминаний
def save_reminders(reminders: dict):
    with open(DATA_FILE, 'w', encoding='utf-8') as file:
        json.dump(reminders, file, ensure_ascii=False, indent=4)


# Функция для добавления напоминания
def add_reminder(user_id: str, time: str, message: str, repeat: str):
    reminders = load_reminders()
    if user_id not in reminders:
        reminders[user_id] = []

    encrypted_message = cipher.encrypt(message.encode()).decode()  # Шифруем сообщение
    reminders[user_id].append({
        'time': time,
        'message': encrypted_message,
        'repeat': repeat,
        'sent': False
    })

    logger.info(f"Added encrypted reminder for user {user_id}: {encrypted_message}")
    save_reminders(reminders)


# Функция для создания клавиатуры выбора типа напоминания
def get_type_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("Единоразово", callback_data='единоразово'),
            InlineKeyboardButton("Ежедневно", callback_data='ежедневно')
        ],
        [
            InlineKeyboardButton("Еженедельно", callback_data='еженедельно'),
            InlineKeyboardButton("Ежемесячно", callback_data='ежемесячно')
        ],
        [
            InlineKeyboardButton("Ежегодно", callback_data='ежегодно')
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


# Функция для создания клавиатуры выбора времени с интервалом 30 минут
def get_time_keyboard():
    hours = [f'{i:02}' for i in range(0, 24)]  # Часы от 00 до 23
    minutes = [f'00', f'30']  # Минуты с интервалом 30 минут
    time_keyboard = [[f'{hour}:{minute}' for minute in minutes] for hour in hours]
    return ReplyKeyboardMarkup(time_keyboard, one_time_keyboard=True)


# Функция для удаления сообщений по ID
async def delete_user_messages(user_id: str, context: ContextTypes.DEFAULT_TYPE):
    if user_id in user_messages:
        for message_id in user_messages[user_id]:
            try:
                await context.bot.delete_message(chat_id=user_id, message_id=message_id)
            except Exception as e:
                logger.error(f"Failed to delete message for user {user_id}: {e}")
        user_messages[user_id] = []


# Обработчик команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        'Привет! 👋\n'
        'Я твой верный бот для создания напоминаний. 🕰\n\n'
        'Ты когда-нибудь забывал сделать что-то важное? 🤔\n'
        'Не беда! Я помогу тебе помнить обо всех делах, даже о тех, которые так хочется забыть. 😅\n\n'
        'Вот что я умею:\n'
        '📌 Хочешь добавить напоминание?\n'
        'Просто используй команду: /set_reminder\n'
        '📋 Посмотреть все свои напоминания? Легко!\n'
        'Жми: /list_reminders\n'
        '🗑️ Удалить лишнее напоминание? Без проблем!\n'
        'Введи: /delete_reminder\n\n'
        'Доверь мне свои заботы, а сам наслаждайся жизнью! 😎'
    )


# Обработчик команды /set_reminder
async def set_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    user_data[user_id] = {}
    msg = await update.message.reply_text(
        'Выберите тип напоминания:',
        reply_markup=get_type_keyboard()
    )
    user_messages[user_id] = [msg.message_id]  # Сохраняем ID сообщения


# Обработчик нажатий на кнопки выбора типа напоминания
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(query.from_user.id)

    # Получаем выбранный тип напоминания
    reminder_type = query.data
    user_data[user_id]['type'] = reminder_type

    # Запускаем календарь для выбора даты
    calendar, step = DetailedTelegramCalendar().build()
    await query.answer()
    msg = await query.edit_message_text(f"Выберите дату ({LSTEP[step]}):", reply_markup=calendar)
    user_messages[user_id].append(msg.message_id)  # Добавляем ID нового сообщения


# Обработчик выбора даты
async def calendar_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(query.from_user.id)

    # Проверка наличия данных для пользователя
    if user_id not in user_data:
        await query.answer()
        await query.edit_message_text('Произошла ошибка. Попробуйте снова.')
        return

    # Работа с календарем
    result, key, step = DetailedTelegramCalendar().process(query.data)
    if not result and key:
        msg = await query.edit_message_text(f"Выберите дату ({LSTEP[step]}):", reply_markup=key)
        user_messages[user_id].append(msg.message_id)
    elif result:
        user_data[user_id]['date'] = result
        await query.answer()
        # Отправляем новое сообщение для выбора времени
        msg = await context.bot.send_message(chat_id=query.message.chat_id,
                                             text=f"Вы выбрали: {result}. Теперь выберите время:",
                                             reply_markup=get_time_keyboard())
        user_messages[user_id].append(msg.message_id)


# Обработчик выбора времени и получения сообщения
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)

    if user_id not in user_data or 'date' not in user_data[user_id]:
        await update.message.reply_text('Сначала выберите тип напоминания с помощью команды /set_reminder.')
        return

    # Проверяем, выбрано ли время
    if 'time' not in user_data[user_id]:
        user_data[user_id]['time'] = update.message.text
        user_messages[user_id].append(update.message.message_id)  # Сохраняем ID сообщения пользователя о времени
        msg = await update.message.reply_text('Теперь введите сообщение, которое нужно будет напомнить.')
        user_messages[user_id].append(msg.message_id)  # Сохраняем ID сообщения с просьбой ввести текст
    else:
        reminder_message = update.message.text
        reminder_date = user_data[user_id]['date']
        reminder_time = user_data[user_id]['time']
        reminder_type = user_data[user_id]['type']

        # Добавляем напоминание
        reminder_datetime_str = f"{reminder_date} {reminder_time}"
        try:
            reminder_datetime = datetime.strptime(reminder_datetime_str, '%Y-%m-%d %H:%M')
            encrypted_message = cipher.encrypt(reminder_message.encode()).decode()
            add_reminder(user_id, reminder_datetime.strftime('%Y-%m-%d %H:%M'), reminder_message, reminder_type)
            logger.info(f"Reminder set by user {user_id}: {encrypted_message}")
            await update.message.reply_text(f'Напоминание добавлено на {reminder_datetime_str}. '
                                            f'Повтор: {reminder_type}')

        except ValueError:
            await update.message.reply_text('Неверный формат времени. Попробуйте снова.')

        # Сохраняем ID сообщения пользователя с текстом напоминания
        user_messages[user_id].append(update.message.message_id)

        # Удаляем временные данные и сообщения пользователя
        await delete_user_messages(user_id, context)
        del user_data[user_id]


# Обработчик команды /list_reminders
async def list_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    reminders = load_reminders()
    user_reminders = reminders.get(user_id, [])

    if not user_reminders:
        await update.message.reply_text('У вас нет установленных напоминаний.')
        return

    message_lines = ['Ваши напоминания:']
    for i, reminder in enumerate(user_reminders):
        decrypted_message = cipher.decrypt(reminder['message'].encode()).decode()  # Дешифруем сообщение
        message_lines.append(
            f"🗓️ {reminder['time']} - {decrypted_message}\n"
            f"[Повтор: {reminder['repeat']}. Отправлено: {'Да' if reminder['sent'] else 'Нет'}]"
        )

    await update.message.reply_text('\n'.join(message_lines))


# Обработчик команды /delete_reminder
async def delete_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    reminders = load_reminders()
    user_reminders = reminders.get(user_id, [])

    if not user_reminders:
        await update.message.reply_text('У вас нет напоминаний для удаления.')
        return

    keyboard = []
    for i, reminder in enumerate(user_reminders, 1):
        decrypted_message = cipher.decrypt(reminder['message'].encode()).decode()
        reminder_text = f"{reminder['time']} - {decrypted_message}"
        keyboard.append([InlineKeyboardButton(reminder_text, callback_data=f"delete_{i}")])
    keyboard.append([InlineKeyboardButton("Отмена", callback_data="cancel")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Выберите напоминание для удаления:', reply_markup=reply_markup)


# Обработчик выбора напоминания для удаления
async def delete_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(query.from_user.id)
    data = query.data

    reminders = load_reminders()
    user_reminders = reminders.get(user_id, [])

    if data.startswith('delete_'):
        # Исправляем индекс, чтобы он соответствовал индексации списка (отнимаем 1)
        index = int(data.split('_')[1]) - 1
        if 0 <= index < len(user_reminders):
            deleted_reminder = user_reminders.pop(index)
            # Сохраняем обновления, не затрагивая напоминания других пользователей
            reminders[user_id] = user_reminders
            save_reminders(reminders)

            await query.answer()
            await query.edit_message_text(f'Напоминание '
                                          f'"{cipher.decrypt(deleted_reminder["message"].encode()).decode()}"'
                                          f' удалено.')
            logger.info(f"Reminder deleted by user {user_id}: "
                        f"{cipher.encrypt(deleted_reminder['message'].encode()).decode()}")
        else:
            await query.answer()
            await query.edit_message_text('Ошибка: Неверный номер напоминания.')
            logger.error(f"Failed to delete reminder for user {user_id}: Invalid index {index}")

    elif data == 'cancel':
        await query.answer()
        await query.edit_message_text('Удаление напоминания отменено.')


# Функция для проверки и отправки напоминаний
async def check_reminders(application: Application):
    now = datetime.now()
    now_str = now.strftime('%Y-%m-%d %H:%M')
    logger.info(f"Checking reminders at {now_str}")

    reminders = load_reminders()
    updated_reminders = {}

    for user_id, user_reminders in reminders.items():
        new_reminders = []
        for reminder in user_reminders:
            reminder_time = datetime.strptime(reminder['time'], '%Y-%m-%d %H:%M')
            if reminder_time <= now and not reminder['sent']:
                chat_id = int(user_id)
                try:
                    # Отправляем напоминание
                    decrypted_message = cipher.decrypt(reminder['message'].encode()).decode()
                    await application.bot.send_message(chat_id=chat_id, text=decrypted_message)
                    logger.info(f"Sent message to chat_id {chat_id}: "
                                f"{cipher.encrypt(decrypted_message.encode()).decode()}")
                    reminder['sent'] = True

                    # Добавляем одноразовое повторное напоминание через 10 минут
                    if not reminder.get('is_repeat', False):
                        new_reminder_time = now + timedelta(minutes=10)
                        new_reminders.append({
                            'time': new_reminder_time.strftime('%Y-%m-%d %H:%M'),
                            'message': cipher.encrypt(decrypted_message.encode()).decode(),
                            'repeat': 'единоразово',
                            'sent': False,
                            'is_repeat': True
                        })

                    save_reminders(reminders)

                except Exception as e:
                    logger.error(f"Failed to send message to chat_id {chat_id}: {e}")

                # Добавляем повторное напоминание, если оно не одноразовое
                if reminder['repeat'] != 'единоразово':
                    if reminder['repeat'] == 'ежедневно':
                        reminder_time += timedelta(days=1)
                    elif reminder['repeat'] == 'еженедельно':
                        reminder_time += timedelta(weeks=1)
                    elif reminder['repeat'] == 'ежемесячно':
                        reminder_time += relativedelta(months=1)
                    elif reminder['repeat'] == 'ежегодно':
                        reminder_time += relativedelta(years=1)

                    reminder['time'] = reminder_time.strftime('%Y-%m-%d %H:%M')
                    reminder['sent'] = False
                    new_reminders.append(reminder)
            else:
                new_reminders.append(reminder)

        updated_reminders[user_id] = new_reminders

    if updated_reminders != reminders:
        save_reminders(updated_reminders)


# Функция для запуска планировщика
async def run_scheduler(application: Application):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_reminders, IntervalTrigger(minutes=1), args=[application])
    scheduler.start()
    while True:
        await asyncio.sleep(1)


def main():
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('set_reminder', set_reminder))
    application.add_handler(CommandHandler('list_reminders', list_reminders))
    application.add_handler(CommandHandler('delete_reminder', delete_reminder))
    application.add_handler(CallbackQueryHandler(delete_button_handler, pattern='^(delete_.*|cancel)$'))
    application.add_handler(CallbackQueryHandler(button_handler,
                                                 pattern='^(единоразово|ежедневно|еженедельно|ежемесячно|ежегодно)$'))
    application.add_handler(CallbackQueryHandler(calendar_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    loop = asyncio.get_event_loop()
    loop.create_task(run_scheduler(application))

    application.run_polling()


if __name__ == '__main__':
    main()
