import os
import re
import time
from datetime import datetime
from threading import Thread

import discord
from discord.ext import commands, tasks
from flask import Flask

# ================= FLASK SERVER =================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

keep_alive()

# ================= CONFIG =================
YELLOW_ROLE_NAME = "⚠️ Yellow Card"
BLACK_ROLE_NAME = "⛔ Black Card"

LOG_WARN_CHANNEL = "warn-log"
LOG_BAN_CHANNEL = "ban-log"
LOG_SPAM_CHANNEL = "spam-log"

RESET_INTERVAL = 24 * 60 * 60
WARN_RESET_DAYS = 30

# ================= INTENTS =================
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# ================= STORAGE =================
USER_MESSAGE_LOG = {}  # {user_id: [{"time": ..., "content": ...}, ...]}
GLOBAL_MESSAGE_LOG = {}
USER_WARNINGS = {}
USER_WARNINGS_HISTORY = {}

# ================= LIMITS =================
USER_LIMIT = 3          # จำนวนข้อความต่อ window
USER_WINDOW = 10        # วินาที
MAX_DUPLICATE = 2       # จำนวนครั้งที่ส่งข้อความซ้ำถือว่า spam

MAX_MENTIONS = 5
FORBIDDEN_MENTIONS = ["@everyone", "@here"]

SUSPICIOUS_DOMAINS = [
    "bit.ly", "tinyurl", "grabify", "iplogger",
    "free-nitro", "discord-gift", "steam-nitro"
]

BANNED_KEYWORDS = [
    "free nitro", "แจก nitro", "verify account",
    "steam gift", "คลิกลิงก์"
]

URL_REGEX = re.compile(r"https?://[^\s]+")

# ================= HELPERS =================
def get_channel_by_name(guild, name):
    return discord.utils.get(guild.text_channels, name=name)

def get_role_by_name(guild, name):
    return discord.utils.get(guild.roles, name=name)

def ai_scam_score(text):
    score = 0
    t = text.lower()
    for word in BANNED_KEYWORDS:
        if word in t:
            score += 30

    urls = URL_REGEX.findall(t)
    for url in urls:
        for bad in SUSPICIOUS_DOMAINS:
            if bad in url:
                score += 50

    mention_count = text.count("@")
    if "@everyone" in text or "@here" in text:
        score += 20
    elif mention_count > MAX_MENTIONS:
        score += 10

    if len(text) > 300:
        score += 10

    return min(score, 100)

def has_suspicious_link(text):
    urls = URL_REGEX.findall(text.lower())
    return any(bad in url for url in urls for bad in SUSPICIOUS_DOMAINS)

def has_mass_mention(text):
    if any(m in text for m in FORBIDDEN_MENTIONS):
        return True
    if text.count("@") > MAX_MENTIONS:
        return True
    return False

def has_banned_words(text):
    t = text.lower()
    return any(w in t for w in BANNED_KEYWORDS)

# ================= SPAM CHECK =================
def is_spam(user_id, content):
    now = time.time()
    logs = USER_MESSAGE_LOG.get(user_id, [])
    logs = [l for l in logs if now - l["time"] <= USER_WINDOW]

    # ตรวจ spam จากจำนวนข้อความใน window
    if len(logs) >= USER_LIMIT:
        logs.append({"time": now, "content": content})
        USER_MESSAGE_LOG[user_id] = logs
        return True, "Spam user (rate limit)"

    # ตรวจ spam จากข้อความซ้ำ
    duplicate_count = sum(1 for l in logs if l["content"] == content)
    if duplicate_count >= MAX_DUPLICATE:
        logs.append({"time": now, "content": content})
        USER_MESSAGE_LOG[user_id] = logs
        return True, "Spam user (duplicate)"

    logs.append({"time": now, "content": content})
    USER_MESSAGE_LOG[user_id] = logs
    return False, ""

