import re
import discord
from utils import (
    get_llama_response,
    start_up,
    get_llama_models,
    change_model,
    get_bot_personalities,
    set_bot_personality,
    add_message,
)
from discord.ext import commands
import os
from dotenv import load_dotenv

load_dotenv()

from settings import (
    bot_allowed_channels,
    bot_allowed_command_roles,
    bot_personality_file,
)
from tinydb import TinyDB

discord_bot_token = os.environ.get("discord_bot_token")
llm_model_path = os.environ.get("llm_model_path")

client = commands.Bot(command_prefix=".")
current_model = llm_model_path


def resolve_custom_emojis(text):
    def replace(match):
        name = match.group(1)
        emoji = discord.utils.get(client.emojis, name=name)

        if emoji:
            return str(emoji)

        return match.group(0)

    return re.sub(r":([A-Za-z0-9_]+):", replace, text)


def should_respond(message):
    # DM
    if message.guild is None:
        return True

    # Mention
    if client.user in message.mentions:
        return True

    # Reply al bot
    if message.reference:
        try:
            replied = message.reference.resolved

            if replied is None:
                return False

            return replied.author.id == client.user.id

        except AttributeError:
            pass

    return False


@client.event
async def on_ready():
    print(f"We have logged in as {client.user}")

    await start_up(current_model)

    db = TinyDB("./bot_memories/bot_state.json")
    db.truncate()
    db.insert({"bot_personality": bot_personality_file})

    print(f"Connected to {len(client.guilds)} guilds.")


@client.event
async def on_message(server_message):
    if server_message.author == client.user:
        return

    allowed_channel = (
        server_message.guild is None
        or len(bot_allowed_channels) == 0
        or server_message.channel.name in bot_allowed_channels
    )

    if not allowed_channel:
        return

    if not should_respond(server_message):
        return

    await server_message.channel.typing()

    db = TinyDB("./bot_memories/bot_state.json")
    current_bot_personality = db.all()[0]["bot_personality"]

    prompt = re.sub(
        rf"<@!?{client.user.id}>",
        "",
        server_message.content,
    ).strip()

    # Si fue un reply sin texto, no enviar un prompt vacío
    if not prompt:
        prompt = "."

    output = get_llama_response(
        prompt,
        current_model,
        current_bot_personality,
    )

    output = resolve_custom_emojis(output)

    add_message(
        current_bot_personality,
        {
            "user_message": "\n### Instructions:\n" + prompt,
            "bot_message": "\n### Response:\n" + output + "\n",
        },
    )

    await server_message.channel.send(
        output,
        reference=server_message,
    )


client.run(discord_bot_token)
