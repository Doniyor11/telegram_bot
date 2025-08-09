import asyncio
import logging
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, PhotoSize
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import sqlite3
from datetime import datetime
import os

BOT_TOKEN = "8249402614:AAFQgtDqZtBByhe3MTU0JsuPRjK94l_HWvY"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()

OPERATOR_ID = None  # ID оператора (нужно установить)
ADMIN_ID = None     # ID админа (нужно установить)

class TaskCreationStates(StatesGroup):
    waiting_destination = State()
    waiting_address = State()

class TaskCompletionStates(StatesGroup):
    waiting_photo_report = State()

def init_db():
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            role TEXT,
            is_active BOOLEAN DEFAULT 1
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            destination TEXT NOT NULL,
            address TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            assigned_to INTEGER,
            status TEXT DEFAULT 'pending',
            completed_at DATETIME,
            photo_report TEXT
        )
    ''')

    conn.commit()
    conn.close()

def get_all_employees():
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, full_name FROM users WHERE role = 'employee' AND is_active = 1")
    employees = cursor.fetchall()
    conn.close()
    return employees

def assign_task(task_id, user_id):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE tasks SET assigned_to = ?, status = 'assigned' WHERE id = ?", (user_id, task_id))
    conn.commit()
    conn.close()

def get_task(task_id):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    task = cursor.fetchone()
    conn.close()
    return task

def complete_task(task_id, photo_file_id):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE tasks SET status = 'completed', completed_at = CURRENT_TIMESTAMP, photo_report = ? WHERE id = ?",
        (photo_file_id, task_id)
    )
    conn.commit()
    conn.close()

@router.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    full_name = message.from_user.full_name or ""

    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT role FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()

    if not user:
        cursor.execute(
            "INSERT OR REPLACE INTO users (user_id, username, full_name, role) VALUES (?, ?, ?, ?)",
            (user_id, username, full_name, "employee")
        )
        conn.commit()
        role = "employee"
    else:
        role = user[0]

    conn.close()

    if role == "operator":
        await message.answer(
            "🔧 Добро пожаловать, оператор!\n\n"
            "Доступные команды:\n"
            "/create_task - Создать новое задание"
        )
    elif role == "admin":
        await message.answer(
            "👑 Добро пожаловать, администратор!\n\n"
            "Вы будете получать уведомления о принятых заданиях."
        )
    else:
        await message.answer(
            "👷 Добро пожаловать, сотрудник!\n\n"
            "Вы будете получать уведомления о новых заданиях."
        )

@router.message(Command("create_task"))
async def cmd_create_task(message: Message, state: FSMContext):
    user_id = message.from_user.id

    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT role FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()

    if not user or user[0] != "operator":
        await message.answer("❌ У вас нет прав для создания заданий.")
        return

    await message.answer("📍 Укажите пункт назначения:")
    await state.set_state(TaskCreationStates.waiting_destination)

@router.message(StateFilter(TaskCreationStates.waiting_destination))
async def process_destination(message: Message, state: FSMContext):
    await state.update_data(destination=message.text)
    await message.answer("🏠 Теперь укажите адрес:")
    await state.set_state(TaskCreationStates.waiting_address)

@router.message(StateFilter(TaskCreationStates.waiting_address))
async def process_address(message: Message, state: FSMContext):
    data = await state.get_data()
    destination = data['destination']
    address = message.text

    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO tasks (destination, address) VALUES (?, ?)",
        (destination, address)
    )
    task_id = cursor.lastrowid
    conn.commit()
    conn.close()

    await message.answer(
        f"✅ Задание создано!\n\n"
        f"📍 Пункт назначения: {destination}\n"
        f"🏠 Адрес: {address}\n\n"
        f"ID задания: {task_id}"
    )

    await state.clear()

    await notify_employees(task_id, destination, address)

async def notify_employees(task_id, destination, address):
    employees = get_all_employees()

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принимаю", callback_data=f"accept_{task_id}")]
    ])

    message_text = (
        f"🚨 Новое задание!\n\n"
        f"📍 Пункт назначения: {destination}\n"
        f"🏠 Адрес: {address}\n"
        f"🕐 Время: {datetime.now().strftime('%H:%M %d.%m.%Y')}"
    )

    for employee_id, username, full_name in employees:
        try:
            await bot.send_message(
                chat_id=employee_id,
                text=message_text,
                reply_markup=keyboard
            )
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение сотруднику {employee_id}: {e}")

@router.callback_query(F.data.startswith("accept_"))
async def handle_accept_task(callback: CallbackQuery):
    task_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    username = callback.from_user.username or "Без username"
    full_name = callback.from_user.full_name or "Неизвестно"

    task = get_task(task_id)
    if not task:
        await callback.answer("❌ Задание не найдено")
        return

    if task[4]:  # assigned_to
        await callback.answer("❌ Задание уже принято другим сотрудником")
        return

    assign_task(task_id, user_id)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏁 Закончил", callback_data=f"complete_{task_id}")]
    ])

    await callback.message.edit_text(
        f"✅ Задание принято!\n\n"
        f"📍 Пункт назначения: {task[1]}\n"
        f"🏠 Адрес: {task[2]}\n"
        f"👤 Исполнитель: {full_name} (@{username})\n\n"
        f"💡 Нажмите 'Закончил' когда выполните задание",
        reply_markup=keyboard
    )

    await callback.answer("✅ Задание принято!")

    if ADMIN_ID:
        try:
            await bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    f"📋 Задание #{task_id} принято!\n\n"
                    f"👤 Исполнитель: {full_name}\n"
                    f"📱 Username: @{username}\n"
                    f"📍 Пункт назначения: {task[1]}\n"
                    f"🏠 Адрес: {task[2]}\n"
                    f"🕐 Время принятия: {datetime.now().strftime('%H:%M %d.%m.%Y')}"
                )
            )
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление админу: {e}")

@router.callback_query(F.data.startswith("complete_"))
async def handle_complete_task(callback: CallbackQuery, state: FSMContext):
    task_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id

    task = get_task(task_id)
    if not task:
        await callback.answer("❌ Задание не найдено")
        return

    if task[4] != user_id:
        await callback.answer("❌ Это не ваше задание")
        return

    if task[5] == 'completed':
        await callback.answer("❌ Задание уже завершено")
        return

    await state.update_data(completing_task_id=task_id)
    await state.set_state(TaskCompletionStates.waiting_photo_report)

    await callback.message.edit_text(
        f"📸 Отправьте фото-отчет о выполненной работе\n\n"
        f"📍 Пункт назначения: {task[1]}\n"
        f"🏠 Адрес: {task[2]}"
    )

    await callback.answer("📸 Отправьте фото-отчет")

@router.message(F.photo, StateFilter(TaskCompletionStates.waiting_photo_report))
async def process_photo_report(message: Message, state: FSMContext):
    data = await state.get_data()
    task_id = data.get('completing_task_id')

    if not task_id:
        await message.answer("❌ Ошибка: задание не найдено")
        await state.clear()
        return

    task = get_task(task_id)
    if not task:
        await message.answer("❌ Задание не найдено")
        await state.clear()
        return

    photo_file_id = message.photo[-1].file_id
    complete_task(task_id, photo_file_id)

    username = message.from_user.username or "Без username"
    full_name = message.from_user.full_name or "Неизвестно"

    await message.answer(
        f"✅ Задание завершено!\n\n"
        f"📍 Пункт назначения: {task[1]}\n"
        f"🏠 Адрес: {task[2]}\n"
        f"📸 Фото-отчет получен"
    )

    if ADMIN_ID:
        try:
            await bot.send_photo(
                chat_id=ADMIN_ID,
                photo=photo_file_id,
                caption=(
                    f"✅ Задание #{task_id} завершено!\n\n"
                    f"👤 Исполнитель: {full_name} (@{username})\n"
                    f"📍 Пункт назначения: {task[1]}\n"
                    f"🏠 Адрес: {task[2]}\n"
                    f"🕐 Время завершения: {datetime.now().strftime('%H:%M %d.%m.%Y')}"
                )
            )
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление админу о завершении: {e}")

    await state.clear()

@router.message(StateFilter(TaskCompletionStates.waiting_photo_report))
async def invalid_photo_report(message: Message):
    await message.answer("❌ Пожалуйста, отправьте фото для отчета")

@router.message(Command("set_admin"))
async def cmd_set_admin(message: Message):
    global ADMIN_ID
    if message.get_args():
        try:
            admin_id = int(message.get_args())
            ADMIN_ID = admin_id

            conn = sqlite3.connect('bot.db')
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO users (user_id, role) VALUES (?, ?)",
                (admin_id, "admin")
            )
            conn.commit()
            conn.close()

            await message.answer(f"✅ Админ установлен: {admin_id}")
        except ValueError:
            await message.answer("❌ Неверный ID")
    else:
        await message.answer("Использование: /set_admin <user_id>")

@router.message(Command("set_operator"))
async def cmd_set_operator(message: Message):
    global OPERATOR_ID
    if message.get_args():
        try:
            operator_id = int(message.get_args())
            OPERATOR_ID = operator_id

            conn = sqlite3.connect('bot.db')
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO users (user_id, role) VALUES (?, ?)",
                (operator_id, "operator")
            )
            conn.commit()
            conn.close()

            await message.answer(f"✅ Оператор установлен: {operator_id}")
        except ValueError:
            await message.answer("❌ Неверный ID")
    else:
        await message.answer("Использование: /set_operator <user_id>")

dp.include_router(router)

async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
