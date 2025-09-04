import os
import discord
import asyncio
import json
import re
import math
import time
from motor.motor_asyncio import AsyncIOMotorClient
from predict import Prediction

TOKEN = os.getenv("DISCORD_TOKEN")
MONGODB_URI = os.getenv("MONGODB_URI")

intents = discord.Intents.default()
intents.message_content = True  # Required for reading message content
bot = discord.Client(intents=intents)

# Initialize predictor and database
predictor = None
db_client = None
db = None

async def initialize_predictor():
    """Initialize the predictor asynchronously"""
    global predictor
    try:
        predictor = Prediction()
        print("Predictor initialized successfully")
    except Exception as e:
        print(f"Failed to initialize predictor: {e}")

async def initialize_database():
    """Initialize MongoDB connection"""
    global db_client, db
    try:
        if not MONGODB_URI:
            print("Warning: MONGODB_URI not set, collection features disabled")
            return

        print(f"Attempting to connect to MongoDB...")
        print(f"URI starts with: {MONGODB_URI[:30]}...")  # Show more characters but keep secure

        # Try different TLS configurations for Railway compatibility
        tls_configs = [
            # Config 1: Standard connection (let MongoDB handle TLS automatically)
            {
                "serverSelectionTimeoutMS": 5000,
                "connectTimeoutMS": 10000,
                "socketTimeoutMS": 20000,
                "maxPoolSize": 1
            },
            # Config 2: Explicit TLS with invalid certificates allowed
            {
                "tls": True,
                "tlsAllowInvalidCertificates": True,
                "serverSelectionTimeoutMS": 5000,
                "connectTimeoutMS": 10000,
                "socketTimeoutMS": 20000,
                "maxPoolSize": 1
            },
            # Config 3: TLS insecure mode
            {
                "tls": True,
                "tlsInsecure": True,
                "serverSelectionTimeoutMS": 5000,
                "connectTimeoutMS": 10000,
                "socketTimeoutMS": 20000,
                "maxPoolSize": 1
            }
        ]

        for i, config in enumerate(tls_configs, 1):
            try:
                print(f"Trying TLS configuration {i}: {list(config.keys())}")
                db_client = AsyncIOMotorClient(MONGODB_URI, **config)

                # Test the connection with shorter timeout
                print("Testing connection with ping...")
                await asyncio.wait_for(db_client.admin.command('ping'), timeout=5)

                db = db_client.pokemon_collector
                print(f"✅ Database initialized successfully with configuration {i}")
                print(f"Database object created: {db is not None}")
                return

            except asyncio.TimeoutError:
                print(f"❌ Config {i} failed: Connection timeout")
            except Exception as e:
                print(f"❌ Config {i} failed: {str(e)[:100]}...")

            # Clean up failed connection
            if 'db_client' in locals() and db_client:
                db_client.close()
            db_client = None
            db = None

        print("❌ All TLS configurations failed - database features will be disabled")

    except Exception as e:
        print(f"❌ Critical error in database initialization: {e}")
        db_client = None
        db = None

