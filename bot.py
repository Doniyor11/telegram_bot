#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)
import sqlite3
from datetime import datetime, time
import pytz

# Настройки бота
BOT_TOKEN = "8249402614:AAFQgtDqZtBByhe3MTU0JsuPRjK94l_HWvY"
ADMIN_ID = 1995964543

# Логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Состояния
DESTINATION, ADDRESS, WAITING_PHOTO = range(3)

class DeliveryBot:
    def __init__(self):
        self.db_path = 'delivery_bot.db'
        self.init_database()

    def init_database(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                is_admin BOOLEAN DEFAULT FALSE,
                registered_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                destination TEXT NOT NULL,
                address TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                created_by INTEGER,
                status TEXT DEFAULT 'pending',
                accepted_by INTEGER,
                accepted_at DATETIME,
                completed_at DATETIME,
                photo_file_id TEXT,
                FOREIGN KEY (created_by) REFERENCES users (user_id),
                FOREIGN KEY (accepted_by) REFERENCES users (user_id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS work_attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                check_in_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                date DATE DEFAULT (date('now')),
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')

        conn.commit()
        conn.close()
        self.fix_admin_status()
        logger.info("База данных инициализирована")

    def fix_admin_status(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT OR REPLACE INTO users
            (user_id, username, first_name, last_name, is_admin)
            VALUES (?, ?, ?, ?, ?)
        ''', (ADMIN_ID, "admin", "Администратор", "", True))

        cursor.execute('UPDATE users SET is_admin = FALSE WHERE user_id != ?', (ADMIN_ID,))

        conn.commit()
        conn.close()
        logger.info(f"Статус администратора обновлен для ID: {ADMIN_ID}")

    def add_user(self, user_id, username, first_name, last_name, is_admin=False):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        if user_id == ADMIN_ID:
            is_admin = True

        cursor.execute('''
            INSERT OR REPLACE INTO users
            (user_id, username, first_name, last_name, is_admin)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, username, first_name, last_name, is_admin))

        conn.commit()
        conn.close()
        logger.info(f"Пользователь {user_id} добавлен в базу")

    def is_admin(self, user_id):
        return user_id == ADMIN_ID

    def get_employees_only(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT user_id, first_name, username FROM users
            WHERE user_id != ?
            AND (is_admin = FALSE OR is_admin IS NULL)
        ''', (ADMIN_ID,))

        users = cursor.fetchall()
        conn.close()

        employee_ids = []
        for user_id, first_name, username in users:
            if user_id != ADMIN_ID:
                employee_ids.append(user_id)
                logger.info(f"Сотрудник: ID={user_id}, Имя={first_name}")
            else:
                logger.warning(f"ИСКЛЮЧЕН АДМИН: ID={user_id}")

        logger.info(f"Список сотрудников: {employee_ids}")
        return employee_ids

    def create_task(self, destination, address, created_by):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO tasks (destination, address, created_by)
            VALUES (?, ?, ?)
        ''', (destination, address, created_by))

        task_id = cursor.lastrowid
        conn.commit()
        conn.close()

        logger.info(f"Создано задание #{task_id}")
        return task_id

    def accept_task(self, task_id, user_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            UPDATE tasks
            SET status = 'accepted', accepted_by = ?, accepted_at = CURRENT_TIMESTAMP
            WHERE task_id = ? AND status = 'pending'
        ''', (user_id, task_id))

        success = cursor.rowcount > 0
        conn.commit()
        conn.close()

        if success:
            logger.info(f"Задание #{task_id} принято пользователем {user_id}")

        return success

    def complete_task(self, task_id, photo_file_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            UPDATE tasks
            SET status = 'completed', completed_at = CURRENT_TIMESTAMP, photo_file_id = ?
            WHERE task_id = ? AND status = 'accepted'
        ''', (photo_file_id, task_id))

        success = cursor.rowcount > 0
        conn.commit()
        conn.close()

        if success:
            logger.info(f"Задание #{task_id} завершено")

        return success

    def get_task_info(self, task_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT destination, address, accepted_by, status
            FROM tasks WHERE task_id = ?
        ''', (task_id,))

        result = cursor.fetchone()
        conn.close()

        return result

    def get_stats(self):
        """Получение статистики"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        stats = {}

        try:
            # Общее количество заданий
            cursor.execute('SELECT COUNT(*) FROM tasks')
            stats['total_tasks'] = cursor.fetchone()[0]

            # Количество заданий по статусам
            cursor.execute('SELECT status, COUNT(*) FROM tasks GROUP BY status')
            status_counts = cursor.fetchall()
            for status, count in status_counts:
                stats[f'{status}_tasks'] = count

            # Количество пользователей (только сотрудники)
            cursor.execute('SELECT COUNT(*) FROM users WHERE is_admin = FALSE AND user_id != ?', (ADMIN_ID,))
            stats['total_users'] = cursor.fetchone()[0]

            # Сегодняшняя посещаемость
            cursor.execute('SELECT COUNT(*) FROM work_attendance WHERE date = date("now")')
            stats['today_attendance'] = cursor.fetchone()[0]

        except Exception as e:
            logger.error(f"Ошибка в get_stats: {e}")
            # Возвращаем значения по умолчанию
            stats = {
                'total_tasks': 0,
                'pending_tasks': 0,
                'accepted_tasks': 0,
                'completed_tasks': 0,
                'total_users': 0,
                'today_attendance': 0
            }
        finally:
            conn.close()

        return stats

    def get_user_active_task(self, user_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT task_id, destination, address
            FROM tasks
            WHERE accepted_by = ? AND status = 'accepted'
            ORDER BY accepted_at DESC LIMIT 1
        ''', (user_id,))

        result = cursor.fetchone()
        conn.close()

        return result

    def get_user_info(self, user_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT username, first_name, last_name
            FROM users WHERE user_id = ?
        ''', (user_id,))

        result = cursor.fetchone()
        conn.close()

        return result

    def check_in_work(self, user_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT id FROM work_attendance
            WHERE user_id = ? AND date = date('now')
        ''', (user_id,))

        if cursor.fetchone():
            conn.close()
            return False

        cursor.execute('''
            INSERT INTO work_attendance (user_id)
            VALUES (?)
        ''', (user_id,))

        conn.commit()
        conn.close()

        logger.info(f"Пользователь {user_id} отметился на работе")
        return True

    def get_today_attendance(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT u.first_name, u.last_name, u.username, w.check_in_time
            FROM work_attendance w
            JOIN users u ON w.user_id = u.user_id
            WHERE w.date = date('now')
            ORDER BY w.check_in_time
        ''')

        result = cursor.fetchall()
        conn.close()

        return result

    def is_checked_in_today(self, user_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT id FROM work_attendance
            WHERE user_id = ? AND date = date('now')
        ''', (user_id,))

        result = cursor.fetchone() is not None
        conn.close()

        return result

    def get_task_messages(self, task_id):
        """Получение всех сообщений с определенным заданием"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS task_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                FOREIGN KEY (task_id) REFERENCES tasks (task_id)
            )
        ''')

        cursor.execute('''
            SELECT user_id, message_id FROM task_messages
            WHERE task_id = ?
        ''', (task_id,))

        result = cursor.fetchall()
        conn.commit()
        conn.close()

        return result

    def save_task_message(self, task_id, user_id, message_id):
        """Сохранение ID сообщения с заданием"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO task_messages (task_id, user_id, message_id)
            VALUES (?, ?, ?)
        ''', (task_id, user_id, message_id))

        conn.commit()
        conn.close()
        logger.info(f"Сохранено сообщение {message_id} для задания #{task_id} пользователю {user_id}")

    def delete_task_messages(self, task_id):
        """Удаление записей о сообщениях задания"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('DELETE FROM task_messages WHERE task_id = ?', (task_id,))

        conn.commit()
        conn.close()
        logger.info(f"Удалены записи сообщений для задания #{task_id}")
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        stats = {}

        cursor.execute('SELECT COUNT(*) FROM tasks')
        stats['total_tasks'] = cursor.fetchone()[0]

        cursor.execute('SELECT status, COUNT(*) FROM tasks GROUP BY status')
        status_counts = cursor.fetchall()
        for status, count in status_counts:
            stats[f'{status}_tasks'] = count

        cursor.execute('SELECT COUNT(*) FROM users WHERE is_admin = FALSE')
        stats['total_users'] = cursor.fetchone()[0]

        conn.close()
    def get_stats(self):
        """Получение статистики"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        stats = {}

        # Общее количество заданий
        cursor.execute('SELECT COUNT(*) FROM tasks')
        stats['total_tasks'] = cursor.fetchone()[0]

        # Количество заданий по статусам
        cursor.execute('SELECT status, COUNT(*) FROM tasks GROUP BY status')
        status_counts = cursor.fetchall()
        for status, count in status_counts:
            stats[f'{status}_tasks'] = count

        # Количество пользователей (только сотрудники)
        cursor.execute('SELECT COUNT(*) FROM users WHERE is_admin = FALSE AND user_id != ?', (ADMIN_ID,))
        stats['total_users'] = cursor.fetchone()[0]

        # Сегодняшняя посещаемость
        cursor.execute('SELECT COUNT(*) FROM work_attendance WHERE date = date("now")')
        stats['today_attendance'] = cursor.fetchone()[0]

        conn.close()
        return stats

bot_instance = DeliveryBot()

async def show_employee_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user else update.callback_query.from_user.id

    is_checked_in = bot_instance.is_checked_in_today(user_id)

    keyboard = [
        [InlineKeyboardButton("📋 Мое задание", callback_data="my_task")],
        [InlineKeyboardButton("✅ Завершить задание", callback_data="complete_task")]
    ]

    if not is_checked_in:
        keyboard.insert(0, [InlineKeyboardButton("🏢 Вышел на работу", callback_data="check_in")])

    keyboard.append([InlineKeyboardButton("ℹ️ Справка", callback_data="help")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    menu_text = "📱 Меню сотрудника:"
    if is_checked_in:
        menu_text += "\n✅ Вы уже отметились сегодня"

    if update.message:
        await update.message.reply_text(menu_text, reply_markup=reply_markup)
    else:
        await update.callback_query.edit_message_text(menu_text, reply_markup=reply_markup)

async def show_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📋 Создать задание", callback_data="create_task")],
        [InlineKeyboardButton("📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton("👥 Кто на работе", callback_data="attendance")],
        [InlineKeyboardButton("ℹ️ Справка", callback_data="help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text("👑 Меню администратора:", reply_markup=reply_markup)
    else:
        await update.callback_query.edit_message_text("👑 Меню администратора:", reply_markup=reply_markup)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if user.id == ADMIN_ID:
        logger.info(f"Администратор {ADMIN_ID} подключился")
        await show_admin_menu(update, context)
    else:
        bot_instance.add_user(
            user.id,
            user.username or "",
            user.first_name or "",
            user.last_name or "",
            is_admin=False
        )
        logger.info(f"Сотрудник {user.id} зарегистрирован")
        await show_employee_menu(update, context)

async def my_task_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.callback_query.from_user.id

    active_task = bot_instance.get_user_active_task(user_id)

    if active_task:
        task_id, destination, address = active_task

        keyboard = [
            [InlineKeyboardButton("✅ Закончил работу", callback_data=f"finish_{task_id}")],
            [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.callback_query.edit_message_text(
            f"📋 Ваше активное задание #{task_id}:\n\n"
            f"📍 Пункт назначения: {destination}\n"
            f"🏠 Адрес: {address}\n\n"
            f"Нажмите кнопку, когда выполните работу:",
            reply_markup=reply_markup
        )
    else:
        keyboard = [
            [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.callback_query.edit_message_text(
            "❌ У вас нет активных заданий.\n"
            "Ожидайте новых уведомлений от администратора.",
            reply_markup=reply_markup
        )

async def complete_task_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.callback_query.from_user.id

    active_task = bot_instance.get_user_active_task(user_id)

    if active_task:
        task_id, destination, address = active_task
        context.user_data['completing_task_id'] = task_id

        await update.callback_query.edit_message_text(
            f"📸 Для завершения задания #{task_id} отправьте фото-отчет:\n\n"
            f"📍 {destination}\n"
            f"🏠 {address}\n\n"
            f"Отправьте фотографию выполненной работы:"
        )
        return WAITING_PHOTO
    else:
        keyboard = [
            [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.callback_query.edit_message_text(
            "❌ У вас нет активных заданий для завершения.",
            reply_markup=reply_markup
        )
        return ConversationHandler.END

async def check_in_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.callback_query.from_user.id

    if bot_instance.check_in_work(user_id):
        user_info = bot_instance.get_user_info(user_id)
        username = user_info[0] if user_info[0] else "Не указан"
        full_name = f"{user_info[1]} {user_info[2]}".strip()

        notification_text = (
            f"🏢 Сотрудник вышел на работу!\n\n"
            f"👤 Сотрудник: {full_name}\n"
            f"📱 Username: @{username}\n"
            f"🕐 Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )

        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=notification_text
            )
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления админу: {e}")

        keyboard = [
            [InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.callback_query.edit_message_text(
            f"✅ Вы отметились на работе!\n"
            f"🕐 Время: {datetime.now().strftime('%H:%M')}\n\n"
            f"Администратор уведомлен.",
            reply_markup=reply_markup
        )
    else:
        keyboard = [
            [InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.callback_query.edit_message_text(
            "❌ Вы уже отмечались сегодня!",
            reply_markup=reply_markup
        )

async def attendance_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    attendance = bot_instance.get_today_attendance()

    if attendance:
        attendance_text = "👥 Сегодня на работе:\n\n"

        for first_name, last_name, username, check_in_time in attendance:
            full_name = f"{first_name} {last_name}".strip()
            username_text = f"@{username}" if username else "Не указан"
            time_obj = datetime.fromisoformat(check_in_time).strftime('%H:%M')

            attendance_text += f"👤 {full_name}\n"
            attendance_text += f"📱 {username_text}\n"
            attendance_text += f"🕐 {time_obj}\n\n"
    else:
        attendance_text = "❌ Сегодня никто еще не отмечался на работе."

    keyboard = [
        [InlineKeyboardButton("🔄 Обновить", callback_data="attendance")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.callback_query.edit_message_text(
        attendance_text,
        reply_markup=reply_markup
    )

async def daily_work_reminder(context: ContextTypes.DEFAULT_TYPE):
    try:
        employee_ids = bot_instance.get_employees_only()

        reminder_text = (
            "🌅 Доброе утро!\n\n"
            "Пора на работу! 💼\n"
            "Не забудьте отметиться, нажав кнопку ниже:"
        )

        keyboard = [[InlineKeyboardButton("🏢 Вышел на работу", callback_data="check_in")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        sent_count = 0
        for employee_id in employee_ids:
            if employee_id == ADMIN_ID:
                logger.error(f"🚨 ОШИБКА: Попытка отправить напоминание администратору {ADMIN_ID}!")
                continue

            if not bot_instance.is_checked_in_today(employee_id):
                try:
                    await context.bot.send_message(
                        chat_id=employee_id,
                        text=reminder_text,
                        reply_markup=reply_markup
                    )
                    sent_count += 1
                    logger.info(f"✅ Напоминание отправлено сотруднику {employee_id}")
                except Exception as e:
                    logger.error(f"❌ Ошибка отправки напоминания сотруднику {employee_id}: {e}")

        if sent_count > 0:
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=f"📤 Отправлено {sent_count} напоминаний о выходе на работу"
                )
            except Exception as e:
                logger.error(f"Ошибка уведомления админа о напоминаниях: {e}")

        logger.info(f"Отправлено {sent_count} напоминаний о работе")

    except Exception as e:
        logger.error(f"Ошибка в функции напоминания: {e}")

async def help_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.callback_query.from_user.id

    if bot_instance.is_admin(user_id):
        help_text = (
            "🔧 Функции администратора:\n\n"
            "📋 Создать задание - Создание новых заданий для сотрудников\n"
            "📊 Статистика - Просмотр статистики по заданиям\n"
            "👥 Кто на работе - Список сотрудников на работе сегодня\n"
            "ℹ️ Справка - Эта справка\n\n"
            "🎯 Возможности:\n"
            "• Создание заданий с адресами\n"
            "• Автоматическая рассылка сотрудникам\n"
            "• Уведомления о принятых заданиях\n"
            "• Получение фото-отчетов\n"
            "• Учет рабочего времени сотрудников\n"
            "• Просмотр статистики работы"
        )

        keyboard = [
            [InlineKeyboardButton("📋 Создать задание", callback_data="create_task")],
            [InlineKeyboardButton("📊 Статистика", callback_data="stats")],
            [InlineKeyboardButton("👥 Кто на работе", callback_data="attendance")]
        ]
    else:
        help_text = (
            "👨‍💼 Функции сотрудника:\n\n"
            "🏢 Вышел на работу - Отметиться о выходе на работу\n"
            "📋 Мое задание - Показать активное задание\n"
            "✅ Завершить задание - Отправить фото-отчет\n"
            "ℹ️ Справка - Эта справка\n\n"
            "🎯 Процесс работы:\n"
            "1. Отметьтесь о выходе на работу утром\n"
            "2. Получите уведомление о новом задании\n"
            "3. Нажмите 'Принимаю' для принятия\n"
            "4. Выполните работу по указанному адресу\n"
            "5. Нажмите 'Закончил работу'\n"
            "6. Отправьте фото-отчет"
        )

        keyboard = [
            [InlineKeyboardButton("📋 Мое задание", callback_data="my_task")],
            [InlineKeyboardButton("✅ Завершить задание", callback_data="complete_task")],
            [InlineKeyboardButton("🏢 Вышел на работу", callback_data="check_in")]
        ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.callback_query.edit_message_text(
        help_text,
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if query.data == "create_task":
        if bot_instance.is_admin(user_id):
            await query.edit_message_text("📍 Введите пункт назначения:")
            return DESTINATION
        else:
            await query.edit_message_text("❌ У вас нет прав администратора!")
            return ConversationHandler.END

    elif query.data == "stats":
        if bot_instance.is_admin(user_id):
            try:
                # Проверяем, есть ли метод get_stats
                if hasattr(bot_instance, 'get_stats'):
                    stats = bot_instance.get_stats()
                else:
                    # Запасной вариант - получаем статистику напрямую
                    stats = {}
                    conn = sqlite3.connect(bot_instance.db_path)
                    cursor = conn.cursor()

                    cursor.execute('SELECT COUNT(*) FROM tasks')
                    stats['total_tasks'] = cursor.fetchone()[0]

                    cursor.execute('SELECT status, COUNT(*) FROM tasks GROUP BY status')
                    status_counts = cursor.fetchall()
                    for status, count in status_counts:
                        stats[f'{status}_tasks'] = count

                    cursor.execute('SELECT COUNT(*) FROM users WHERE is_admin = FALSE')
                    stats['total_users'] = cursor.fetchone()[0]

                    cursor.execute('SELECT COUNT(*) FROM work_attendance WHERE date = date("now")')
                    stats['today_attendance'] = cursor.fetchone()[0]

                    conn.close()

                total_users = stats.get('total_users', 0)
                total_tasks = stats.get('total_tasks', 0)
                pending_tasks = stats.get('pending_tasks', 0)
                accepted_tasks = stats.get('accepted_tasks', 0)
                completed_tasks = stats.get('completed_tasks', 0)
                today_attendance = stats.get('today_attendance', 0)

                stats_text = (
                    "📊 Статистика бота:\n\n"
                    f"👥 Сотрудников: {total_users}\n"
                    f"🏢 Сегодня на работе: {today_attendance}\n\n"
                    f"📋 Всего заданий: {total_tasks}\n"
                    f"⏳ Ожидающих: {pending_tasks}\n"
                    f"🔄 В работе: {accepted_tasks}\n"
                    f"✅ Завершенных: {completed_tasks}"
                )

                keyboard = [
                    [InlineKeyboardButton("📋 Создать задание", callback_data="create_task")],
                    [InlineKeyboardButton("🔄 Обновить", callback_data="stats")],
                    [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await query.edit_message_text(stats_text, reply_markup=reply_markup)

            except Exception as e:
                logger.error(f"Ошибка получения статистики: {e}")
                error_text = (
                    "❌ Ошибка при получении статистики.\n\n"
                    "Возможные причины:\n"
                    "• База данных не инициализирована\n"
                    "• Проблемы с подключением\n\n"
                    "Попробуйте перезапустить бота."
                )

                keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await query.edit_message_text(error_text, reply_markup=reply_markup)
        else:
            await query.edit_message_text("❌ У вас нет прав администратора!")

    elif query.data == "attendance":
        if bot_instance.is_admin(user_id):
            await attendance_handler(update, context)
        else:
            await query.edit_message_text("❌ У вас нет прав администратора!")

    elif query.data == "check_in":
        await check_in_handler(update, context)

    elif query.data == "my_task":
        await my_task_button(update, context)

    elif query.data == "complete_task":
        return await complete_task_button(update, context)

    elif query.data == "help":
        await help_button(update, context)

    elif query.data == "back_to_menu":
        if bot_instance.is_admin(user_id):
            await show_admin_menu(update, context)
        else:
            await show_employee_menu(update, context)

    elif query.data.startswith("accept_"):
        task_id = int(query.data.split("_")[1])

        if bot_instance.accept_task(task_id, user_id):
            user_info = bot_instance.get_user_info(user_id)
            username = user_info[0] if user_info[0] else "Не указан"
            full_name = f"{user_info[1]} {user_info[2]}".strip()

            # Уведомляем администратора
            notification_text = (
                f"✅ Задание #{task_id} принято!\n\n"
                f"👤 Сотрудник: {full_name}\n"
                f"📱 Username: @{username}\n"
                f"🕐 Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
            )

            try:
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=notification_text
                )
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления админу: {e}")

            # УДАЛЯЕМ ЗАДАНИЕ У ВСЕХ ОСТАЛЬНЫХ СОТРУДНИКОВ
            task_messages = bot_instance.get_task_messages(task_id)
            deleted_count = 0

            for msg_user_id, message_id in task_messages:
                # Не удаляем у того, кто принял задание
                if msg_user_id != user_id:
                    try:
                        await context.bot.edit_message_text(
                            chat_id=msg_user_id,
                            message_id=message_id,
                            text=f"❌ Задание #{task_id} уже принято другим сотрудником.\n\n"
                                 f"👤 Принял: {full_name}\n"
                                 f"🕐 Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
                        )
                        deleted_count += 1
                        logger.info(f"✅ Удалено задание #{task_id} у сотрудника {msg_user_id}")
                    except Exception as e:
                        logger.error(f"❌ Ошибка удаления задания у сотрудника {msg_user_id}: {e}")

            # Очищаем записи о сообщениях
            bot_instance.delete_task_messages(task_id)

            logger.info(f"📤 Задание #{task_id} удалено у {deleted_count} сотрудников")

            # Отвечаем принявшему сотруднику
            await query.edit_message_text(
                f"✅ Вы приняли задание #{task_id}!\n"
                f"Администратор уведомлен.\n\n"
                f"🚫 Задание удалено у {deleted_count} других сотрудников\n\n"
                f"📋 Для завершения задания нажмите кнопку ниже "
                f"или используйте меню бота (/start)"
            )
        else:
            await query.edit_message_text(
                "❌ Задание уже принято другим сотрудником или не существует."
            )

    elif query.data.startswith("finish_"):
        task_id = int(query.data.split("_")[1])

        active_task = bot_instance.get_user_active_task(user_id)

        if active_task and active_task[0] == task_id:
            context.user_data['completing_task_id'] = task_id

            await query.edit_message_text(
                f"📸 Для завершения задания #{task_id} отправьте фото-отчет:\n\n"
                f"📍 {active_task[1]}\n"
                f"🏠 {active_task[2]}\n\n"
                f"Отправьте фотографию выполненной работы:"
            )
            return WAITING_PHOTO
        else:
            await query.edit_message_text(
                "❌ Задание не найдено или уже завершено."
            )

async def get_destination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['destination'] = update.message.text
    await update.message.reply_text("🏠 Теперь введите адрес:")
    return ADDRESS

async def get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    address = update.message.text
    destination = context.user_data['destination']

    task_id = bot_instance.create_task(destination, address, update.effective_user.id)

    task_message = (
        f"📦 Новое задание #{task_id}\n\n"
        f"📍 Пункт назначения: {destination}\n"
        f"🏠 Адрес: {address}\n"
        f"🕐 Время создания: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
        f"Нажмите 'Принимаю', чтобы взять задание:"
    )

    keyboard = [[InlineKeyboardButton("✅ Принимаю", callback_data=f"accept_{task_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    employee_ids = bot_instance.get_employees_only()
    sent_count = 0
    failed_count = 0

    logger.info(f"=== СОЗДАНО ЗАДАНИЕ #{task_id} ===")
    logger.info(f"АДМИНИСТРАТОР: {ADMIN_ID} (НЕ получит задание)")
    logger.info(f"СОТРУДНИКИ: {employee_ids}")

    # Отправляем КАЖДОМУ сотруднику и сохраняем ID сообщений
    for employee_id in employee_ids:
        if employee_id == ADMIN_ID:
            logger.error(f"🚨 КРИТИЧЕСКАЯ ОШИБКА: Попытка отправить задание администратору {ADMIN_ID}!")
            continue

        try:
            sent_message = await context.bot.send_message(
                chat_id=employee_id,
                text=task_message,
                reply_markup=reply_markup
            )
            # Сохраняем ID сообщения для последующего удаления
            bot_instance.save_task_message(task_id, employee_id, sent_message.message_id)
            sent_count += 1
            logger.info(f"✅ Задание #{task_id} отправлено сотруднику {employee_id}, message_id: {sent_message.message_id}")
        except Exception as e:
            failed_count += 1
            logger.error(f"❌ Ошибка отправки задания сотруднику {employee_id}: {e}")

    logger.info(f"=== РЕЗУЛЬТАТ РАССЫЛКИ ЗАДАНИЯ #{task_id} ===")
    logger.info(f"✅ Успешно отправлено: {sent_count}")
    logger.info(f"❌ Ошибок отправки: {failed_count}")
    logger.info(f"👑 Администратору НЕ отправлено: {ADMIN_ID}")

    await update.message.reply_text(
        f"✅ Задание #{task_id} создано!\n\n"
        f"📍 Пункт назначения: {destination}\n"
        f"🏠 Адрес: {address}\n\n"
        f"📤 Отправлено {sent_count} сотрудникам\n"
        f"❌ Ошибок: {failed_count}\n"
        f"👑 Вам (админу) задание НЕ отправлено"
    )

    await show_admin_menu(update, context)

    return ConversationHandler.END

async def receive_photo_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        photo = update.message.photo[-1]
        task_id = context.user_data.get('completing_task_id')

        if task_id:
            if bot_instance.complete_task(task_id, photo.file_id):
                user_info = bot_instance.get_user_info(update.effective_user.id)
                username = user_info[0] if user_info[0] else "Не указан"
                full_name = f"{user_info[1]} {user_info[2]}".strip()

                task_info = bot_instance.get_task_info(task_id)
                destination = task_info[0] if task_info else "Неизвестно"
                address = task_info[1] if task_info else "Неизвестно"

                notification_text = (
                    f"🎉 Задание #{task_id} завершено!\n\n"
                    f"👤 Сотрудник: {full_name}\n"
                    f"📱 Username: @{username}\n"
                    f"📍 Пункт назначения: {destination}\n"
                    f"🏠 Адрес: {address}\n"
                    f"🕐 Время завершения: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                    f"📸 Фото-отчет:"
                )

                try:
                    await context.bot.send_photo(
                        chat_id=ADMIN_ID,
                        photo=photo.file_id,
                        caption=notification_text
                    )
                except Exception as e:
                    logger.error(f"Ошибка отправки уведомления админу: {e}")

                await update.message.reply_text(
                    f"✅ Задание #{task_id} успешно завершено!\n"
                    f"📸 Фото-отчет отправлен администратору.\n\n"
                    f"Спасибо за работу! 👏\n\n"
                    f"Используйте /start для возврата в меню."
                )

                return ConversationHandler.END
            else:
                await update.message.reply_text(
                    "❌ Ошибка при завершении задания. Попробуйте еще раз."
                )
                return ConversationHandler.END
        else:
            await update.message.reply_text(
                "❌ Ошибка: задание не найдено."
            )
            return ConversationHandler.END
    else:
        await update.message.reply_text(
            "❌ Пожалуйста, отправьте фотографию для отчета.\n"
            "Или используйте /cancel для отмены."
        )
        return WAITING_PHOTO

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Операция отменена.")

    user_id = update.effective_user.id
    if bot_instance.is_admin(user_id):
        await show_admin_menu(update, context)
    else:
        await show_employee_menu(update, context)

    return ConversationHandler.END

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Exception while handling an update: {context.error}")

def main():
    logger.info("🚀 Запуск бота...")

    application = Application.builder().token(BOT_TOKEN).build()

    job_queue = application.job_queue

    try:
        timezone = pytz.timezone('Asia/Tashkent')
        reminder_time = time(hour=7, minute=0)

        job_queue.run_daily(
            callback=daily_work_reminder,
            time=reminder_time,
            name="daily_work_reminder"
        )
        logger.info("✅ Планировщик задач настроен")
    except Exception as e:
        logger.warning(f"⚠️ Ошибка настройки планировщика: {e}")
        logger.info("Бот будет работать без автоматических напоминаний")

    task_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern="^create_task$")],
        states={
            DESTINATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_destination)],
            ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_address)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    complete_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(button_handler, pattern="^complete_task$"),
            CallbackQueryHandler(button_handler, pattern="^finish_")
        ],
        states={
            WAITING_PHOTO: [
                MessageHandler(filters.PHOTO, receive_photo_report),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_photo_report)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(task_conv_handler)
    application.add_handler(complete_conv_handler)
    application.add_handler(CallbackQueryHandler(button_handler))

    application.add_error_handler(error_handler)

    logger.info("✅ Бот запущен и работает!")
    print("🤖 Телеграм бот запущен!")
    print(f"👤 Администратор: {ADMIN_ID}")
    print("📋 Бот готов принимать команды...")
    print("⏰ Напоминания в 7:00 (если доступен планировщик)")

    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        logger.info("🛑 Бот остановлен пользователем")
        print("\n🛑 Бот остановлен")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        print(f"❌ Ошибка: {e}")

if __name__ == '__main__':
    main()
