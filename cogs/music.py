import asyncio
import datetime as dt
import enum
import random
import re
import typing as t
from enum import Enum

import aiohttp
import discord
import wavelink
from discord.ext import commands

URL_REGEX = r"(?i)\b((?:https?://|www\d{0,3}[.]|[a-z0-9.\-]+[.][a-z]{2,4}/)(?:[^\s()<>]+|\(([^\s()<>]+|(\([^\s()<>]+\)))*\))+(?:\(([^\s()<>]+|(\([^\s()<>]+\)))*\)|[^\s`!()\[\]{};:'\".,<>?«»“”‘’]))"
LYRICS_URL = "https://some-random-api.ml/lyrics?title="
HZ_BANDS = (20, 40, 63, 100, 150, 250, 400, 450, 630, 1000, 1600, 2500, 4000, 10000, 16000)
TIME_REGEX = r"([0-9]{1,2})[:ms](([0-9]{1,2})s?)?"
OPTIONS = {
    "1️⃣": 0,
    "2⃣": 1,
    "3⃣": 2,
    "4⃣": 3,
    "5⃣": 4,
}


class AlreadyConnectedToChannel(commands.CommandError):
    pass


class NoVoiceChannel(commands.CommandError):
    pass


class QueueIsEmpty(commands.CommandError):
    pass


class NoTracksFound(commands.CommandError):
    pass


class PlayerIsAlreadyPaused(commands.CommandError):
    pass


class PlayerIsAlreadyPlaying(commands.CommandError):
    pass


class NoMoreTracks(commands.CommandError):
    pass


class NoPreviousTracks(commands.CommandError):
    pass


class InvalidRepeatMode(commands.CommandError):
    pass


class VolumeTooLow(commands.CommandError):
    pass


class VolumeTooHigh(commands.CommandError):
    pass


class MaxVolume(commands.CommandError):
    pass


class MinVolume(commands.CommandError):
    pass


class NoLyricsFound(commands.CommandError):
    pass


class InvalidEQPreset(commands.CommandError):
    pass


class NonExistentEQBand(commands.CommandError):
    pass


class EQGainOutOfBounds(commands.CommandError):
    pass


class InvalidTimeString(commands.CommandError):
    pass


class RepeatMode(Enum):
    NONE = 0
    SINGLE = 1
    ALL = 2

class Queue: 
    def __init__(self):
        self._queue = []
        self.position = 0
        self.repeat_mode = RepeatMode.NONE

    @property
    def is_empty(self):
        return not self._queue

    @property
    def current_track(self):
        if not self._queue:
            raise QueueIsEmpty

        if self.position <= len(self._queue) - 1:
            return self._queue[self.position]

    @property
    def upcoming(self):
        if not self._queue:
            raise QueueIsEmpty

        return self._queue[self.position + 1:]

    @property
    def history(self):
        if not self._queue:
            raise QueueIsEmpty
        
        return self._queue[:self.position]

    @property
    def length(self):
        return len(self._queue)

    def add(self, *args):
        self._queue.extend(args)

    def get_next_track(self):
        if not self._queue:
            raise QueueIsEmpty

        self.position += 1
        
        if self.position < 0:
            return None
        elif self.position > len(self._queue) - 1:
            if self.repeat_mode == RepeatMode.ALL:
                self.position = 0
            else:
                return None

        return self._queue[self.position]

    def shuffle(self):
        if not self._queue:
            raise QueueIsEmpty

        upcoming = self.upcoming
        random.shuffle(upcoming)
        self._queue = self._queue[:self.position + 1]
        self._queue.extend(upcoming)

    def set_repeat_mode(self, mode):
        if mode == "none":
            self.repeat_mode = RepeatMode.NONE
        elif mode == "single":
            self.repeat_mode = RepeatMode.SINGLE
        elif mode == "all":
            self.repeat_mode = RepeatMode.ALL

    def empty(self):
        self._queue.clear()
        self.position = 0


