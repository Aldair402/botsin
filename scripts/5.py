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


def build_emoji_index(client):
    emoji_map = {}

    print("========== INDEXING EMOJIS ==========")

    for guild in client.guilds:
        print(f"{guild.name}: {len(guild.emojis)} emojis")

        for emoji in guild.emojis:
            # Mantener el primero encontrado si hay nombres repetidos
            emoji_map.setdefault(emoji.name, str(emoji))

    print(f"Indexed {len(emoji_map)} unique emoji names.")
    print("=====================================")

    return emoji_map


emoji_index = {}


def resolve_custom_emojis(text):
    def repl(match):
        name = match.group(1)

        if name in emoji_index:
            print(f"[Emoji] {name} -> {emoji_index[name]}")
            return emoji_index[name]

        print(f"[Emoji] Not found: {name}")
        return match.group(0)

    return re.sub(r":([A-Za-z0-9_]+):", repl, text)


@client.event
async def on_ready():
    global emoji_index

    print(f"We have logged in as {client.user}")

    await start_up(current_model)

    db = TinyDB("./bot_memories/bot_state.json")
    db.truncate()
    db.insert({"bot_personality": bot_personality_file})

    emoji_index = build_emoji_index(client)


@client.event
async def on_message(server_message):
    if server_message.author == client.user:
        return

    allowed_channel = (
        len(bot_allowed_channels) == 0
        or server_message.channel.name in bot_allowed_channels
    )

    if (
        client.user in server_message.mentions
        and len(server_message.content.split()) >= 2
        and allowed_channel
    ):
        await server_message.channel.typing()

        db = TinyDB("./bot_memories/bot_state.json")
        current_bot_personality = db.all()[0]["bot_personality"]

        prompt = server_message.content.replace(
            f"<@{client.user.id}>", ""
        )

        output = get_llama_response(
            prompt,
            current_model,
            current_bot_personality,
        )

        print("RAW:", repr(output))

        output = resolve_custom_emojis(output)

        print("FINAL:", repr(output))

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
