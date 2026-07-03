import discord
from utils import get_llama_response, start_up, get_llama_models, change_model, get_bot_personalities, set_bot_personality, add_message
from discord.ext import commands
import os
from dotenv import load_dotenv
load_dotenv()
from settings import bot_allowed_channels, bot_allowed_command_roles, bot_personality_file
from tinydb import TinyDB
discord_bot_token = os.environ.get('discord_bot_token')
llm_model_path = os.environ.get('llm_model_path')


client = commands.Bot(command_prefix='.')
current_model = llm_model_path


@client.event
async def on_ready():
    print(f'We have logged in as {client.user}')
    await start_up(current_model)
    db = TinyDB("./bot_memories/bot_state.json")
    db.truncate()
    db.insert({"bot_personality": bot_personality_file})
    # await set_bot_personality(client, bot_personality_file)


@client.event
async def on_message(server_message):
    # ignore messages sent by the client.
    if server_message.author == client.user:
        return

    # check if client should respond to question.
    allowed_channel = False
    if len(bot_allowed_channels) == 0 or server_message.channel.name in bot_allowed_channels:
        allowed_channel = True

    # make sure the question is addressed to the client and not empty.
    if server_message.content.startswith('<@'+str(client.user.id)+'>') and len(server_message.content.split(' ')) >= 2 and allowed_channel == True:
        await server_message.channel.typing()

        db = TinyDB("./bot_memories/bot_state.json")
        current_bot_personality = db.all()[0]["bot_personality"]

        # generate the llama model response to the user question.
        output = get_llama_response(server_message.content.replace('<@'+str(client.user.id)+'>', ""), current_model, current_bot_personality)

        # keeps a simple chat history.
        add_message(current_bot_personality, {"user_message": "\n### Instructions:\n"+server_message.content.replace('<@'+str(client.user.id)+'>', ""), "bot_message": "\n### Response:\n"+output+"\n"})

        # send llama response to the user.
        await server_message.channel.send(output, reference=server_message)



client.run(discord_bot_token)