class Player(wavelink.Player):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.queue = Queue()
        self.eq_levels = [0.] * 15

    async def connect(self, ctx, channel=None):
        if self.is_connected:
            raise AlreadyConnectedToChannel
        
        if (channel := getattr(ctx.author.voice, "channel", channel)) is None:
            raise NoVoiceChannel

        await super().connect(channel.id)
        return channel

    async def teardown(self):
        try:
            await self.destroy()
        except KeyError:
            pass

    async def add_tracks(self, ctx, tracks):
        if not tracks:
            raise NoTracksFound

        if isinstance(tracks, wavelink.TrackPlaylist):
            self.queue.add(*tracks.tracks)
        elif len(tracks) == 1:
            self.queue.add(tracks[0])
            
            embed = discord.Embed(
            description=f"Added **{tracks[0].title}** to the queue. [{ctx.message.author.mention}]",
            color=0xff0000
        )
            await ctx.send(embed=embed)
        else:
            if (track := await self.choose_track(ctx, tracks)) is not None:
                self.queue.add(track)
                embed = discord.Embed(
            description=f"Added **{track.title}** to the queue. [{ctx.message.author.mention}]",
            color=0xff0000
        )
            await ctx.send(embed=embed)

        if not self.is_playing and not self.queue.is_empty:
            await self.start_playback()

    async def choose_track(self, ctx, tracks):
        def _check(r, u):
            return (
                r.emoji in OPTIONS.keys()
                and u == ctx.author
                and r.message.id == msg.id
            )

        embed = discord.Embed(
            title="Choose a song",
            description=(
                "\n".join(
                    f"**{i+1}.** {t.title} ({t.length//60000}:{str(t.length%60).zfill(2)})"
                    for i, t in enumerate(tracks[:5])
                )
            ),
            color=0xff0000,
            timestamp=dt.datetime.utcnow()
        )
        embed.set_footer(text=f"Invoked by {ctx.author.display_name}", icon_url=ctx.author.avatar_url)

        msg = await ctx.send(embed=embed)
        for emoji in list(OPTIONS.keys())[:min(len(tracks), len(OPTIONS))]:
            await msg.add_reaction(emoji)
        
        try:
            reaction, _ = await self.bot.wait_for("reaction_add", timeout=60.0, check=_check)
        except asyncio.TimeoutError:
            await msg.delete()
            await ctx.message.delete()
        else:
            await msg.delete()
            return tracks[OPTIONS[reaction.emoji]]

    async def start_playback(self):
        await self.play(self.queue.current_track)

    async def advance(self):
        try:
            if (track := self.queue.get_next_track()) is not None:
                await self.play(track)
        except QueueIsEmpty:
            pass

    async def repeat_track(self):
        await self.play(self.queue.current_track)
        

