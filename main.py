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

CONFIRM_DELAY = 60           # Cooldown สำหรับ Confirm ประกาศ
RESET_INTERVAL = 24 * 60 * 60  # ตรวจทุก 24 ชั่วโมง
WARN_RESET_DAYS = 30         # จำนวนวันก่อน reset warn

# ================= INTENTS =================
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# ================= STORAGE =================
CONFIRM_COOLDOWN = {}
USER_MESSAGE_LOG = {}
GLOBAL_MESSAGE_LOG = {}
USER_WARNINGS = {}
USER_WARNINGS_HISTORY = {}

# ================= LIMITS =================
USER_LIMIT = 2
USER_WINDOW = 120
GLOBAL_LIMIT = 5
GLOBAL_WINDOW = 60

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

TEMPLATES = {
    "urgent": {"title": "🚨 ข่าวด่วน!", "color": 0xff4d4d, "image": "https://media.giphy.com/media/v1.Y2lkPWVjZjA1ZTQ3MXU0NmNrcnU5cWc2bHdveDh6M2Fza3o5OGYyMTZlbG0zbzdidnlzOCZlcD12MV9naWZzX3NlYXJjaCZjdD1n/s1sc0ojbL7SIO12uKs/giphy.gif"},
    "event": {"title": "🎉 ข่าวกิจกรรม!", "color": 0x4dff88, "image": "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExMnlpNmVvNzZ1NmhweWp5dmRjdjVhMm52cWlkbjcxajRjdzI3MmdzZyZlcD12MV9naWZzX3RyZW5kaW5nJmN0PWc/3NtY188QaxDdC/giphy.gif"},
    "notice": {"title": "📢 แจ้งเตือน!", "color": 0x4da6ff, "image": "https://media.giphy.com/media/v1.Y2lkPWVjZjA1ZTQ3N3ZjY213aGhpcnhmeGYycHUxZGlrYWx6enZsczdzNjUxMGF1OWdlaCZlcD12MV9naWZzX3RyZW5kaW5nJmN0PWc/YBHJyPCU9h1VewdaPZ/giphy.gif"}
}

# ================= HELPERS =================
def get_channel_by_name(guild, name):
    return discord.utils.get(guild.text_channels, name=name)

def get_role_by_name(guild, name):
    return discord.utils.get(guild.roles, name=name)

def is_spam(user_id):
    now = time.time()
    logs = USER_MESSAGE_LOG.get(user_id, [])
    logs = [t for t in logs if now - t <= USER_WINDOW]
    if len(logs) >= USER_LIMIT:
        return True, "Spam user"
    logs.append(now)
    USER_MESSAGE_LOG[user_id] = logs

    g_logs = GLOBAL_MESSAGE_LOG.get("all", [])
    g_logs = [t for t in g_logs if now - t <= GLOBAL_WINDOW]
    if len(g_logs) >= GLOBAL_LIMIT:
        return True, "Spam global"
    g_logs.append(now)
    GLOBAL_MESSAGE_LOG["all"] = g_logs

    return False, ""

def has_suspicious_link(text):
    urls = URL_REGEX.findall(text.lower())
    return any(bad in url for url in urls for bad in SUSPICIOUS_DOMAINS)

def has_mass_mention(text):
    return any(m in text for m in FORBIDDEN_MENTIONS) or text.count("@") > MAX_MENTIONS

def has_banned_words(text):
    t = text.lower()
    return any(w in t for w in BANNED_KEYWORDS)

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

# ================= MODAL + ANNOUNCEMENT =================
class AnnouncementModal(discord.ui.Modal):
    message = discord.ui.TextInput(label="ข้อความประกาศ", style=discord.TextStyle.paragraph)

    def __init__(self, template, roles, channel, author):
        super().__init__(title="📝 ส่งประกาศ")
        self.template = template
        self.roles = roles
        self.channel = channel
        self.author = author

    async def on_submit(self, interaction: discord.Interaction):
        text = self.message.value
        member = interaction.user

        spam, _ = is_spam(member.id)
        risk = ai_scam_score(text)

        if spam or has_suspicious_link(text) or has_mass_mention(text) or has_banned_words(text) or risk >= 50:
            await interaction.response.send_message(
                f"🚫 ระบบป้องกันอัตโนมัติ Block / Risk={risk}%",
                ephemeral=True
            )
            await punish(member, f"AI Risk {risk}% / Spam / Link / MassMention")
            await log_spam(interaction.guild, member, f"AI Risk {risk}% / Spam / Link / MassMention", member)
            return

        mention_text = " ".join(r.mention for r in self.roles)
        embed = discord.Embed(
            title=self.template["title"],
            description=text,
            color=self.template["color"],
            timestamp=datetime.utcnow()
        )
        embed.set_author(name=str(member), icon_url=member.display_avatar.url)
        embed.set_image(url=self.template["image"])

        view = ConfirmView(member, embed, mention_text, self.channel)
        await interaction.response.send_message("📢 Preview ประกาศ", embed=embed, view=view, ephemeral=True)

