import os

import discord
from discord.ext import commands
from dotenv import load_dotenv
from pretty_help import PrettyHelp

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

bot = commands.Bot(command_prefix=commands.when_mentioned_or("-"), intents=discord.Intents.all(), case_insensitive=True, help_command=PrettyHelp(color=0xff0000, active_time=60, show_index=False))


initial_extensions = ['cogs.music']


if __name__ == '__main__':
    for extension in initial_extensions:
        bot.load_extension(extension)

@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="-help"))
    print("Bot is ready!")

@bot.event
async def on_connect():
    print(f"Connected to Discord (latency: {bot.latency*1000:,.0f} ms)")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.errors.MissingPermissions):
        embed = discord.Embed(
            color=0xff0000
        )
        user_avatar_url = ctx.message.author.avatar_url
        embed.set_author(name=f'You don\'t have enough permissions to use this command', icon_url=user_avatar_url)
        await ctx.send(embed=embed)

@bot.event
async def on_error(self, err, *args, **kwargs):
    raise

@bot.event
async def on_command_error(self, ctx, exc):
    raise getattr(exc, "original", exc)

@bot.event
async def process_commands(msg):
    ctx = await bot.get_context(msg, cls=commands.Context)

    if ctx.command is not None:
            await bot.invoke(ctx)

@bot.event
async def on_message(msg):
    if not msg.author.bot:
        await bot.process_commands(msg)

@bot.event
async def on_command_error(ctx, exc):
    if isinstance(exc, commands.NoPrivateMessage):
        pass

bot.run(TOKEN, reconnect=True)