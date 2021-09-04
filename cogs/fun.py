import discord
from discord import embeds
from discord.ext import commands
import random

class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='penis')
    @commands.guild_only()
    async def penis(self, ctx):
        rng = random.randint(0, 15)
        embed = discord.Embed(
            description=f'8' + (rng * '=' + 'D'),
            color=random.randint(0, 0xffffff)
        )
        embed.set_author(name=ctx.message.author.name + '\'s penis size', icon_url=ctx.message.author.avatar_url)
        await ctx.send(embed=embed)

    @commands.command(name="howgay")
    @commands.guild_only()
    async def howgay(self, ctx):
        rng = random.randint(0, 100)
        embed = discord.Embed(
            description=f"You are " + str(rng) + "% gay" + " 🏳️‍🌈",
            color=random.randint(0, 0xffffff)
        )
        embed.set_author(name=ctx.author.name, icon_url=ctx.author.avatar_url)
        await ctx.send(embed=embed)

    @commands.command(name="simp")
    @commands.guild_only()
    async def simp(self, ctx):
        rng = random.randint(0, 100)
        embed = discord.Embed(
            description=f'You are ' + str(rng) + '% simp' + ' 🥺',
            color=0xFF69B4
        )
        embed.set_author(name=ctx.author.name, icon_url=ctx.author.avatar_url)
        await ctx.send(embed=embed)

def setup(bot):
    bot.add_cog(Fun(bot))