# ================= CONFIRM =================
class ConfirmView(discord.ui.View):
    def __init__(self, author, embed, mention, channel):
        super().__init__(timeout=None)
        self.author = author
        self.embed = embed
        self.mention = mention
        self.channel = channel

    @discord.ui.button(label="✅ Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, _):
        if interaction.user != self.author:
            return

        now = time.time()
        last = CONFIRM_COOLDOWN.get(interaction.user.id, 0)
        if now - last < CONFIRM_DELAY:
            await interaction.response.send_message("⏳ กรุณารอ", ephemeral=True)
            return

        CONFIRM_COOLDOWN[interaction.user.id] = now
        await self.channel.send(content=self.mention, embed=self.embed)
        await interaction.response.edit_message(content="✔ ส่งเรียบร้อย", view=None, embed=None)

# ================= SELECTS =================
class RoleSelect(discord.ui.Select):
    def __init__(self, template, channel):
        options = [
            discord.SelectOption(label=role.name, value=str(role.id))
            for role in template["guild"].roles if role != template["guild"].default_role
        ]
        super().__init__(placeholder="เลือก Role ที่ต้องการ Tag (หลายตัวได้)",
                         min_values=0, max_values=len(options), options=options)
        self.template = template
        self.channel = channel

    async def callback(self, interaction: discord.Interaction):
        roles = [interaction.guild.get_role(int(rid)) for rid in self.values if interaction.guild.get_role(int(rid))]
        if not roles:
            await interaction.response.send_message("❌ ไม่มี Role ที่เลือก", ephemeral=True)
            return

        modal = AnnouncementModal(self.template, roles, self.channel, interaction.user)
        await interaction.response.send_modal(modal)

class ChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, template):
        super().__init__(channel_types=[discord.ChannelType.text])
        self.template = template

    async def callback(self, interaction: discord.Interaction):
        if not self.values:
            await interaction.response.send_message("❌ ไม่พบช่องนี้", ephemeral=True)
            return

        # แปลง ID เป็น Channel Object เพื่อป้องกันล้มเหลว
        channel_obj = interaction.guild.get_channel(int(self.values[0].id)) if isinstance(self.values[0], discord.abc.Snowflake) else interaction.guild.get_channel(int(self.values[0]))
        if not channel_obj:
            await interaction.response.send_message("❌ ไม่พบช่องนี้", ephemeral=True)
            return

        view = discord.ui.View(timeout=None)
        view.add_item(RoleSelect(self.template, channel_obj))
        await interaction.response.send_message("เลือก Role ที่ต้องการ Tag", view=view, ephemeral=True)

class TemplateSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="เลือก Template",
            options=[discord.SelectOption(label=key, value=key) for key in TEMPLATES]
        )

    async def callback(self, interaction: discord.Interaction):
        template = TEMPLATES[self.values[0]].copy()
        template["guild"] = interaction.guild

        view = discord.ui.View(timeout=None)
        view.add_item(ChannelSelect(template))
        await interaction.response.send_message("เลือกช่องประกาศ", view=view, ephemeral=True)

class AnnouncementView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TemplateSelect())

# ================= ON_MESSAGE AUTO PROTECT =================
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    text = message.content
    member = message.author
    guild = message.guild

    risk = ai_scam_score(text)
    if has_suspicious_link(text) or has_mass_mention(text) or has_banned_words(text) or risk >= 50:
        try:
            await message.delete()
        except:
            pass

        await log_spam(guild, member, f"Auto Detect | AI Risk {risk}% | Message blocked", bot.user)
        await punish(member, f"Auto Detect | AI Risk {risk}%")
        try:
            await member.send(f"🚨 ข้อความของคุณถูกลบ\nเหตุผล: AI Scam Risk {risk}%")
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
    await bot.tree.sync()
    if not reset_warns.is_running():
        reset_warns.start()
    print(f"Bot online as {bot.user}")

# ================= COMMAND =================
@bot.command(name="ane")
@commands.has_permissions(administrator=True)
async def ane(ctx):
    """📢 ส่งประกาศ (Admin เท่านั้น)"""
    await ctx.send("🛠 Admin Announcement Panel", view=AnnouncementView())

# ================= RUN =================
bot.run(os.getenv("TOKEN"))
