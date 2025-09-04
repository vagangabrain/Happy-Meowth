import os
import discord
import asyncio
import json
import re
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
        
        db_client = AsyncIOMotorClient(MONGODB_URI)
        db = db_client.pokemon_collector
        print("Database initialized successfully")
    except Exception as e:
        print(f"Failed to initialize database: {e}")

def load_pokemon_data():
    """Load Pokemon data from pokemondata.json"""
    try:
        with open('pokemondata.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Failed to load pokemondata.json: {e}")
        return []

def find_pokemon_by_name(name, pokemon_data):
    """Find Pokemon by name (including other language names)"""
    name_lower = name.lower().strip()
    
    for pokemon in pokemon_data:
        # Check main name
        if pokemon['name'].lower() == name_lower:
            return pokemon
        
        # Check other language names
        for lang_name in pokemon['other_names'].values():
            if lang_name.lower() == name_lower:
                return pokemon
    
    return None

def get_pokemon_variants(base_pokemon_name, pokemon_data):
    """Get all variants of a Pokemon (including the base form)"""
    variants = []
    base_pokemon_name_lower = base_pokemon_name.lower()
    
    for pokemon in pokemon_data:
        # Add the base Pokemon itself
        if pokemon['name'].lower() == base_pokemon_name_lower:
            variants.append(pokemon['name'])
        # Add variants that belong to this base Pokemon
        elif pokemon.get('is_variant') and pokemon.get('variant_of', '').lower() == base_pokemon_name_lower:
            variants.append(pokemon['name'])
    
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
    """Get all users who have collected this Pokemon in the given guild"""
    if not db:
        return []
    
    pokemon_data = load_pokemon_data()
    collectors = []
    
    try:
        # Find all collections in this guild
        collections = await db.collections.find({"guild_id": guild_id}).to_list(length=None)
        
        for collection in collections:
            user_pokemon = collection.get('pokemon', [])
            
            # Check if user has this specific Pokemon
            if pokemon_name in user_pokemon:
                collectors.append(collection['user_id'])
                continue
            
            # Check if user has the base form and this is a variant
            target_pokemon = find_pokemon_by_name(pokemon_name, pokemon_data)
            if target_pokemon and target_pokemon.get('is_variant'):
                base_form = target_pokemon.get('variant_of')
                if base_form and base_form in user_pokemon:
                    collectors.append(collection['user_id'])
    
    except Exception as e:
        print(f"Error getting collectors: {e}")
    
    return collectors

async def add_pokemon_to_collection(user_id, guild_id, pokemon_names):
    """Add Pokemon to user's collection"""
    if not db:
        return "Database not available"
    
    pokemon_data = load_pokemon_data()
    added_pokemon = []
    invalid_pokemon = []
    
    for name in pokemon_names:
        name = name.strip()
        pokemon = find_pokemon_by_name(name, pokemon_data)
        
        if pokemon:
            # If it's a base form, add the main name
            # If it's a variant, add the variant name
            added_pokemon.append(pokemon['name'])
        else:
            invalid_pokemon.append(name)
    
    if not added_pokemon:
        return f"Invalid Pokemon names: {', '.join(invalid_pokemon)}"
    
    try:
        # Update or create collection
        await db.collections.update_one(
            {"user_id": user_id, "guild_id": guild_id},
            {"$addToSet": {"pokemon": {"$each": added_pokemon}}},
            upsert=True
        )
        
        result = f"Added to collection: {', '.join(added_pokemon)}"
        if invalid_pokemon:
            result += f"\nInvalid names: {', '.join(invalid_pokemon)}"
        
        return result
    
    except Exception as e:
        return f"Database error: {e}"

async def remove_pokemon_from_collection(user_id, guild_id, pokemon_names):
    """Remove Pokemon from user's collection"""
    if not db:
        return "Database not available"
    
    pokemon_data = load_pokemon_data()
    removed_pokemon = []
    not_found_pokemon = []
    
    for name in pokemon_names:
        name = name.strip()
        pokemon = find_pokemon_by_name(name, pokemon_data)
        
        if pokemon:
            removed_pokemon.append(pokemon['name'])
        else:
            not_found_pokemon.append(name)
    
    if not removed_pokemon:
        return f"Invalid Pokemon names: {', '.join(not_found_pokemon)}"
    
    try:
        result = await db.collections.update_one(
            {"user_id": user_id, "guild_id": guild_id},
            {"$pullAll": {"pokemon": removed_pokemon}}
        )
        
        if result.modified_count > 0:
            response = f"Removed from collection: {', '.join(removed_pokemon)}"
            if not_found_pokemon:
                response += f"\nInvalid names: {', '.join(not_found_pokemon)}"
            return response
        else:
            return "No Pokemon were removed (they might not be in your collection)"
    
    except Exception as e:
        return f"Database error: {e}"

async def clear_user_collection(user_id, guild_id):
    """Clear user's entire collection for the guild"""
    if not db:
        return "Database not available"
    
    try:
        result = await db.collections.delete_one({"user_id": user_id, "guild_id": guild_id})
        
        if result.deleted_count > 0:
            return "Collection cleared successfully"
        else:
            return "Your collection is already empty"
    
    except Exception as e:
        return f"Database error: {e}"

async def list_user_collection(user_id, guild_id):
    """List user's Pokemon collection for the guild"""
    if not db:
        return "Database not available"
    
    try:
        collection = await db.collections.find_one({"user_id": user_id, "guild_id": guild_id})
        
        if not collection or not collection.get('pokemon'):
            return "Your collection is empty"
        
        pokemon_list = sorted(collection['pokemon'])
        
        # Split into chunks if too long
        if len(pokemon_list) <= 20:
            return f"Your collection ({len(pokemon_list)} Pokemon):\n{', '.join(pokemon_list)}"
        else:
            chunks = [pokemon_list[i:i+20] for i in range(0, len(pokemon_list), 20)]
            response = f"Your collection ({len(pokemon_list)} Pokemon):\n"
            for i, chunk in enumerate(chunks, 1):
                response += f"Page {i}: {', '.join(chunk)}\n"
            return response
    
    except Exception as e:
        return f"Database error: {e}"

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    if predictor is None:
        await initialize_predictor()
    if db_client is None:
        await initialize_database()

@bot.event
async def on_message(message):
    # Don't respond to the bot's own messages
    if message.author == bot.user:
        return

    # Check if predictor is available
    if predictor is None:
        print("Predictor not initialized, attempting to initialize...")
        await initialize_predictor()
        if predictor is None:
            return

    # 1) Test command
    if message.content.lower() == "m!ping":
        await message.channel.send("Pong!")
        return

    # 2) Collection commands
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
            
            pokemon_names = " ".join(command_parts[1:]).split(",")
            result = await add_pokemon_to_collection(message.author.id, message.guild.id, pokemon_names)
            await message.reply(result)
        
        elif subcommand == "remove":
            if len(command_parts) < 2:
                await message.reply("Usage: m!cl remove <pokemon names separated by commas>")
                return
            
            pokemon_names = " ".join(command_parts[1:]).split(",")
            result = await remove_pokemon_from_collection(message.author.id, message.guild.id, pokemon_names)
            await message.reply(result)
        
        elif subcommand == "clear":
            result = await clear_user_collection(message.author.id, message.guild.id)
            await message.reply(result)
        
        elif subcommand == "list":
            result = await list_user_collection(message.author.id, message.guild.id)
            await message.reply(result)
        
        else:
            await message.reply("Available commands: m!cl add, m!cl remove, m!cl clear, m!cl list")
        
        return

    # 3) Manual predict command
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
        
        # If still no image URL found
        if not image_url:
            await message.reply("Please provide an image URL after m!predict or reply to a message with an image.")
            return
        
        try:
            name, confidence = predictor.predict(image_url)
            formatted_output = format_pokemon_prediction(name, confidence)
            
            # Get collectors for this Pokemon
            collectors = await get_collectors_for_pokemon(name, message.guild.id)
            
            if collectors:
                collector_mentions = " ".join([f"<@{user_id}>" for user_id in collectors])
                formatted_output += f"\nCollectors: {collector_mentions}"
            
            await message.reply(formatted_output)
        except Exception as e:
            await message.reply(f"Error: {e}")
        return

    # 4) Auto-detect Poketwo spawns
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
                            
                            # Add confidence threshold to avoid low-confidence predictions
                            confidence_value = float(confidence.rstrip('%'))
                            if confidence_value >= 70.0:  # Only show if confidence >= 70%
                                formatted_output = format_pokemon_prediction(name, confidence)
                                
                                # Get collectors for this Pokemon
                                collectors = await get_collectors_for_pokemon(name, message.guild.id)
                                
                                if collectors:
                                    collector_mentions = " ".join([f"<@{user_id}>" for user_id in collectors])
                                    formatted_output += f"\nCollectors: {collector_mentions}"
                                
                                await message.reply(formatted_output)
                            else:
                                print(f"Low confidence prediction skipped: {name} ({confidence})")
                        except Exception as e:
                            print(f"Auto-detection error: {e}")

async def get_image_url_from_message(message):
    """Extract image URL from message attachments or embeds"""
    image_url = None
    
    # Check attachments first
    if message.attachments:
        for attachment in message.attachments:
            if attachment.url.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
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