def load_pokemon_data():
    """Load Pokemon data from pokemondata.json"""
    try:
        with open('pokemondata.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Failed to load pokemondata.json: {e}")
        return []

def normalize_pokemon_name(name):
    """Remove gender suffixes from Pokemon names for comparison"""
    if name.endswith("-Male") or name.endswith("-Female"):
        if name.endswith("-Male"):
            return name[:-5]  # Remove "-Male"
        else:  # endswith("-Female")
            return name[:-7]  # Remove "-Female"
    return name

def find_pokemon_by_name(name, pokemon_data):
    """Find Pokemon by name (including other language names)"""
    name_lower = name.lower().strip()

    for pokemon in pokemon_data:
        # Check main name
        if pokemon.get('name', '').lower() == name_lower:
            return pokemon

        # Check other language names (only if the key exists and is not None)
        other_names = pokemon.get('other_names')
        if other_names and isinstance(other_names, dict):
            for lang_name in other_names.values():
                if lang_name and isinstance(lang_name, str) and lang_name.lower() == name_lower:
                    return pokemon

    return None

def get_pokemon_variants(base_pokemon_name, pokemon_data):
    """Get all variants of a Pokemon (including the base form)"""
    variants = []
    base_pokemon_name_lower = base_pokemon_name.lower()

    for pokemon in pokemon_data:
        pokemon_name = pokemon.get('name', '')

        # Add the base Pokemon itself
        if pokemon_name.lower() == base_pokemon_name_lower:
            variants.append(pokemon_name)
        # Add variants that belong to this base Pokemon
        elif (pokemon.get('is_variant') and 
              pokemon.get('variant_of', '').lower() == base_pokemon_name_lower):
            variants.append(pokemon_name)

    return variants

def format_pokemon_prediction(name, confidence):
    """Format the Pokemon prediction output, handling gender variants"""
    # Check if the Pokemon name contains gender information
    if name.endswith("-Male") or name.endswith("-Female"):
        # Extract the base name and gender
        if name.endswith("-Male"):
            base_name = name[:-5]  # Remove "-Male"
            gender = "Male"
        else:  # endswith("-Female")
            base_name = name[:-7]  # Remove "-Female"
            gender = "Female"

        # Return formatted string with gender on separate line
        return f"{base_name}: {confidence}\nGender: {gender}"
    else:
        # Return normal format for Pokemon without gender variants
        return f"{name}: {confidence}"

async def get_collectors_for_pokemon(pokemon_name, guild_id):
    """Get all users who have collected this Pokemon in the given guild (excluding AFK users)"""
    if db is None:
        return []

    pokemon_data = load_pokemon_data()
    collectors = []

    # Normalize the spawned Pokemon name (remove gender suffix if present)
    normalized_spawn_name = normalize_pokemon_name(pokemon_name).lower()

    try:
        # Get AFK users for this guild
        afk_users = await get_afk_users(guild_id)

        # Find all collections in this guild
        collections = await db.collections.find({"guild_id": guild_id}).to_list(length=None)

        for collection in collections:
            user_id = collection['user_id']

            # Skip AFK users
            if user_id in afk_users:
                continue

            user_pokemon = collection.get('pokemon', [])

            # Check each Pokemon in user's collection
            for collected_pokemon in user_pokemon:
                # Normalize the collected Pokemon name
                normalized_collected_name = normalize_pokemon_name(collected_pokemon).lower()

                # If the normalized names match, this user should be pinged
                if normalized_collected_name == normalized_spawn_name:
                    collectors.append(user_id)
                    break  # No need to check other Pokemon for this user

            # Also check if user has the base form and this is a variant
            target_pokemon = find_pokemon_by_name(pokemon_name, pokemon_data)
            if target_pokemon and target_pokemon.get('is_variant'):
                base_form = target_pokemon.get('variant_of')
                if base_form:
                    normalized_base_form = normalize_pokemon_name(base_form).lower()
                    for collected_pokemon in user_pokemon:
                        normalized_collected_name = normalize_pokemon_name(collected_pokemon).lower()
                        if normalized_collected_name == normalized_base_form:
                            if user_id not in collectors:  # Avoid duplicates
                                collectors.append(user_id)
                            break

    except Exception as e:
        print(f"Error getting collectors: {e}")

    return collectors

async def get_guild_ping_roles(guild_id):
    """Get the rare and regional ping roles for a guild"""
    if db is None:
        return None, None

    try:
        guild_settings = await db.guild_settings.find_one({"guild_id": guild_id})
        if guild_settings:
            return guild_settings.get('rare_role_id'), guild_settings.get('regional_role_id')
    except Exception as e:
        print(f"Error getting guild ping roles: {e}")

    return None, None

async def set_rare_role(guild_id, role_id):
    """Set the rare Pokemon ping role for a guild"""
    if db is None:
        return "Database not available"

    try:
        result = await db.guild_settings.update_one(
            {"guild_id": guild_id},
            {"$set": {"rare_role_id": role_id}},
            upsert=True
        )
        return "Rare role set successfully!"
    except Exception as e:
        print(f"Error setting rare role: {e}")
        return f"Database error: {str(e)[:100]}"

async def set_regional_role(guild_id, role_id):
    """Set the regional Pokemon ping role for a guild"""
    if db is None:
        return "Database not available"

    try:
        result = await db.guild_settings.update_one(
            {"guild_id": guild_id},
            {"$set": {"regional_role_id": role_id}},
            upsert=True
        )
        return "Regional role set successfully!"
    except Exception as e:
        print(f"Error setting regional role: {e}")
        return f"Database error: {str(e)[:100]}"

async def get_pokemon_ping_info(pokemon_name, guild_id):
    """Get ping information for a Pokemon based on its rarity"""
    if db is None:
        return None

    pokemon_data = load_pokemon_data()
    pokemon = find_pokemon_by_name(pokemon_name, pokemon_data)

    if not pokemon:
        return None

    rarity = pokemon.get('rarity')
    if not rarity:
        return None

    rare_role_id, regional_role_id = await get_guild_ping_roles(guild_id)

    if rarity == "rare" and rare_role_id:
        return f"Rare Ping: <@&{rare_role_id}>"
    elif rarity == "regional" and regional_role_id:
        return f"Regional Ping: <@&{regional_role_id}>"

    return None

async def toggle_user_afk(user_id, guild_id):
    """Toggle user's AFK status for a guild"""
    if db is None:
        return "Database not available", False

    try:
        # Check current status
        current_afk = await db.afk_users.find_one({"user_id": user_id, "guild_id": guild_id})

        if current_afk and current_afk.get('afk', False):
            # User is currently AFK, remove them
            await db.afk_users.delete_one({"user_id": user_id, "guild_id": guild_id})
            return "You are no longer AFK and will be pinged for Pokemon spawns.", False
        else:
            # User is not AFK, add them
            await db.afk_users.update_one(
                {"user_id": user_id, "guild_id": guild_id},
                {"$set": {"user_id": user_id, "guild_id": guild_id, "afk": True}},
                upsert=True
            )
            return "You are now AFK and won't be pinged for Pokemon spawns.", True
    except Exception as e:
        print(f"Error toggling AFK status: {e}")
        return f"Database error: {str(e)[:100]}", False

async def get_afk_users(guild_id):
    """Get list of AFK user IDs for a guild"""
    if db is None:
        return []

    try:
        afk_docs = await db.afk_users.find({"guild_id": guild_id, "afk": True}).to_list(length=None)
        return [doc['user_id'] for doc in afk_docs]
    except Exception as e:
        print(f"Error getting AFK users: {e}")
        return []

async def is_user_afk(user_id, guild_id):
    """Check if a user is AFK"""
    if db is None:
        return False

    try:
        afk_doc = await db.afk_users.find_one({"user_id": user_id, "guild_id": guild_id})
        return afk_doc and afk_doc.get('afk', False)
    except Exception as e:
        print(f"Error checking AFK status: {e}")
        return False

async def add_pokemon_to_collection(user_id, guild_id, pokemon_names):
    """Add Pokemon to user's collection"""
    if db is None:
        return "Database not available"

    if not pokemon_names:
        return "No Pokemon names provided"

    pokemon_data = load_pokemon_data()
    if not pokemon_data:
        return "Pokemon data not available"

    added_pokemon = []
    invalid_pokemon = []

    for name in pokemon_names:
        if not name or not isinstance(name, str):
            continue

        name = name.strip()
        if not name:
            continue

        pokemon = find_pokemon_by_name(name, pokemon_data)

        if pokemon and pokemon.get('name'):
            # If it's a base form, add the main name
            # If it's a variant, add the variant name
            added_pokemon.append(pokemon['name'])
        else:
            invalid_pokemon.append(name)

    if not added_pokemon:
        error_msg = "No valid Pokemon names found"
        if invalid_pokemon:
            error_msg += f". Invalid names: {', '.join(invalid_pokemon[:10])}"
            if len(invalid_pokemon) > 10:
                error_msg += f" and {len(invalid_pokemon) - 10} more..."
        return error_msg

    try:
        # Update or create collection
        result = await db.collections.update_one(
            {"user_id": user_id, "guild_id": guild_id},
            {"$addToSet": {"pokemon": {"$each": added_pokemon}}},
            upsert=True
        )

        # Create response with character limits in mind
        if len(added_pokemon) <= 10:
            response = f"Added {len(added_pokemon)} Pokemon: {', '.join(added_pokemon)}"
        else:
            response = f"Added {len(added_pokemon)} Pokemon: {', '.join(added_pokemon[:10])} and {len(added_pokemon) - 10} more..."

        if invalid_pokemon:
            if len(invalid_pokemon) <= 5:
                response += f"\nInvalid: {', '.join(invalid_pokemon)}"
            else:
                response += f"\nInvalid: {', '.join(invalid_pokemon[:5])} and {len(invalid_pokemon) - 5} more..."

        return response

    except Exception as e:
        print(f"Database error in add_pokemon_to_collection: {e}")
        return f"Database error: {str(e)[:100]}"

async def remove_pokemon_from_collection(user_id, guild_id, pokemon_names):
    """Remove Pokemon from user's collection"""
    if db is None:
        return "Database not available"

    if not pokemon_names:
        return "No Pokemon names provided"

    pokemon_data = load_pokemon_data()
    if not pokemon_data:
        return "Pokemon data not available"

    removed_pokemon = []
    not_found_pokemon = []

    for name in pokemon_names:
        if not name or not isinstance(name, str):
            continue

        name = name.strip()
        if not name:
            continue

        pokemon = find_pokemon_by_name(name, pokemon_data)

        if pokemon and pokemon.get('name'):
            removed_pokemon.append(pokemon['name'])
        else:
            not_found_pokemon.append(name)

    if not removed_pokemon:
        error_msg = "No valid Pokemon names found"
        if not_found_pokemon:
            error_msg += f". Invalid names: {', '.join(not_found_pokemon[:10])}"
            if len(not_found_pokemon) > 10:
                error_msg += f" and {len(not_found_pokemon) - 10} more..."
        return error_msg

    try:
        result = await db.collections.update_one(
            {"user_id": user_id, "guild_id": guild_id},
            {"$pullAll": {"pokemon": removed_pokemon}}
        )

        if result.modified_count > 0:
            # Create response with character limits in mind
            if len(removed_pokemon) <= 10:
                response = f"Removed {len(removed_pokemon)} Pokemon: {', '.join(removed_pokemon)}"
            else:
                response = f"Removed {len(removed_pokemon)} Pokemon: {', '.join(removed_pokemon[:10])} and {len(removed_pokemon) - 10} more..."

            if not_found_pokemon:
                if len(not_found_pokemon) <= 5:
                    response += f"\nInvalid: {', '.join(not_found_pokemon)}"
                else:
                    response += f"\nInvalid: {', '.join(not_found_pokemon[:5])} and {len(not_found_pokemon) - 5} more..."

            return response
        else:
            return "No Pokemon were removed (they might not be in your collection)"

    except Exception as e:
        print(f"Database error in remove_pokemon_from_collection: {e}")
        return f"Database error: {str(e)[:100]}"

async def clear_user_collection(user_id, guild_id):
    """Clear user's entire collection for the guild"""
    if db is None:
        return "Database not available"

    try:
        result = await db.collections.delete_one({"user_id": user_id, "guild_id": guild_id})

        if result.deleted_count > 0:
            return "Collection cleared successfully"
        else:
            return "Your collection is already empty"

    except Exception as e:
        print(f"Database error in clear_user_collection: {e}")
        return f"Database error: {str(e)[:100]}"

async def list_user_collection(user_id, guild_id, page=1):
    """List user's Pokemon collection for the guild with pagination"""
    if db is None:
        return "Database not available"

    try:
        collection = await db.collections.find_one({"user_id": user_id, "guild_id": guild_id})

        if not collection or not collection.get('pokemon'):
            return "Your collection is empty"

        pokemon_list = sorted(collection['pokemon'])
        items_per_page = 150  # Increased from 15 to 150 Pokemon per page
        total_pages = math.ceil(len(pokemon_list) / items_per_page)

        # Ensure page is within bounds
        page = max(1, min(page, total_pages))

        start_index = (page - 1) * items_per_page
        end_index = start_index + items_per_page
        page_pokemon = pokemon_list[start_index:end_index]

        response = f"**__Your collection ({len(pokemon_list)} Pokemon) - Page {page}/{total_pages}:\n__**"
        response += ", ".join(page_pokemon)

        return response, page, total_pages

    except Exception as e:
        print(f"Database error in list_user_collection: {e}")
        return f"Database error: {str(e)[:100]}"

async def process_message_commands(message):
    """Process all bot commands - used for both new messages and edits"""
    # Don't respond to the bot's own messages
    if message.author == bot.user:
        return

    # Check if predictor is available
    if predictor is None:
        print("Predictor not initialized, attempting to initialize...")
        await initialize_predictor()
        if predictor is None:
            return

    # Help command
    if message.content.lower() == "m!help":
        embed = discord.Embed(
            title="🤖 Pokemon Helper Bot Commands",
            description="Here are all the available commands organized by category:",
            color=0x3498db
        )

        embed.add_field(
            name="🔧 Basic Commands",
            value=(
                "`m!ping` - Check bot latency and response time\n"
                "`m!help` - Show this help message"
            ),
            inline=False
        )

        embed.add_field(
            name="🔍 Prediction Commands", 
            value=(
                "`m!predict <image_url>` - Predict Pokemon from image URL\n"
                "`m!predict` (reply to image) - Predict Pokemon from replied image\n"
                "🤖 Auto-detection works on Poketwo spawns!"
            ),
            inline=False
        )

        embed.add_field(
            name="📚 Collection Management",
            value=(
                "`m!cl add <pokemon1, pokemon2, ...>` - Add Pokemon to your collection\n"
                "`m!cl remove <pokemon1, pokemon2, ...>` - Remove Pokemon from collection\n"
                "`m!cl list` - View your collection (with pagination)\n"
                "`m!cl clear` - Clear your entire collection"
            ),
            inline=False
        )

        embed.add_field(
            name="😴 AFK System",
            value=(
                "`m!afk` - Toggle your AFK status (with interactive button)\n"
                "AFK users won't be pinged when their Pokemon spawn"
            ),
            inline=False
        )

        embed.add_field(
            name="👑 Admin Commands",
            value=(
                "`m!rare-role @role` - Set role to ping for rare Pokemon\n"
                "`m!regional-role @role` - Set role to ping for regional Pokemon\n"
                "*Requires Administrator permission*"
            ),
            inline=False
        )

        embed.add_field(
            name="✨ Features",
            value=(
                "• Automatic Pokemon detection on Poketwo spawns\n"
                "• Collector pinging (mentions users who have that Pokemon)\n"
                "• Rare/Regional Pokemon role pinging\n"
                "• Gender variant support\n"
                "• Multi-language Pokemon name support\n"
                "• Commands work with message edits!"
            ),
            inline=False
        )

        embed.set_footer(text="Bot created for Pokemon collection management | Use commands with 'm!' prefix")

        await message.channel.send(embed=embed)
        return

    # Ping command - show actual latency
    if message.content.lower() == "m!ping":
        start_time = time.time()

        # Send initial message
        sent_message = await message.channel.send("🏓 Pinging...")

        # Calculate latency
        end_time = time.time()
        message_latency = round((end_time - start_time) * 1000, 2)  # Convert to milliseconds
        websocket_latency = round(bot.latency * 1000, 2)  # Bot's websocket latency in ms

        # Edit message with actual ping info
        embed = discord.Embed(title="🏓 Pong!", color=0x00ff00)
        embed.add_field(name="Message Latency", value=f"{message_latency}ms", inline=True)
        embed.add_field(name="WebSocket Latency", value=f"{websocket_latency}ms", inline=True)

        # Add status indicator based on latency
        if websocket_latency < 100:
            embed.add_field(name="Status", value="🟢 Excellent", inline=True)
        elif websocket_latency < 200:
            embed.add_field(name="Status", value="🟡 Good", inline=True)
        elif websocket_latency < 500:
            embed.add_field(name="Status", value="🟠 Fair", inline=True)
        else:
            embed.add_field(name="Status", value="🔴 Poor", inline=True)

        await sent_message.edit(content="", embed=embed)
        return

    # AFK command with toggle button
    if message.content.lower() == "m!afk":
        current_afk = await is_user_afk(message.author.id, message.guild.id)

        if current_afk:
            initial_message = "You are currently AFK and won't be pinged for Pokemon spawns."
        else:
            initial_message = "You are currently active and will be pinged for Pokemon spawns."

        view = AFKView(message.author.id, message.guild.id, current_afk)
        await message.reply(initial_message, view=view)
        return

    # Role management commands
    if message.content.lower().startswith("m!rare-role"):
        # Check if user has administrator permissions
        if not message.author.guild_permissions.administrator:
            await message.reply("You need administrator permissions to use this command.")
            return

        # Extract role mention or ID
        content_parts = message.content.split()
        if len(content_parts) < 2:
            await message.reply("Usage: m!rare-role @role or m!rare-role <role_id>")
            return

        role_mention = content_parts[1]
        role_id = None

        # Try to extract role ID from mention or direct ID
        if role_mention.startswith("<@&") and role_mention.endswith(">"):
            role_id = int(role_mention[3:-1])
        else:
            try:
                role_id = int(role_mention)
            except ValueError:
                await message.reply("Invalid role mention or ID. Use @role or role ID.")
                return

        # Verify role exists in guild
        role = message.guild.get_role(role_id)
        if not role:
            await message.reply("Role not found in this server.")
            return

        result = await set_rare_role(message.guild.id, role_id)
        await message.reply(result)
        return

    if message.content.lower().startswith("m!regional-role"):
        # Check if user has administrator permissions
        if not message.author.guild_permissions.administrator:
            await message.reply("You need administrator permissions to use this command.")
            return

        # Extract role mention or ID
        content_parts = message.content.split()
        if len(content_parts) < 2:
            await message.reply("Usage: m!regional-role @role or m!regional-role <role_id>")
            return

        role_mention = content_parts[1]
        role_id = None

        # Try to extract role ID from mention or direct ID
        if role_mention.startswith("<@&") and role_mention.endswith(">"):
            role_id = int(role_mention[3:-1])
        else:
            try:
                role_id = int(role_mention)
            except ValueError:
                await message.reply("Invalid role mention or ID. Use @role or role ID.")
                return

        # Verify role exists in guild
        role = message.guild.get_role(role_id)
        if not role:
            await message.reply("Role not found in this server.")
            return

        result = await set_regional_role(message.guild.id, role_id)
        await message.reply(result)
        return

    # Collection commands
    if message.content.lower().startswith("m!cl "):
        command_parts = message.content[5:].strip().split()

        if not command_parts:
            await message.reply("Usage: m!cl [add/remove/clear/list] [pokemon names]")
            return

        subcommand = command_parts[0].lower()

        if subcommand == "add":
            if len(command_parts) < 2:
                await message.reply("Usage: m!cl add <pokemon names separated by commas>")
                return

            pokemon_names_str = " ".join(command_parts[1:])
            pokemon_names = [name.strip() for name in pokemon_names_str.split(",") if name.strip()]

            if not pokemon_names:
                await message.reply("No valid Pokemon names provided")
                return

            result = await add_pokemon_to_collection(message.author.id, message.guild.id, pokemon_names)
            await message.reply(result)

        elif subcommand == "remove":
            if len(command_parts) < 2:
                await message.reply("Usage: m!cl remove <pokemon names separated by commas>")
                return

            pokemon_names_str = " ".join(command_parts[1:])
            pokemon_names = [name.strip() for name in pokemon_names_str.split(",") if name.strip()]

            if not pokemon_names:
                await message.reply("No valid Pokemon names provided")
                return

            result = await remove_pokemon_from_collection(message.author.id, message.guild.id, pokemon_names)
            await message.reply(result)

        elif subcommand == "clear":
            result = await clear_user_collection(message.author.id, message.guild.id)
            await message.reply(result)

        elif subcommand == "list":
            result = await list_user_collection(message.author.id, message.guild.id, 1)

            if isinstance(result, tuple):
                content, page, total_pages = result

                if total_pages > 1:
                    view = CollectionPaginationView(message.author.id, message.guild.id, page, total_pages)
                    await message.reply(content, view=view)
                else:
                    await message.reply(content)
            else:
                await message.reply(result)

        else:
            await message.reply("Available commands: m!cl add, m!cl remove, m!cl clear, m!cl list")

        return

    # Manual predict command
    if message.content.startswith("m!predict"):
        image_url = None

        # Check if there's a URL in the command
        url_parts = message.content.split(" ", 1)
        if len(url_parts) > 1 and url_parts[1].strip():
            image_url = url_parts[1].strip()

        # If no URL provided, check if replying to a message with image
        elif message.reference:
            try:
                replied_message = await message.channel.fetch_message(message.reference.message_id)
                image_url = await get_image_url_from_message(replied_message)
            except discord.NotFound:
                await message.reply("Could not find the replied message.")
                return
            except discord.Forbidden:
                await message.reply("I don't have permission to access that message.")
                return
            except Exception as e:
                await message.reply(f"Error fetching replied message: {str(e)[:100]}")
                return

        # If still no image URL found
        if not image_url:
            await message.reply("Please provide an image URL after m!predict or reply to a message with an image.")
            return

        try:
            name, confidence = predictor.predict(image_url)
            if name and confidence:
                formatted_output = format_pokemon_prediction(name, confidence)

                # Get collectors for this Pokemon
                collectors = await get_collectors_for_pokemon(name, message.guild.id)

                if collectors:
                    collector_mentions = " ".join([f"<@{user_id}>" for user_id in collectors])
                    formatted_output += f"\nCollectors: {collector_mentions}"

                # Get ping info for rare/regional Pokemon
                ping_info = await get_pokemon_ping_info(name, message.guild.id)
                if ping_info:
                    formatted_output += f"\n{ping_info}"

                await message.reply(formatted_output)
            else:
                await message.reply("Could not predict Pokemon from the provided image.")
        except Exception as e:
            print(f"Prediction error: {e}")
            await message.reply(f"Error: {str(e)[:100]}")
        return

    # Auto-detect Poketwo spawns (only for new messages, not edits)
    if message.author.id == 716390085896962058:  # Poketwo user ID
        # Check if message has embeds with the specific titles
        if message.embeds:
            embed = message.embeds[0]
            if embed.title:
                # Check for spawn embed titles
                if (embed.title == "A wild pokémon has appeared!" or 
                    (embed.title.endswith("A new wild pokémon has appeared!") and 
                     "fled." in embed.title)):

                    image_url = await get_image_url_from_message(message)

                    if image_url:
                        try:
                            name, confidence = predictor.predict(image_url)

                            if name and confidence:
                                # Add confidence threshold to avoid low-confidence predictions
                                confidence_str = str(confidence).rstrip('%')
                                try:
                                    confidence_value = float(confidence_str)
                                    if confidence_value >= 70.0:  # Only show if confidence >= 70%
                                        formatted_output = format_pokemon_prediction(name, confidence)

                                        # Get collectors for this Pokemon
                                        collectors = await get_collectors_for_pokemon(name, message.guild.id)

                                        if collectors:
                                            collector_mentions = " ".join([f"<@{user_id}>" for user_id in collectors])
                                            formatted_output += f"\nCollectors: {collector_mentions}"

                                        # Get ping info for rare/regional Pokemon
                                        ping_info = await get_pokemon_ping_info(name, message.guild.id)
                                        if ping_info:
                                            formatted_output += f"\n{ping_info}"

                                        await message.reply(formatted_output)
                                    else:
                                        print(f"Low confidence prediction skipped: {name} ({confidence})")
                                except ValueError:
                                    print(f"Could not parse confidence value: {confidence}")
                        except Exception as e:
                            print(f"Auto-detection error: {e}")

class AFKView(discord.ui.View):
    def __init__(self, user_id, guild_id, is_afk):
        super().__init__(timeout=300)  # 5 minutes timeout
        self.user_id = user_id
        self.guild_id = guild_id
        self.update_button(is_afk)

    def update_button(self, is_afk):
        # Clear existing buttons
        self.clear_items()

        if is_afk:
            button = discord.ui.Button(
                label="Collection",
                style=discord.ButtonStyle.danger,
                emoji="📦"
            )
        else:
            button = discord.ui.Button(
                label="Collection",
                style=discord.ButtonStyle.success,
                emoji="📦"
            )

        button.callback = self.toggle_afk
        self.add_item(button)

    async def toggle_afk(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button is not for you!", ephemeral=True)
            return

        message, is_afk = await toggle_user_afk(self.user_id, self.guild_id)
        self.update_button(is_afk)

        await interaction.response.edit_message(content=message, view=self)

class CollectionPaginationView(discord.ui.View):
    def __init__(self, user_id, guild_id, current_page, total_pages):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.guild_id = guild_id
        self.current_page = current_page
        self.total_pages = total_pages

        # Update button states
        self.previous_button.disabled = (current_page <= 1)
        self.next_button.disabled = (current_page >= total_pages)

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.primary)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button is not for you!", ephemeral=True)
            return

        new_page = max(1, self.current_page - 1)
        result = await list_user_collection(self.user_id, self.guild_id, new_page)

        if isinstance(result, tuple):
            content, page, total_pages = result
            self.current_page = page
            self.total_pages = total_pages

            # Update button states
            self.previous_button.disabled = (page <= 1)
            self.next_button.disabled = (page >= total_pages)

            await interaction.response.edit_message(content=content, view=self)
        else:
            await interaction.response.edit_message(content=result, view=None)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button is not for you!", ephemeral=True)
            return

        new_page = min(self.total_pages, self.current_page + 1)
        result = await list_user_collection(self.user_id, self.guild_id, new_page)

        if isinstance(result, tuple):
            content, page, total_pages = result
            self.current_page = page
            self.total_pages = total_pages

            # Update button states
            self.previous_button.disabled = (page <= 1)
            self.next_button.disabled = (page >= total_pages)

            await interaction.response.edit_message(content=content, view=self)
        else:
            await interaction.response.edit_message(content=result, view=None)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    if predictor is None:
        await initialize_predictor()
    if db is None:
        await initialize_database()

@bot.event
async def on_message(message):
    await process_message_commands(message)

@bot.event
async def on_message_edit(before, after):
    """Handle message edits - process commands on edited messages too"""
    # Only process if the message content actually changed
    if before.content != after.content:
        print(f"Message edited by {after.author}: '{before.content}' -> '{after.content}'")
        await process_message_commands(after)

async def get_image_url_from_message(message):
    """Extract image URL from message attachments or embeds"""
    image_url = None

    # Check attachments first
    if message.attachments:
        for attachment in message.attachments:
            if any(attachment.url.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".webp", ".gif"]):
                image_url = attachment.url
                break

    # Check embeds if no attachment found
    if not image_url and message.embeds:
        embed = message.embeds[0]
        if embed.image and embed.image.url:
            image_url = embed.image.url
        elif embed.thumbnail and embed.thumbnail.url:
            image_url = embed.thumbnail.url

    return image_url

def main():
    if not TOKEN:
        print("Error: DISCORD_TOKEN environment variable not set")
        return

    try:
        bot.run(TOKEN)
    except discord.LoginFailure:
        print("Error: Invalid Discord token")
    except Exception as e:
        print(f"Error starting bot: {e}")

if __name__ == "__main__":
    main()
