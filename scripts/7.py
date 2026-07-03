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
from collections import deque
from datetime import datetime
from tinydb import TinyDB, Query
import json

load_dotenv()

from settings import (
    bot_allowed_channels,
    bot_allowed_command_roles,
    bot_personality_file,
)

discord_bot_token = os.environ.get("discord_bot_token")
llm_model_path = os.environ.get("llm_model_path")

client = commands.Bot(command_prefix=".")
current_model = llm_model_path

# Índice global de emojis
emoji_index = {}

# ============= SISTEMA DE MEMORIA =============
class ConversationMemory:
    """Memoria con ventana deslizante para cada usuario."""
    
    def __init__(self, max_size=10):
        self.memory = {}  # user_id -> deque de mensajes
        self.max_size = max_size
        self.db = TinyDB("./bot_memories/conversations.json")
        self._load_from_db()
    
    def _load_from_db(self):
        """Carga conversaciones previas desde la base de datos."""
        try:
            all_conversations = self.db.all()
            for conv in all_conversations:
                user_id = conv.get("user_id")
                if user_id not in self.memory:
                    self.memory[user_id] = deque(maxlen=self.max_size)
                
                self.memory[user_id].append({
                    "role": conv.get("role", "user"),
                    "content": conv.get("content", ""),
                    "timestamp": conv.get("timestamp", datetime.now().isoformat())
                })
            print(f"[Memoria] Cargadas {len(all_conversations)} conversaciones")
        except Exception as e:
            print(f"[Memoria] Error al cargar: {e}")
    
    def add_message(self, user_id, message, role="user"):
        """Añade un mensaje a la memoria del usuario."""
        if user_id not in self.memory:
            self.memory[user_id] = deque(maxlen=self.max_size)
        
        msg_entry = {
            "role": role,
            "content": message,
            "timestamp": datetime.now().isoformat()
        }
        
        self.memory[user_id].append(msg_entry)
        
        # Guardar en DB para persistencia
        self.db.insert({
            "user_id": user_id,
            "role": role,
            "content": message,
            "timestamp": msg_entry["timestamp"]
        })
    
    def get_context(self, user_id, include_timestamps=False):
        """Obtiene el contexto de la conversación para la IA."""
        if user_id not in self.memory or not self.memory[user_id]:
            return ""
        
        context = "### Historial de la conversación:\n"
        for msg in self.memory[user_id]:
            role = "Usuario" if msg["role"] == "user" else "Bot"
            timestamp = f" [{msg['timestamp'][:19]}]" if include_timestamps else ""
            context += f"{role}{timestamp}: {msg['content']}\n"
        
        return context
    
    def clear_user_memory(self, user_id):
        """Limpia la memoria de un usuario específico."""
        if user_id in self.memory:
            del self.memory[user_id]
        
        # Limpiar de la DB
        User = Query()
        self.db.remove(User.user_id == user_id)
        print(f"[Memoria] Memoria limpiada para usuario {user_id}")
    
    def get_user_stats(self, user_id):
        """Obtiene estadísticas de la conversación de un usuario."""
        if user_id not in self.memory:
            return {"total_messages": 0, "user_messages": 0, "bot_messages": 0}
        
        total = len(self.memory[user_id])
        user_msgs = sum(1 for m in self.memory[user_id] if m["role"] == "user")
        bot_msgs = total - user_msgs
        
        return {
            "total_messages": total,
            "user_messages": user_msgs,
            "bot_messages": bot_msgs
        }

# Instancia global de memoria
conversation_memory = ConversationMemory(max_size=15)  # Mantiene 15 mensajes por usuario

# ============= FUNCIONES DE EMOJIS =============
def build_emoji_index():
    """Construye un índice de todos los emojis personalizados del servidor."""
    emoji_map = {}

    print("========== INDEXING EMOJIS ==========")

    for guild in client.guilds:
        print(f"{guild.name}: {len(guild.emojis)} emojis")

        for emoji in guild.emojis:
            emoji_map.setdefault(emoji.name, str(emoji))

    print(f"Indexed {len(emoji_map)} unique emoji names.")
    print("=====================================")

    return emoji_map

def resolve_custom_emojis(text):
    """Reemplaza :nombre_emoji: por el emoji real de Discord."""
    def repl(match):
        name = match.group(1)

        if name in emoji_index:
            return emoji_index[name]

        return match.group(0)

    return re.sub(r":([A-Za-z0-9_]+):", repl, text)

# ============= FUNCIONES DE RESPUESTA =============
def should_respond(message):
    """Determina si el bot debe responder al mensaje."""
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

def get_user_info(message):
    """Obtiene información formateada del usuario."""
    user = message.author
    return {
        "name": user.name,
        "discriminator": user.discriminator,
        "id": user.id,
        "display_name": user.display_name,
        "mention": user.mention,
        "formatted": f"{user.name}#{user.discriminator} (ID: {user.id})"
    }

