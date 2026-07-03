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


def resolve_custom_emojis(text, client):
    def replace(match):
        name = match.group(1)

        emoji = discord.utils.get(client.emojis, name=name)

        if emoji:
            print(f"[Emoji] Resolved :{name}: -> {emoji}")
            return str(emoji)

        print(f"[Emoji] Not found: :{name}:")
        return match.group(0)

    return re.sub(r":([A-Za-z0-9_]+):", replace, text)


@client.event
async def on_ready():
    print(f"We have logged in as {client.user}")

    await start_up(current_model)

    db = TinyDB("./bot_memories/bot_state.json")
    db.truncate()
    db.insert({"bot_personality": bot_personality_file})

    print(f"Loaded {len(client.emojis)} custom emojis from {len(client.guilds)} guilds.")


@client.event
async def on_message(server_message):
    # Ignore messages sent by the bot itself.
    if server_message.author == client.user:
        return

    # Check if client should respond.
    allowed_channel = False
    if len(bot_allowed_channels) == 0 or server_message.channel.name in bot_allowed_channels:
        allowed_channel = True

    # Make sure the bot was mentioned.
    if (
        server_message.content.startswith(f"<@{client.user.id}>")
        and len(server_message.content.split(" ")) >= 2
        and allowed_channel
    ):

        await server_message.channel.typing()

        db = TinyDB("./bot_memories/bot_state.json")
        current_bot_personality = db.all()[0]["bot_personality"]

        prompt = server_message.content.replace(f"<@{client.user.id}>", "")

        output = get_llama_response(
            prompt,
            current_model,
            current_bot_personality,
        )

        print("\n========== RAW OUTPUT ==========")
        print(repr(output))
        print("================================")

        output = resolve_custom_emojis(output, client)

        print("\n======== RESOLVED OUTPUT ========")
        print(repr(output))
        print("=================================")

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
