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

# ============= SISTEMA DE MEMORIA MEJORADO =============
class ConversationMemory:
    """Memoria con ventana deslizante para cada usuario."""
    
    def __init__(self, max_size=15):
        self.memory = {}  # user_id -> deque de mensajes
        self.user_info = {}  # user_id -> información del usuario
        self.max_size = max_size
        self.db = TinyDB("./bot_memories/conversations.json")
        self.user_db = TinyDB("./bot_memories/users.json")  # Nueva DB para usuarios
        self._load_from_db()
        self._load_users_from_db()
    
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
            print(f"[Memoria] Error al cargar conversaciones: {e}")
    
    def _load_users_from_db(self):
        """Carga información de usuarios desde la base de datos."""
        try:
            all_users = self.user_db.all()
            for user in all_users:
                user_id = user.get("user_id")
                if user_id:
                    self.user_info[user_id] = {
                        "name": user.get("name", "Desconocido"),
                        "discriminator": user.get("discriminator", "0000"),
                        "display_name": user.get("display_name", "Desconocido"),
                        "global_name": user.get("global_name", ""),
                        "first_seen": user.get("first_seen", datetime.now().isoformat()),
                        "last_seen": user.get("last_seen", datetime.now().isoformat()),
                        "message_count": user.get("message_count", 0)
                    }
            print(f"[Memoria] Cargados {len(all_users)} usuarios")
        except Exception as e:
            print(f"[Memoria] Error al cargar usuarios: {e}")
    
    def update_user_info(self, user):
        """Actualiza o crea información del usuario."""
        user_id = str(user.id)
        
        if user_id not in self.user_info:
            # Nuevo usuario
            self.user_info[user_id] = {
                "name": user.name,
                "discriminator": user.discriminator,
                "display_name": user.display_name,
                "global_name": user.global_name if hasattr(user, 'global_name') else "",
                "first_seen": datetime.now().isoformat(),
                "last_seen": datetime.now().isoformat(),
                "message_count": 0
            }
            
            # Guardar en DB
            self.user_db.insert({
                "user_id": user_id,
                "name": user.name,
                "discriminator": user.discriminator,
                "display_name": user.display_name,
                "global_name": user.global_name if hasattr(user, 'global_name') else "",
                "first_seen": datetime.now().isoformat(),
                "last_seen": datetime.now().isoformat(),
                "message_count": 0
            })
            print(f"[Memoria] Nuevo usuario registrado: {user.name}#{user.discriminator} (ID: {user_id})")
        else:
            # Actualizar usuario existente
            self.user_info[user_id]["last_seen"] = datetime.now().isoformat()
            self.user_info[user_id]["message_count"] += 1
            
            # Actualizar en DB
            User = Query()
            self.user_db.update({
                "last_seen": datetime.now().isoformat(),
                "message_count": self.user_info[user_id]["message_count"]
            }, User.user_id == user_id)
    
    def add_message(self, user_id, message, role="user", user=None):
        """Añade un mensaje a la memoria del usuario."""
        if user_id not in self.memory:
            self.memory[user_id] = deque(maxlen=self.max_size)
        
        msg_entry = {
            "role": role,
            "content": message,
            "timestamp": datetime.now().isoformat()
        }
        
        self.memory[user_id].append(msg_entry)
        
        # Preparar datos para la DB con información de usuario
        db_entry = {
            "user_id": user_id,
            "role": role,
            "content": message,
            "timestamp": msg_entry["timestamp"]
        }
        
        # Añadir información del usuario si está disponible
        if user_id in self.user_info:
            db_entry["user_name"] = self.user_info[user_id].get("name", "Desconocido")
            db_entry["user_discriminator"] = self.user_info[user_id].get("discriminator", "0000")
            db_entry["user_display_name"] = self.user_info[user_id].get("display_name", "Desconocido")
        
        # Guardar en DB
        self.db.insert(db_entry)
    
    def get_user_info_formatted(self, user_id):
        """Obtiene información formateada del usuario."""
        if user_id not in self.user_info:
            return "Usuario desconocido"
        
        info = self.user_info[user_id]
        return f"{info['name']}#{info['discriminator']} (display: {info['display_name']})"
    
    def get_context(self, user_id, include_timestamps=False, include_user_info=True):
        """Obtiene el contexto de la conversación para la IA."""
        if user_id not in self.memory or not self.memory[user_id]:
            return ""
        
        context = ""
        
        # Incluir información del usuario
        if include_user_info and user_id in self.user_info:
            info = self.user_info[user_id]
            context += f"### Información del usuario:\n"
            context += f"- Nombre: {info['name']}#{info['discriminator']}\n"
            context += f"- Nick: {info['display_name']}\n"
            if info.get('global_name'):
                context += f"- Nombre global: {info['global_name']}\n"
            context += f"- Total de mensajes: {info['message_count']}\n"
            context += f"- Miembro desde: {info['first_seen'][:10]}\n\n"
        
        context += "### Historial de la conversación:\n"
        for msg in self.memory[user_id]:
            role = "Usuario" if msg["role"] == "user" else "Bot"
            timestamp = f" [{msg['timestamp'][:19]}]" if include_timestamps else ""
            context += f"{role}{timestamp}: {msg['content']}\n"
        
        return context
    
    def clear_user_memory(self, user_id):
        """Limpia la memoria de un usuario específico."""
        if user_id in self.memory:
            del self.memory[user_id]
        
        # Limpiar conversaciones de la DB
        User = Query()
        self.db.remove(User.user_id == user_id)
        print(f"[Memoria] Memoria limpiada para usuario {user_id}")
    
    def get_user_stats(self, user_id):
        """Obtiene estadísticas de la conversación de un usuario."""
        if user_id not in self.memory:
            return {
                "total_messages": 0, 
                "user_messages": 0, 
                "bot_messages": 0,
                "user_info": self.user_info.get(user_id, {})
            }
        
        total = len(self.memory[user_id])
        user_msgs = sum(1 for m in self.memory[user_id] if m["role"] == "user")
        bot_msgs = total - user_msgs
        
        return {
            "total_messages": total,
            "user_messages": user_msgs,
            "bot_messages": bot_msgs,
            "user_info": self.user_info.get(user_id, {})
        }
    
    def get_all_users(self):
        """Obtiene todos los usuarios registrados."""
        return self.user_info
    
    def search_by_username(self, username):
        """Busca usuarios por nombre."""
        results = []
        for user_id, info in self.user_info.items():
            if username.lower() in info['name'].lower() or username.lower() in info['display_name'].lower():
                results.append({
                    "user_id": user_id,
                    "info": info
                })
        return results