# ================= PUNISH =================
async def punish(member, reason):
    guild = member.guild
    USER_WARNINGS[member.id] = USER_WARNINGS.get(member.id, 0) + 1
    count = USER_WARNINGS[member.id]

    USER_WARNINGS_HISTORY.setdefault(member.id, []).append({
        "time": int(time.time()),
        "reason": reason
    })

    yellow = get_role_by_name(guild, YELLOW_ROLE_NAME)
    black = get_role_by_name(guild, BLACK_ROLE_NAME)

    if count < 3:
        if yellow:
            await member.add_roles(yellow, reason=reason)
            await log_warn(guild, member, reason, member)
        return False

    if black:
        await member.add_roles(black, reason="ครบ 3 ใบเหลือง")
        await log_ban(guild, member, reason, bot.user)
        await member.ban(reason="ครบ 3 ใบเหลือง (Black Card)", delete_message_days=1)
        return True

# ================= LOG =================
def create_log_embed(title, user, reason, staff, color):
    embed = discord.Embed(title=title, color=color, timestamp=datetime.utcnow())
    embed.add_field(name="👤 ผู้ใช้", value=f"{user} ({user.id})", inline=False)
    embed.add_field(name="📝 เหตุผล", value=reason, inline=False)
    embed.add_field(name="🛡 ผู้ดำเนินการ", value=f"{staff} ({staff.id})", inline=False)
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.set_footer(text="Security System")
    return embed

async def log_warn(guild, user, reason, staff):
    ch = get_channel_by_name(guild, LOG_WARN_CHANNEL)
    if ch:
        await ch.send(embed=create_log_embed("🟡 WARN | ใบเหลือง", user, reason, staff, 0xffcc00))

async def log_spam(guild, user, reason, staff):
    ch = get_channel_by_name(guild, LOG_SPAM_CHANNEL)
    if ch:
        await ch.send(embed=create_log_embed("⚠️ SECURITY | Spam/Abuse", user, reason, staff, 0xff8800))

async def log_ban(guild, user, reason, staff):
    ch = get_channel_by_name(guild, LOG_BAN_CHANNEL)
    if ch:
        await ch.send(embed=create_log_embed("🔴 BAN | ใบดำ", user, reason, staff, 0xff0000))

# ================= ON_MESSAGE =================
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    text = message.content
    member = message.author
    guild = message.guild

    spam, reason_spam = is_spam(member.id, text)
    risk = ai_scam_score(text)
    mass_mention = has_mass_mention(text)

    if spam or has_suspicious_link(text) or has_banned_words(text) or mass_mention or risk >= 50:
        try:
            await message.delete()
        except:
            pass

        full_reason = ""
        if spam:
            full_reason += reason_spam
        if mass_mention:
            full_reason += (" | Mass Mention" if full_reason else "Mass Mention")
        if risk >= 50:
            full_reason += (f" | AI Risk {risk}%" if full_reason else f"AI Risk {risk}%")
        if has_suspicious_link(text):
            full_reason += (" | Suspicious Link" if full_reason else "Suspicious Link")
        if has_banned_words(text):
            full_reason += (" | Banned Word" if full_reason else "Banned Word")

        await log_spam(guild, member, f"Auto Detect | {full_reason} | Message blocked", bot.user)
        await punish(member, f"Auto Detect | {full_reason}")
        try:
            await member.send(f"🚨 ข้อความของคุณถูกลบ\nเหตุผล: {full_reason}")
        except:
            pass
        return

    await bot.process_commands(message)

# ================= RESET WARN TASK =================
@tasks.loop(seconds=RESET_INTERVAL)
async def reset_warns():
    now = int(time.time())
    reset_seconds = WARN_RESET_DAYS * 24 * 60 * 60

    for user_id, history in list(USER_WARNINGS_HISTORY.items()):
        last_warn_time = history[-1]["time"] if history else 0
        if now - last_warn_time >= reset_seconds:
            USER_WARNINGS[user_id] = 0
            USER_WARNINGS_HISTORY[user_id] = []
            print(f"Reset warn ของ user_id={user_id}")

# ================= READY =================
@bot.event
async def on_ready():
    if not reset_warns.is_running():
        reset_warns.start()
    print(f"Bot online as {bot.user}")

# ================= RUN =================
bot.run(os.getenv("TOKEN"))
