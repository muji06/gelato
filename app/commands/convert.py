import re
import io
import json
import math
import logging

import requests
from bs4 import BeautifulSoup

from discord.ext import commands
import discord

import ffmpeg
import subprocess
import asyncio
from tempfile import NamedTemporaryFile
from database import Servers, Convert, Session
from utils import what_website
from browser import ChromeBrowser

logger = logging.getLogger(__name__)


def convert_size(size_bytes):
   """
   Given size in bytes, convert it into readable number
   """
   if size_bytes == 0:
       return "0B"
   size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
   i = int(math.floor(math.log(size_bytes, 1024)))
   p = math.pow(1024, i)
   s = round(size_bytes / p, 2)
   return "%s %s" % (s, size_name[i])


async def error_reaction(ctx, message):
    """
    Save me some time by wrapping both error message and the x reaction to original command issuer
    """
    await ctx.send(message)
    await ctx.message.add_reaction("❌")


class convert(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.lock = asyncio.Lock()
        # self.pattern: re.Pattern = re.compile(r"https://img-9gag-fun\.9cache\.com.+")

    @commands.command(name='convert', aliases=['c','mp4','con'])
    async def convert(self, ctx: commands.Context, *, url:str = None):
        async with ctx.typing():
            
            if not url:
                await error_reaction(ctx,"No url provided")
                return 
            website = what_website(url)
            if website == "9gag_mobile": #mobile shit link
                mobile = requests.get(url)
                soup = BeautifulSoup(mobile.text)
                contents = json.loads(soup.find("script", type="application/ld+json").text)
                
                url = contents['video']['contentUrl'] # real link here
            elif website == "reel":
                url = ChromeBrowser.reel_download_url(url)

            try:
                # check headers first, don't want to download a whole ass 2gb file just to check size and type
                head_data = requests.head(url, allow_redirects=True).headers
            except:
                await error_reaction(ctx,"Not valid url.")
                return
                      
            content_length = int(head_data.get("Content-Length", 0))
            content_type = head_data.get("Content-Type", "")

            if not "video" in content_type:
                await error_reaction(ctx,"Not a video download link")
                return
            
            if content_length == 0 or content_length > 26000000:
                await error_reaction(ctx,f"File either empty or too big ({convert_size(content_length)})")
                return
            
            
            data = requests.get(url, allow_redirects=True)
            
            delete = False
            async with self.lock: # lock each convert so they are synchronous
                with NamedTemporaryFile(mode="w+") as tf: # use a temporary file for saving
                    try:
                        logger.info(content_type)
                        prefix = re.sub(".*/","",content_type) # content-type = "video/mp4" -> "mp4"
                        if not prefix:
                            await error_reaction(ctx,"Didn't find prefix")
                            raise Exception

                        if website != "reel":
                            # TODO: Investigate why it cannot load all the metadata for input if link is from discord embed
                            process: subprocess.Popen = (
                                    ffmpeg
                                    .input("pipe:", f=f"{prefix}")
                                    .output(tf.name, f='mp4', vcodec='libx264')
                                    .overwrite_output()
                                    .run_async(pipe_stdin=True, pipe_stdout= True)
                                    )
                            
                            process.communicate(input=data.content)

                            tf.seek(0,2) # take me to the last byte of the video
                            
                            vid_size = tf.tell()
                            if tf.tell() < 5: # check for less than 5 bytes(empty file but is binary coded with endline)
                                await error_reaction(ctx,"Didn't find prefix")
                                raise Exception
                            elif tf.tell() > 26000000:
                                await error_reaction(ctx,f"File too big ({convert_size(tf.tell())})")
                                raise Exception
                            
                            tf.seek(0) # back to start so i can stream
                            video = discord.File(tf.name, filename="output.mp4")
                        else:
                            vid_size = content_length
                            video = discord.File(io.BytesIO(data.content), filename="output.mp4")

                        user = str(ctx.author.id)
                        source = website
                        server = str(ctx.guild.id)
                        no_error = True
                        try:
                            server_stats = Session.get(Servers, server)
                            # make sure we have this row
                            if not server_stats: 
                                Session.add(Servers(
                                    server_id = server,
                                    server_name = ctx.guild.name
                                ))
                                Session.commit()
                            # now update the data
                            current_id =  server_stats.total_videos + 1
                            server_stats.total_videos = current_id

                            current_total = server_stats.total_storage + vid_size
                            server_stats.total_storage = current_total

                            Session.add(Convert(
                                server_id = server,
                                user_id = user,
                                source = source,
                                download_size = vid_size
                            ))
                            Session.commit()
                            await ctx.send(f"[{current_id}]Conversion for {ctx.author.mention}\n{convert_size(vid_size)} ({convert_size(current_total)})",file=video, mention_author=False)
                            delete = True
                            no_error = False
                        except Exception as e:
                            await ctx.send("DB error (no stats saved)")
                            logger.error(e)

                        if no_error:
                            await ctx.send(f"Conversion for {ctx.author.mention}\n{convert_size(vid_size)}",file=video, mention_author=False)
                        
                    except Exception as e:
                        await error_reaction(ctx,"Something went wrong!")
                        logger.error(e)
                    finally:
                        if delete:
                            await ctx.message.delete()
                        tf.close()
                        return
                    
    @commands.command(name='exec', aliases=['exe'])
    async def exec(self, ctx: commands.Context, mode = None, *, text = ""):
        if ctx.author.id != 336563297648246785:
            file = discord.File("silicate.jpg")
            await ctx.reply("blehhhh",file=file, ephemeral=True)
            return
        elif not mode:
            await ctx.send("No method provided")
            return
        if mode == "SELECT":
            data = Session.get(Servers, str(ctx.guild.id))
            field = f"""
{data.server_name=}
{data.server_id=}
{data.total_storage=}
{data.total_videos=}
"""
            await ctx.send(field)
            return
        elif mode == "UPDATE":
            if len(text) != 0:
                try:
                    the_dict = json.loads(text)
                    data = Session.get(Servers, str(ctx.guild.id))
                    data.total_storage = the_dict["total_storage"]
                    data.total_videos = the_dict["total_videos"]
                    Session.commit()
                    await ctx.send("Succesfully updated")
                except Exception as e:
                    await ctx.send("invalid json or db failed")
                    logger.error(e)
                    return
        else:
            await ctx.send("invalid")
        
async def setup(bot):
    await bot.add_cog(convert(bot))
