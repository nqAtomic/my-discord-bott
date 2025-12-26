import os
import time
import sqlite3
import threading
from datetime import timedelta

import discord
from discord.ext import commands
from discord import app_commands
from flask import Flask, render_template_string

# ---------------- CONFIG ----------------
PREFIX = "&"
LOG_CHANNEL = "mod-logs"
WELCOME_CHANNEL = "welcome"
BAD_WORDS = ["badword1", "badword2"]  # edit
PORT = 10000

# ---------------- BOT ----------------
intents = discord.Intents.all()
bot = commands.Bot(command_prefix=PREFIX, intents=intents)
tree = bot.tree

# ---------------- DATABASE ----------------
db = sqlite3.connect("database.db", check_same_thread=False)
cursor = db.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS warns (user_id INTEGER, reason TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS levels (user_id INTEGER, xp INTEGER, level INTEGER)")
db.commit()

# ---------------- DASHBOARD ----------------
app = Flask(__name__)

HTML = """
<!DOCTYPE html>
<html>
<head>
<title>Bot Dashboard</title>
<style>
body { background:#0f172a; color:white; font-family:Arial; text-align:center }
.card { background:#1e293b; padding:20px; margin:20px; border-radius:12px }
</style>
</head>
<body>
<h1>🤖 Discord Bot Dashboard</h1>

<div class="card">
<h2>⚠️ Total Warnings</h2>
<p>{{ warns }}</p>
</div>

<div class="card">
<h2>📊 Users with Levels</h2>
<p>{{ users }}</p>
</div>

</body>
</html>
"""

@app.route("/")
def home():
    cursor.execute("SELECT COUNT(*) FROM warns")
    warns = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(DISTINCT user_id) FROM levels")
    users = cursor.fetchone()[0]
    return render_template_string(HTML, warns=warns, users=users)

def run_dashboard():
    app.run(host="0.0.0.0", port=PORT)

# ---------------- UTIL ----------------
async def log_action(guild, msg):
    channel = discord.utils.get(guild.text_channels, name=LOG_CHANNEL)
    if channel:
        await channel.send(msg)

user_messages = {}

# ---------------- EVENTS ----------------
@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {bot.user}")

@bot.event
async def on_member_join(member):
    channel = discord.utils.get(member.guild.text_channels, name=WELCOME_CHANNEL)
    if channel:
        await channel.send(f"👋 Welcome {member.mention} to **{member.guild.name}**!")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Bad word filter
    for word in BAD_WORDS:
        if word in message.content.lower():
            await message.delete()
            await message.channel.send(
                f"⚠️ {message.author.mention} bad words are not allowed!",
                delete_after=3
            )
            await log_action(message.guild, f"🚫 Bad word removed from {message.author}")
            return

    # Anti-spam
    now = time.time()
    uid = message.author.id
    user_messages.setdefault(uid, []).append(now)
    user_messages[uid] = [t for t in user_messages[uid] if now - t < 5]
    if len(user_messages[uid]) > 6:
        await message.delete()
        return

    # Level system
    cursor.execute("SELECT xp, level FROM levels WHERE user_id=?", (uid,))
    data = cursor.fetchone()
    if not data:
        cursor.execute("INSERT INTO levels VALUES (?, ?, ?)", (uid, 1, 0))
    else:
        xp, level = data
        xp += 1
        if xp >= (level + 1) * 50:
            level += 1
            await message.channel.send(
                f"🎉 {message.author.mention} reached **Level {level}**!"
            )
        cursor.execute(
            "UPDATE levels SET xp=?, level=? WHERE user_id=?",
            (xp, level, uid)
        )
    db.commit()

    await bot.process_commands(message)

# ---------------- PREFIX COMMANDS ----------------
@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason="No reason"):
    await member.kick(reason=reason)
    await ctx.send(f"👢 Kicked {member}")
    await log_action(ctx.guild, f"👢 {member} kicked | {reason}")

@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="No reason"):
    await member.ban(reason=reason)
    await ctx.send(f"⛔ Banned {member}")
    await log_action(ctx.guild, f"⛔ {member} banned | {reason}")

@bot.command()
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount=5):
    await ctx.channel.purge(limit=amount + 1)
    await ctx.send(f"🧹 Cleared {amount} messages", delete_after=3)

@bot.command()
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, minutes: int):
    await member.timeout(timedelta(minutes=minutes))
    await ctx.send(f"🔇 Muted {member} for {minutes} minutes")

@bot.command()
@commands.has_permissions(manage_messages=True)
async def warn(ctx, member: discord.Member, *, reason="No reason"):
    cursor.execute("INSERT INTO warns VALUES (?, ?)", (member.id, reason))
    db.commit()
    await ctx.send(f"⚠️ Warned {member}: {reason}")

@bot.command()
async def warns(ctx, member: discord.Member):
    cursor.execute("SELECT reason FROM warns WHERE user_id=?", (member.id,))
    rows = cursor.fetchall()
    if not rows:
        await ctx.send("✅ No warnings.")
    else:
        text = "\n".join([f"{i+1}. {r[0]}" for i, r in enumerate(rows)])
        await ctx.send(f"⚠️ Warnings:\n{text}")

@bot.command()
async def level(ctx):
    cursor.execute("SELECT xp, level FROM levels WHERE user_id=?", (ctx.author.id,))
    xp, lvl = cursor.fetchone()
    await ctx.send(f"📊 Level: **{lvl}** | XP: **{xp}**")

# ---------------- SLASH COMMANDS ----------------
@tree.command(name="ban", description="Ban a member")
@app_commands.checks.has_permissions(ban_members=True)
async def slash_ban(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason"):
    await member.ban(reason=reason)
    await interaction.response.send_message(f"⛔ Banned {member}")

@tree.command(name="kick", description="Kick a member")
@app_commands.checks.has_permissions(kick_members=True)
async def slash_kick(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason"):
    await member.kick(reason=reason)
    await interaction.response.send_message(f"👢 Kicked {member}")

# ---------------- RUN ----------------
threading.Thread(target=run_dashboard).start()
bot.run(os.getenv("TOKEN"))