# Instancia global de memoria
conversation_memory = ConversationMemory(max_size=15)

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

def get_user_info(user):
    """Obtiene información detallada del usuario."""
    return {
        "id": str(user.id),
        "name": user.name,
        "discriminator": user.discriminator,
        "display_name": user.display_name,
        "global_name": user.global_name if hasattr(user, 'global_name') else "",
        "mention": user.mention,
        "avatar_url": user.display_avatar.url if hasattr(user, 'display_avatar') else None,
        "created_at": user.created_at.isoformat() if hasattr(user, 'created_at') else None,
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
    print(f"[Memoria] Usuarios registrados: {len(conversation_memory.get_all_users())}")

@client.event
async def on_message(server_message):
    if server_message.author == client.user:
        return

    # Actualizar información del usuario
    conversation_memory.update_user_info(server_message.author)

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
    user_info = get_user_info(server_message.author)
    user_id = str(server_message.author.id)

    # Obtener contexto de memoria
    conversation_context = conversation_memory.get_context(user_id)

    # Construir el prompt completo para la IA
    enhanced_prompt = f"""
### Información del usuario:
- Nombre: {user_info['formatted']}
- Nick: {user_info['display_name']}
- Mención: {user_info['mention']}
- ID: {user_info['id']}

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

    # Guardar en memoria (mensaje del usuario) con información del usuario
    conversation_memory.add_message(user_id, prompt, role="user", user=server_message.author)
    
    # Guardar en memoria (respuesta del bot)
    conversation_memory.add_message(user_id, output, role="bot", user=server_message.author)

    # Guardar en el sistema existente de add_message
    add_message(
        current_bot_personality,
        {
            "user_message": f"\n### Usuario:\n{user_info['formatted']}\n### Instrucciones:\n{prompt}",
            "bot_message": f"\n### Response:\n{output}\n",
            "user_info": user_info,  # Guardar información completa
        },
    )

    # Enviar respuesta
    await server_message.channel.send(
        output,
        reference=server_message,
    )

    # Log de estadísticas
    stats = conversation_memory.get_user_stats(user_id)
    print(f"[Memoria] Usuario {user_info['formatted']}: {stats['total_messages']} mensajes en memoria")

# ============= COMANDOS DE ADMINISTRACIÓN MEJORADOS =============
@client.command(name="memory_stats")
@commands.has_any_role(*bot_allowed_command_roles)
async def memory_stats(ctx):
    """Muestra estadísticas de la memoria del usuario actual."""
    user_id = str(ctx.author.id)
    stats = conversation_memory.get_user_stats(user_id)
    user_info = stats.get('user_info', {})
    
    embed = discord.Embed(
        title="📊 Estadísticas de Memoria",
        description=f"Para <@{user_id}>",
        color=discord.Color.blue()
    )
    
    if user_info:
        embed.add_field(name="Usuario", value=f"{user_info.get('name', 'N/A')}#{user_info.get('discriminator', '0000')}", inline=True)
        embed.add_field(name="Nick", value=user_info.get('display_name', 'N/A'), inline=True)
        embed.add_field(name="Total mensajes", value=user_info.get('message_count', 0), inline=True)
    
    embed.add_field(name="Mensajes en memoria", value=stats["total_messages"], inline=True)
    embed.add_field(name="Mensajes del usuario", value=stats["user_messages"], inline=True)
    embed.add_field(name="Respuestas del bot", value=stats["bot_messages"], inline=True)
    embed.add_field(name="Límite de memoria", value=f"{conversation_memory.max_size} mensajes", inline=True)
    embed.set_footer(text="La memoria se mantiene en orden cronológico")
    
    await ctx.send(embed=embed)

@client.command(name="user_info")
@commands.has_any_role(*bot_allowed_command_roles)
async def user_info_cmd(ctx, user_id: str = None):
    """Muestra información de un usuario específico."""
    if not user_id:
        user_id = str(ctx.author.id)
    
    # Buscar el usuario en la DB
    if user_id in conversation_memory.user_info:
        info = conversation_memory.user_info[user_id]
        embed = discord.Embed(
            title=f"👤 Información del Usuario",
            description=f"ID: {user_id}",
            color=discord.Color.gold()
        )
        embed.add_field(name="Nombre", value=f"{info['name']}#{info['discriminator']}", inline=True)
        embed.add_field(name="Nick", value=info['display_name'], inline=True)
        if info.get('global_name'):
            embed.add_field(name="Nombre Global", value=info['global_name'], inline=True)
        embed.add_field(name="Primera vez", value=info['first_seen'][:19], inline=True)
        embed.add_field(name="Última vez", value=info['last_seen'][:19], inline=True)
        embed.add_field(name="Total mensajes", value=info.get('message_count', 0), inline=True)
        
        await ctx.send(embed=embed)
    else:
        await ctx.send(f"❌ Usuario {user_id} no encontrado en la base de datos.")

@client.command(name="list_users")
@commands.has_any_role(*bot_allowed_command_roles)
async def list_users(ctx):
    """Lista todos los usuarios registrados."""
    users = conversation_memory.get_all_users()
    
    if not users:
        await ctx.send("📭 No hay usuarios registrados.")
        return
    
    embed = discord.Embed(
        title="👥 Usuarios Registrados",
        description=f"Total: {len(users)} usuarios",
        color=discord.Color.green()
    )
    
    # Ordenar por última vez visto
    sorted_users = sorted(users.items(), key=lambda x: x[1]['last_seen'], reverse=True)
    
    for user_id, info in sorted_users[:10]:  # Mostrar los 10 más recientes
        name = f"{info['name']}#{info['discriminator']}"
        last_seen = info['last_seen'][:19]
        messages = info.get('message_count', 0)
        embed.add_field(
            name=name,
            value=f"ID: {user_id}\nÚltima vez: {last_seen}\nMensajes: {messages}",
            inline=False
        )
    
    if len(sorted_users) > 10:
        embed.set_footer(text=f"Y {len(sorted_users) - 10} usuarios más...")
    
    await ctx.send(embed=embed)

@client.command(name="search_user")
@commands.has_any_role(*bot_allowed_command_roles)
async def search_user(ctx, *, username: str):
    """Busca usuarios por nombre."""
    results = conversation_memory.search_by_username(username)
    
    if not results:
        await ctx.send(f"🔍 No se encontraron usuarios con: `{username}`")
        return
    
    embed = discord.Embed(
        title="🔍 Resultados de Búsqueda",
        description=f"Encontrados {len(results)} usuarios para: `{username}`",
        color=discord.Color.blue()
    )
    
    for result in results[:10]:
        info = result['info']
        user_id = result['user_id']
        name = f"{info['name']}#{info['discriminator']}"
        embed.add_field(
            name=name,
            value=f"ID: {user_id}\nNick: {info['display_name']}\nMensajes: {info.get('message_count', 0)}",
            inline=False
        )
    
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
    context = conversation_memory.get_context(user_id, include_user_info=True)
    
    if not context:
        await ctx.send("📭 No hay memoria para este usuario.")
        return
    
    # Truncar si es muy largo
    if len(context) > 1900:
        context = context[:1900] + "..."
    
    await ctx.send(f"```\n{context}\n```")

@client.command(name="export_users")
@commands.has_any_role(*bot_allowed_command_roles)
async def export_users(ctx):
    """Exporta la lista de usuarios a un archivo JSON."""
    users = conversation_memory.get_all_users()
    
    export_path = f"./bot_memories/users_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    with open(export_path, "w") as f:
        json.dump(users, f, indent=2)
    
    await ctx.send(f"✅ Usuarios exportados a: `{export_path}`")

# ============= INICIAR BOT =============
client.run(discord_bot_token)