# ============= EVENTOS DEL BOT =============
@client.event
async def on_ready():
    global emoji_index

    print(f"We have logged in as {client.user}")

    await start_up(current_model)

    # Inicializar estado del bot
    db = TinyDB("./bot_memories/bot_state.json")
    db.truncate()
    db.insert({"bot_personality": bot_personality_file})

    # Indexar emojis al iniciar
    emoji_index = build_emoji_index()

    print(f"Connected to {len(client.guilds)} guilds.")
    print(f"[Memoria] Tamaño máximo por usuario: {conversation_memory.max_size} mensajes")

@client.event
async def on_message(server_message):
    if server_message.author == client.user:
        return

    # Verificar si el canal está permitido
    allowed_channel = (
        server_message.guild is None
        or len(bot_allowed_channels) == 0
        or server_message.channel.name in bot_allowed_channels
    )

    if not allowed_channel:
        return

    # Verificar si debe responder
    if not should_respond(server_message):
        return

    await server_message.channel.typing()

    # Obtener estado actual del bot
    db = TinyDB("./bot_memories/bot_state.json")
    current_bot_personality = db.all()[0]["bot_personality"]

    # Limpiar la mención del bot del prompt
    prompt = re.sub(
        rf"<@!?{client.user.id}>",
        "",
        server_message.content,
    ).strip()

    # Si fue un reply sin texto, no enviar un prompt vacío
    if not prompt:
        prompt = "."

    # Obtener información del usuario
    user_info = get_user_info(server_message)
    user_id = str(server_message.author.id)

    # Obtener contexto de memoria
    conversation_context = conversation_memory.get_context(user_id)

    # Construir el prompt completo para la IA
    enhanced_prompt = f"""
### Información del usuario:
- Nombre: {user_info['formatted']}
- Nick: {user_info['display_name']}
- Mención: {user_info['mention']}

{conversation_context}

### Mensaje actual del usuario:
{prompt}

### Instrucción:
Responde al mensaje del usuario manteniendo coherencia con la conversación anterior.
"""

    # Obtener respuesta de la IA
    output = get_llama_response(
        enhanced_prompt,
        current_model,
        current_bot_personality,
    )

    # Resolver emojis personalizados
    output = resolve_custom_emojis(output)

    # Guardar en memoria (mensaje del usuario)
    conversation_memory.add_message(user_id, prompt, role="user")
    
    # Guardar en memoria (respuesta del bot)
    conversation_memory.add_message(user_id, output, role="bot")

    # Guardar en el sistema existente de add_message
    add_message(
        current_bot_personality,
        {
            "user_message": f"\n### Usuario:\n{user_info['formatted']}\n### Instrucciones:\n{prompt}",
            "bot_message": f"\n### Response:\n{output}\n",
        },
    )

    # Enviar respuesta
    await server_message.channel.send(
        output,
        reference=server_message,
    )

    # Log de estadísticas
    stats = conversation_memory.get_user_stats(user_id)
    print(f"[Memoria] Usuario {user_id}: {stats['total_messages']} mensajes en memoria")

# ============= COMANDOS DE ADMINISTRACIÓN =============
@client.command(name="memory_stats")
@commands.has_any_role(*bot_allowed_command_roles)
async def memory_stats(ctx):
    """Muestra estadísticas de la memoria."""
    user_id = str(ctx.author.id)
    stats = conversation_memory.get_user_stats(user_id)
    
    embed = discord.Embed(
        title="📊 Estadísticas de Memoria",
        description=f"Para <@{user_id}>",
        color=discord.Color.blue()
    )
    embed.add_field(name="Total de mensajes", value=stats["total_messages"], inline=True)
    embed.add_field(name="Mensajes del usuario", value=stats["user_messages"], inline=True)
    embed.add_field(name="Respuestas del bot", value=stats["bot_messages"], inline=True)
    embed.add_field(name="Límite de memoria", value=f"{conversation_memory.max_size} mensajes", inline=True)
    embed.set_footer(text="La memoria se mantiene en orden cronológico")
    
    await ctx.send(embed=embed)

@client.command(name="clear_memory")
@commands.has_any_role(*bot_allowed_command_roles)
async def clear_memory(ctx):
    """Limpia la memoria del usuario que ejecuta el comando."""
    user_id = str(ctx.author.id)
    conversation_memory.clear_user_memory(user_id)
    
    await ctx.send(f"🧹 Memoria limpiada para <@{user_id}>")

@client.command(name="memory_context")
@commands.has_any_role(*bot_allowed_command_roles)
async def memory_context(ctx):
    """Muestra el contexto actual de la conversación."""
    user_id = str(ctx.author.id)
    context = conversation_memory.get_context(user_id)
    
    if not context:
        await ctx.send("📭 No hay memoria para este usuario.")
        return
    
    # Truncar si es muy largo
    if len(context) > 1900:
        context = context[:1900] + "..."
    
    await ctx.send(f"```\n{context}\n```")

# ============= INICIAR BOT =============
client.run(discord_bot_token)