class Music(commands.Cog, wavelink.WavelinkMixin):
    def __init__(self, bot):
        self.bot = bot
        self.wavelink = wavelink.Client(bot=bot)
        self.bot.loop.create_task(self.start_nodes())

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if not member.bot and after.channel is None:
            if not [m for m in before.channel.members if not m.bot]:
                await self.get_player(member.guild).teardown()

    @wavelink.WavelinkMixin.listener()
    async def on_node_ready(self, node):
        print(f" Wavelink node `{node.identifier}` ready.")

    @wavelink.WavelinkMixin.listener("on_track_stuck")
    @wavelink.WavelinkMixin.listener("on_track_end")
    @wavelink.WavelinkMixin.listener("on_track_exception")
    async def on_player_stop(self, node, payload):
        if payload.player.queue.repeat_mode == RepeatMode.SINGLE:
            await payload.player.repeat_track()
        else:
            await payload.player.advance()


    async def cog_check(self, ctx):
        if isinstance(ctx.channel, discord.DMChannel):
            embed = discord.Embed(
            description="Music commands are not available in DMs.",
            color=0xff0000
        )
            await ctx.send(embed=embed)
            return False

        return True

    async def start_nodes(self):
        await self.bot.wait_until_ready()

        nodes = {
            "MAIN": {
                "host": "127.0.0.1",
                "port": 2333,
                "rest_uri": "http://127.0.0.1:2333",
                "password": "youshallnotpass",
                "identifier": "MAIN",
                "region": "europe",
            }
        }

        for node in nodes.values():
            await self.wavelink.initiate_node(**node)

    def get_player(self, obj):
        if isinstance(obj, commands.Context):
            return self.wavelink.get_player(obj.guild.id, cls=Player, context=obj)
        elif isinstance(obj, discord.Guild):
            return self.wavelink.get_player(obj.id, cls=Player)

    @commands.command(name="connect", aliases=["join", "j"], help="Connects the bot to your voice channel or channel given by your query")
    async def connect_command(self, ctx, *, channel: t.Optional[discord.VoiceChannel]):
        player = self.get_player(ctx)
        channel = await player.connect(ctx, channel)
        embed = discord.Embed(
            description=f"Connected to **{channel.name}!** [{ctx.message.author.mention}]",
            color=0xff0000
        )
        await ctx.send(embed=embed)

    @connect_command.error
    async def connect_command_error(self, ctx, exc):
        if isinstance(exc, AlreadyConnectedToChannel):
            embed = discord.Embed(
            description="Already connected to a voice channel!",
            color=0xff0000
        )
            await ctx.send(embed=embed)
        elif isinstance(exc, NoVoiceChannel):
            embed = discord.Embed(
            description="You must type voice channel name or be connected to a voice channel to use this command!",
            color=0xff0000
        )
            await ctx.send(embed=embed)

    @commands.command(name="disconnect", aliases=["leave", "l", "dc"], help="Disconnects the bot from your voice channel and clears the queue")
    async def disconnect_command(self, ctx):
        player = self.get_player(ctx)
        await player.teardown()
        await ctx.message.add_reaction("👌")

    @commands.command(name="play", aliases=["p"], help="Loads your input and adds it to the queue; If there is no playing track, then it will start playing")
    async def play_command(self, ctx, *, query: t.Optional[str]):
        player = self.get_player(ctx)

        if not player.is_connected:
            await player.connect(ctx)

        if query is None:
            if player.queue.is_empty:
                raise QueueIsEmpty

            await player.set_pause(False)
            embed = discord.Embed(
            description=f"Playback resumed! [{ctx.message.author.mention}]",
            color=0xff0000
        )
            await ctx.send(embed=embed)

        # elif query.startswith("https://soundcloud.com"):
        #     await player.add_tracks(ctx, await self.wavelink.get_tracks(query))
        
        else:
            query = query.strip("<>")
            if not re.match(URL_REGEX, query):
                query = f"ytsearch:{query}"

            await player.add_tracks(ctx, await self.wavelink.get_tracks(query))

    @play_command.error
    async def play_command_error(self, ctx, exc):
        if isinstance(exc, QueueIsEmpty):
            embed = discord.Embed(
            description="The queue is empty!",
            color=0xff0000
        )
            await ctx.send(embed=embed)
        elif isinstance(exc, NoVoiceChannel):
            embed = discord.Embed(
            description="You must be in a voice channel to use this command!",
            color=0xff0000
        )
            await ctx.send(embed=embed)

    @commands.command(name="pause", aliases=["break"], help="Pauses playback")
    async def pause_command(self, ctx):
        player = self.get_player(ctx)
        
        if player.is_paused:
            raise PlayerIsAlreadyPaused
        
        await player.set_pause(True)
        embed = discord.Embed(
            description=f"Playback paused! [{ctx.message.author.mention}]",
            color=0xff0000
        )
        await ctx.send(embed=embed)

    @pause_command.error
    async def pause_command_error(self, ctx, exc):
        if isinstance(exc, PlayerIsAlreadyPaused):
            embed = discord.Embed(
            description="Playback is already paused!",
            color=0xff0000
        )
            await ctx.send(embed=embed)

    @commands.command(name="resume", aliases=["unpause", "continue"], help="Resumes playback")
    async def resume_command(self, ctx):
        player = self.get_player(ctx)

        if player.is_playing:
            raise PlayerIsAlreadyPlaying
        
        await player.set_pause(False)
        embed = discord.Embed(
            description=f"Playback resumed [{ctx.message.author.mention}]",
            color=0xff0000
        )
        await ctx.send(embed=embed)

    @resume_command.error
    async def resume_command_error(self, ctx, exc):
        if isinstance(exc, PlayerIsAlreadyPlaying):
            embed = discord.Embed(
            description="Already playing!",
            color=0xff0000
        )
            await ctx.send(embed=embed)

    @commands.command(name="clear", aliases=["stop", "c", "empty"], help="Removes all tracks from the queue")
    async def clear_command(self, ctx):
        player = self.get_player(ctx)
        player.queue.empty()
        await player.stop()
        embed = discord.Embed(
            description=f"Queue cleared! [{ctx.message.author.mention}]",
            color=0xff0000
        )
        await ctx.send(embed=embed)

    @commands.command(name="skip", aliases=["next", "s"], help="Skips to the next song")
    async def skip_command(self, ctx):
        player = self.get_player(ctx)

        if not player.queue.upcoming:
            raise NoMoreTracks

        await player.stop()
        embed = discord.Embed(
            description=f"Skipped **{player.queue.current_track}** [{ctx.message.author.mention}]",
            color=0xff0000
        )
        await ctx.send(embed=embed)
        await ctx.message.add_reaction("👌")

    @skip_command.error
    async def skip_command_error(self, ctx, exc):
        if isinstance(exc, QueueIsEmpty):
            embed = discord.Embed(
                description="The queue is empty!",
                color=0xff0000
            )
            await ctx.send(embed=embed)
        elif isinstance(exc, NoMoreTracks):
            embed = discord.Embed(
                description="There are no more tracks in the queue!",
                color=0xff0000
            )
            await ctx.send(embed=embed)

    @commands.command(name="back", aliases=["previous", "b"], help="Skips to the previous song")
    async def back_command(self, ctx):
        player = self.get_player(ctx)

        if not player.queue.history:
            raise NoPreviousTracks

        player.queue.position -= 2
        await player.stop()
        await ctx.message.add_reaction("👌")

    @back_command.error
    async def back_command_error(self, ctx, exc):
        if isinstance(exc, QueueIsEmpty):
            embed = discord.Embed(
                description="The queue is empty!",
                color=0xff0000
            )
            await ctx.send(embed=embed)
        elif isinstance(exc, NoPreviousTracks):
            embed = discord.Embed(
                description="There are no previous tracks in the queue!",
                color=0xff0000
            )
            await ctx.send(embed=embed)

    @commands.command(name="shuffle", aliases=["sh"], help="Randomizes the current order of tracks in the queue")
    async def shuffle_command(self, ctx):
        player = self.get_player(ctx)
        player.queue.shuffle()
        await ctx.message.add_reaction("👌")
        embed = discord.Embed(
            description=f"Queue shuffled [{ctx.message.author.mention}]",
            color=0xff0000
        )
        await ctx.send(embed=embed)
    
    @shuffle_command.error
    async def shuffle_command_error(self, ctx, exc):
        if isinstance (exc, QueueIsEmpty):
            embed = discord.Embed(
                description="The queue is empty!",
                color=0xff0000
            )
            await ctx.send(embed=embed)

    @commands.command(name="loop", aliases=["repeat"], help="Starts looping single track or all queue | modes: none, single, all")
    async def loop_command(self, ctx, mode: str):
        if mode not in ("none", "single", "all"):
            raise InvalidRepeatMode

        player = self.get_player(ctx)
        player.queue.set_repeat_mode(mode)
        embed = discord.Embed(
            description=f"Repeat mode has been set to **{mode}** [{ctx.message.author.mention}]",
            color=0xff0000
        )
        await ctx.send(embed=embed)

    @loop_command.error
    async def loop_command_error(self, ctx, exc):
        if isinstance(exc, InvalidRepeatMode):
            embed = discord.Embed(
                description="Invalid loop mode! (Modes: none, single, all)",
                color=0xff0000
            )
            await ctx.send(embed=embed)

    @commands.command(name="queue", aliases=["q", "list"], help="Displays the queue")
    async def queue_command(self, ctx):
        player = self.get_player(ctx)
        
        if player.queue.is_empty:
            raise QueueIsEmpty

        # embed = discord.Embed(
        #     color=0xff0000,
        #     timestamp=dt.datetime.utcnow()
        # )
        # embed.set_footer(text=f"Requested by {ctx.author.display_name}", icon_url=ctx.author.avatar_url)
        # embed.add_field(
        #     name="Currently playing",
        #     value=getattr(player.queue.current_track, "title", "No tracks currently playing."),
        #     inline=False
        # )
        # if upcoming := player.queue.upcoming:
        #     embed.add_field(
        #         name="Next up",
        #         value=f"\n".join(t.title for t in upcoming),
        #         inline=False
        #     )

        # await ctx.send(embed=embed)
        embed = discord.Embed(
            color=0xff0000,
            timestamp=dt.datetime.utcnow(),
            description = f"**Currently playing:** {player.queue.current_track.title}\n"
        )
        embed.set_footer(text=f"Requested by {ctx.author.display_name}", icon_url=ctx.author.avatar_url)

        i = 2

        for song in player.queue.upcoming:
            embed.description += f"\n**{i}.** {song.title}"
            i += 1
        
        await ctx.send(embed=embed)

    @queue_command.error
    async def queue_command_error(self, ctx, exc):
        if isinstance(exc, QueueIsEmpty):
            embed = discord.Embed(
            description="The queue is empty!",
            color=0xff0000
        )
            await ctx.send(embed=embed)

    @commands.group(name="volume", invoke_without_command=True, aliases=["vol", "v"], help="Sets the player's volume | DONT USE")
    async def volume_group(self, ctx, volume: int):
        player = self.get_player(ctx)

        if volume < 0:
            raise VolumeTooLow
        
        if volume > 1000:
            raise VolumeTooHigh

        await player.set_volume(volume)
        embed = discord.Embed(
            description=f"Volume set to **{volume:,}%** [{ctx.message.author.mention}]",
            color=0xff0000
        )
        await ctx.send(embed=embed)

    @volume_group.error
    async def volume_group_error(self, ctx, exc):
        if isinstance(exc, VolumeTooLow):
            embed = discord.Embed(
            description="The volume must be **0%** or above!",
            color=0xff0000
        )
            await ctx.send(embed=embed)
        elif isinstance(exc, VolumeTooHigh):
            embed = discord.Embed(
            description=f"The volume must be **1000%** or below!",
            color=0xff0000
        )
            await ctx.send(embed=embed)

    @volume_group.command(name="up")
    async def volume_up_command(self, ctx):
        player = self.get_player(ctx)

        if player.volume == 1000:
            raise MaxVolume
        
        await player.set_volume(value := min(player.volume + 10, 1000))
        embed = discord.Embed(
            description=f"Volume set to **{value:,}% [{ctx.message.author.mention}]",
            color=0xff0000
        )
        await ctx.send(embed=embed)

    @volume_up_command.error
    async def volume_up_command_error(self, ctx, exc):
        if isinstance(exc, MaxVolume):
            embed = discord.Embed(
            description="The player is already at max volume!",
            color=0xff0000
        )
            await ctx.send(embed=embed)

    @volume_group.command(name="down")
    async def volume_down_command(self, ctx):
        player = self.get_player(ctx)

        if player.volume == 0:
            raise MinVolume
        
        await player.set_volume(value := max(0, player.volume - 10))
        embed = discord.Embed(
            description=f"Volume set to **{value:,}% [{ctx.message.author.mention}]",
            color=0xff0000
        )
        await ctx.send(embed=embed)

    @volume_down_command.error
    async def volume_down_command_error(self, ctx, exc):
        if isinstance(exc, MinVolume):
            embed = discord.Embed(
            description="The player is already at min volume!",
            color=0xff0000
        )
            await ctx.send(embed=embed)

    @commands.command(name="lyrics", aliases=["lyric", "ly"], help="Displays lyrics for the currently playing track or searches for lyrics based on your query")
    async def lyrics_command(self, ctx, *, name: t.Optional[str]):
        player = self.get_player(ctx)
        name = name or player.queue.current_track.title

        async with ctx.typing():
            async with aiohttp.request("GET", LYRICS_URL + name.replace(' ', '%20'), headers={}) as r:
                if not 200 <= r.status <= 299:
                    raise NoLyricsFound

                data = await r.json()

                if len(data["lyrics"]) > 2000:
                    return await ctx.send(f"<{data['links']['genius']}>")

                embed = discord.Embed(
                    title=data["title"],
                    description=data["lyrics"],
                    colour=0xff0000,
                    timestamp=dt.datetime.utcnow(),
                )
                embed.set_thumbnail(url=data["thumbnail"]["genius"])
                embed.set_author(name=data["author"])
                await ctx.send(embed=embed)

    @lyrics_command.error
    async def lyrics_command_error(self, ctx, exc):
        if isinstance(exc, NoLyricsFound):
            embed = discord.Embed(
            description="No lyrics could be found!",
            color=0xff0000
        )
            await ctx.send(embed=embed)

    @commands.command(name="eq", help="Changes the preset of the equalizer to one of the given in query ('flat', 'boost', 'metal' or 'piano') | DONT USE")
    async def eq_command(self, ctx, preset: str):
        player = self.get_player(ctx)

        eq = getattr(wavelink.eqs.Equalizer, preset, None)
        if not eq:
            raise InvalidEQPreset

        await player.set_eq(eq())
        embed = discord.Embed(
            description=f"Equalizer adjsuted to the **{preset}** preset! [{ctx.message.author.mention}]",
            color=0xff0000
        )
        await ctx.send(embed=embed)

    @eq_command.error
    async def eq_command_error(self, ctx, exc):
        if isinstance(exc, InvalidEQPreset):
            embed = discord.Embed(
            description="The EQ preset must be either **'flat'**, **'boost'**, **'metal'** or **'piano'**",
            color=0xff0000
        )
            await ctx.send(embed=embed)

    @commands.command(name="adveq", aliases=["aeq"], help="Advanced equalizer - changes dB on one of the 15 given bounds. | DONT USE")
    async def adveq_command(self, ctx, band: int, gain: float):
        player = self.get_player(ctx)

        if not 1 <= band <= 15 and band not in HZ_BANDS:
            raise NonExistentEQBand

        if band > 15:
            band = HZ_BANDS.index(band) + 1

        if abs(gain) > 10:
            raise EQGainOutOfBounds

        player.eq_levels[band - 1] = gain / 10
        eq = wavelink.eqs.Equalizer(levels=[(i, gain) for i, gain in enumerate(player.eq_levels)])
        await player.set_eq(eq)
        embed = discord.Embed(
            description=f"Equalizer adjsuted [{ctx.message.author.mention}]",
            color=0xff0000
        )
        await ctx.send(embed=embed)

    @adveq_command.error
    async def adveq_command_error(self, ctx, exc):
        if isinstance(exc, NonExistentEQBand):
            embed = discord.Embed(
            description="This is a 15 band equalizer -- the band number should be between 1 and 15, or one of the following "
                "frequencies: " + ", ".join(str(b) for b in HZ_BANDS),
            color=0xff0000
        )
            await ctx.send(embed=embed)
        elif isinstance(exc, EQGainOutOfBounds):
            embed = discord.Embed(
            description="The EQ gain for any band should be between 10 dB and -10 dB!",
            color=0xff0000
        )
            await ctx.send(embed=embed)

    @commands.command(name="playing", aliases=["np", "nowplaying", "now", "song", "songinfo", "si"], help="Displays info about the currently playing track")
    async def playing_command(self, ctx):
        player = self.get_player(ctx)

        if not player.is_playing:
            PlayerIsAlreadyPaused

        embed=discord.Embed(
            color=0xff0000,
            timestamp=dt.datetime.utcnow()
        )
        embed.set_footer(text=f"Requested by {ctx.author.display_name}", icon_url=ctx.author.avatar_url)
        embed.add_field(name="Currently Playing:", value=player.queue.current_track.title, inline=False)
        embed.add_field(name="Artist", value=player.queue.current_track.author, inline=False)

        position = divmod(player.position, 60000)
        length = divmod(player.queue.current_track.length, 60000)
        embed.add_field(
            name="Position",
            value=f"{int(position[0])}:{round(position[1]/1000):02}/{int(length[0])}:{round(length[1]/1000):02}",
            inline=False
        )

        await ctx.send(embed=embed)

    @playing_command.error
    async def playing_command_error(self, ctx, exc):
        if isinstance(exc, PlayerIsAlreadyPaused):
            embed = discord.Embed(
            description="There is no track currently playing!",
            color=0xff0000
        )
            await ctx.send(embed=embed)
        if isinstance(exc, QueueIsEmpty):
            embed = discord.Embed(
            description="The queue is empty!",
            color=0xff0000
        )
            await ctx.send(embed=embed)

    @commands.command(name="jump", aliases=["skipto"], help="Skips to the specified track")
    async def jump_command(self, ctx, index: int):
        player = self.get_player(ctx)

        if player.queue.is_empty:
            raise QueueIsEmpty

        if not 0 <= index <= player.queue.length:
            raise NoMoreTracks

        player.queue.position = index - 2
        await player.stop()
        embed = discord.Embed(
            description=f"Playing track in postion **{index}!** [{ctx.message.author.mention}]",
            color=0xff0000
        )
        await ctx.send(embed=embed)

    @jump_command.error
    async def jump_command_error(self, ctx, exc):
        if isinstance(exc, QueueIsEmpty):
            embed = discord.Embed(
            description="There are no tracks in the queue!",
            color=0xff0000
        )
            await ctx.send(embed=embed)
        elif isinstance(exc, NoMoreTracks):
            embed = discord.Embed(
            description=f"That index is out of the bounds of the queue!",
            color=0xff0000
        )
            await ctx.send(embed=embed)

    @commands.command(name="restart", aliases=["replay", "rp"], help="Plays the current song from start")
    async def restart_command(self, ctx):
        player = self.get_player(ctx)

        if player.queue.is_empty:
            raise QueueIsEmpty

        await player.seek(0)
        embed = discord.Embed(
            description=f"Track restarted! [{ctx.message.author.mention}]",
            color=0xff0000
        )
        await ctx.send(embed=embed)

    @restart_command.error
    async def restart_command_error(self, ctx, exc):
        if isinstance(exc, QueueIsEmpty):
            embed = discord.Embed(
            description=f"The queue is empty!",
            color=0xff0000
        )
            await ctx.send(embed=embed)

    @commands.command(name="seek", help="Skips to the specified timestamp in the currently playing track | e.g. 1m30s or 30s or 1m0s")
    async def seek_command(self, ctx, position: str):
        player = self.get_player(ctx)

        if player.queue.is_empty:
            raise QueueIsEmpty

        if not (match := re.match(TIME_REGEX, position)):
            raise InvalidTimeString

        if match.group(3):
            secs = (int(match.group(1)) * 60) + (int(match.group(3)))
        else:
            secs = int(match.group(1))

        await player.seek(secs * 1000)
        embed = discord.Embed(
            description=f"Seeked! [{ctx.message.author.mention}]",
            color=0xff0000
        )
        await ctx.send(embed=embed)

def setup(bot):
    bot.add_cog(Music(bot))
