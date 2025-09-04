import discord
import json
import math
from discord.ext import commands

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
    from main import db
    
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

async def get_afk_users(guild_id):
    """Get list of AFK user IDs for a guild"""
    from main import db
    
    if db is None:
        return []

    try:
        afk_docs = await db.afk_users.find({"guild_id": guild_id, "afk": True}).to_list(length=None)
        return [doc['user_id'] for doc in afk_docs]
    except Exception as e:
        print(f"Error getting AFK users: {e}")
        return []

async def toggle_user_afk(user_id, guild_id):
    """Toggle user's AFK status for a guild"""
    from main import db
    
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

async def is_user_afk(user_id, guild_id):
    """Check if a user is AFK"""
    from main import db
    
    if db is None:
        return False

    try:
        afk_doc = await db.afk_users.find_one({"user_id": user_id, "guild_id": guild_id})
        return afk_doc and afk_doc.get('afk', False)
    except Exception as e:
        print(f"Error checking AFK status: {e}")
        return False

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
                label="Set Active",
                style=discord.ButtonStyle.danger,
                emoji="✅"
            )
        else:
            button = discord.ui.Button(
                label="Set AFK",
                style=discord.ButtonStyle.success,
                emoji="😴"
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

async def add_pokemon_to_collection(user_id, guild_id, pokemon_names):
    """Add Pokemon to user's collection"""
    from main import db
    
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
        if len(added_pokemon) <= 150:
            response = f"Added {len(added_pokemon)} Pokemon: {', '.join(added_pokemon)}"
        else:
            response = f"Added {len(added_pokemon)} Pokemon: {', '.join(added_pokemon[:150])} and {len(added_pokemon) - 150} more..."

        if invalid_pokemon:
            if len(invalid_pokemon) <= 30:
                response += f"\nInvalid: {', '.join(invalid_pokemon)}"
            else:
                response += f"\nInvalid: {', '.join(invalid_pokemon[:30])} and {len(invalid_pokemon) - 30} more..."

        return response

    except Exception as e:
        print(f"Database error in add_pokemon_to_collection: {e}")
        return f"Database error: {str(e)[:100]}"

async def remove_pokemon_from_collection(user_id, guild_id, pokemon_names):
    """Remove Pokemon from user's collection"""
    from main import db
    
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
            error_msg += f". Invalid names: {', '.join(not_found_pokemon[:30])}"
            if len(not_found_pokemon) > 30:
                error_msg += f" and {len(not_found_pokemon) - 30} more..."
        return error_msg

    try:
        result = await db.collections.update_one(
            {"user_id": user_id, "guild_id": guild_id},
            {"$pullAll": {"pokemon": removed_pokemon}}
        )

        if result.modified_count > 0:
            # Create response with character limits in mind
            if len(removed_pokemon) <= 150:
                response = f"Removed {len(removed_pokemon)} Pokemon: {', '.join(removed_pokemon)}"
            else:
                response = f"Removed {len(removed_pokemon)} Pokemon: {', '.join(removed_pokemon[:150])} and {len(removed_pokemon) - 150} more..."

            if not_found_pokemon:
                if len(not_found_pokemon) <= 30:
                    response += f"\nInvalid: {', '.join(not_found_pokemon)}"
                else:
                    response += f"\nInvalid: {', '.join(not_found_pokemon[:30])} and {len(not_found_pokemon) - 30} more..."

            return response
        else:
            return "No Pokemon were removed (they might not be in your collection)"

    except Exception as e:
        print(f"Database error in remove_pokemon_from_collection: {e}")
        return f"Database error: {str(e)[:100]}"

async def clear_user_collection(user_id, guild_id):
    """Clear user's entire collection for the guild"""
    from main import db
    
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
    from main import db
    
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

class Collections(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.group(name='cl', invoke_without_command=True)
    async def collection(self, ctx):
        """Collection management commands"""
        await ctx.send("Available commands: `m!cl add`, `m!cl remove`, `m!cl clear`, `m!cl list`")

    @collection.command(name='add')
    async def add_pokemon(self, ctx, *, pokemon_names):
        """Add Pokemon to your collection"""
        if not pokemon_names:
            await ctx.send("Usage: `m!cl add <pokemon names separated by commas>`")
            return

        pokemon_list = [name.strip() for name in pokemon_names.split(",") if name.strip()]

        if not pokemon_list:
            await ctx.send("No valid Pokemon names provided")
            return

        result = await add_pokemon_to_collection(ctx.author.id, ctx.guild.id, pokemon_list)
        await ctx.send(result)

    @collection.command(name='remove')
    async def remove_pokemon(self, ctx, *, pokemon_names):
        """Remove Pokemon from your collection"""
        if not pokemon_names:
            await ctx.send("Usage: `m!cl remove <pokemon names separated by commas>`")
            return

        pokemon_list = [name.strip() for name in pokemon_names.split(",") if name.strip()]

        if not pokemon_list:
            await ctx.send("No valid Pokemon names provided")
            return

        result = await remove_pokemon_from_collection(ctx.author.id, ctx.guild.id, pokemon_list)
        await ctx.send(result)

    @collection.command(name='clear')
    async def clear_collection(self, ctx):
        """Clear your entire collection"""
        result = await clear_user_collection(ctx.author.id, ctx.guild.id)
        await ctx.send(result)

    @collection.command(name='list')
    async def list_collection(self, ctx):
        """List your Pokemon collection"""
        result = await list_user_collection(ctx.author.id, ctx.guild.id, 1)

        if isinstance(result, tuple):
            content, page, total_pages = result

            if total_pages > 1:
                view = CollectionPaginationView(ctx.author.id, ctx.guild.id, page, total_pages)
                await ctx.send(content, view=view)
            else:
                await ctx.send(content)
        else:
            await ctx.send(result)

    @commands.command(name='afk')
    async def toggle_afk(self, ctx):
        """Toggle your AFK status"""
        current_afk = await is_user_afk(ctx.author.id, ctx.guild.id)

        if current_afk:
            initial_message = "You are currently AFK and won't be pinged for Pokemon spawns."
        else:
            initial_message = "You are currently active and will be pinged for Pokemon spawns."

        view = AFKView(ctx.author.id, ctx.guild.id, current_afk)
        await ctx.send(initial_message, view=view)

async def setup(bot):
    await bot.add_cog(Collections(bot))
