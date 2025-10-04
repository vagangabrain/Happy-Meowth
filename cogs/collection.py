import discord
import math
import time
import asyncio
from discord.ext import commands
from utils import (
    load_pokemon_data, 
    find_pokemon_by_name, 
    find_pokemon_by_name_flexible,
    normalize_pokemon_name,
    is_rare_pokemon
)

class CollectionPaginationView(discord.ui.View):
    def __init__(self, user_id, guild_id, current_page, total_pages, cog):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.guild_id = guild_id
        self.current_page = current_page
        self.total_pages = total_pages
        self.cog = cog

        # Update button states
        self.previous_button.disabled = (current_page <= 1)
        self.next_button.disabled = (current_page >= total_pages)

    @discord.ui.button(label="", emoji="◀️", style=discord.ButtonStyle.primary)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button is not for you!", ephemeral=True)
            return

        new_page = max(1, self.current_page - 1)
        embed = await self.cog.create_collection_embed(self.user_id, self.guild_id, new_page)

        if embed:
            self.current_page = new_page
            # Update button states
            self.previous_button.disabled = (new_page <= 1)
            self.next_button.disabled = (new_page >= self.total_pages)
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.edit_message(content="Error loading collection.", embed=None, view=None)

    @discord.ui.button(label="", emoji="▶️", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button is not for you!", ephemeral=True)
            return

        new_page = min(self.total_pages, self.current_page + 1)
        embed = await self.cog.create_collection_embed(self.user_id, self.guild_id, new_page)

        if embed:
            self.current_page = new_page
            # Update button states
            self.previous_button.disabled = (new_page <= 1)
            self.next_button.disabled = (new_page >= self.total_pages)
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.edit_message(content="Error loading collection.", embed=None, view=None)

class Collection(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Performance caching
        self._collectors_cache = {}
        self._hunters_cache = {}
        self._afk_users_cache = {}
        self._cache_ttl = 60  # 1 minute cache
        self._cache_timestamps = {}

    @property
    def db(self):
        """Get database from main module"""
        import __main__
        return getattr(__main__, 'db', None)

    def _is_cache_valid(self, cache_key):
        """Check if cache entry is still valid"""
        if cache_key not in self._cache_timestamps:
            return False
        return time.time() - self._cache_timestamps[cache_key] < self._cache_ttl

    def _set_cache(self, cache_dict, cache_key, value):
        """Set cache value with timestamp"""
        cache_dict[cache_key] = value
        self._cache_timestamps[cache_key] = time.time()

    def _invalidate_guild_caches(self, guild_id):
        """Invalidate all caches for a guild"""
        cache_keys_to_remove = []

        # Find all cache keys for this guild
        for cache_dict in [self._collectors_cache, self._hunters_cache, self._afk_users_cache]:
            for key in list(cache_dict.keys()):
                if f"_{guild_id}_" in key or f"_{guild_id}" == key[-len(str(guild_id))-1:]:
                    cache_keys_to_remove.append(key)
                    cache_dict.pop(key, None)

        # Remove timestamps
        for key in cache_keys_to_remove:
            self._cache_timestamps.pop(key, None)

    async def get_collection_afk_users(self, guild_id):
        """Get list of collection AFK user IDs for a guild with caching"""
        cache_key = f"collection_afk_{guild_id}"

        if self._is_cache_valid(cache_key) and cache_key in self._afk_users_cache:
            return self._afk_users_cache[cache_key]

        if self.db is None:
            return []

        try:
            afk_docs = await self.db.collection_afk_users.find(
                {"guild_id": guild_id, "afk": True},
                {"user_id": 1}  # Only fetch user_id field
            ).to_list(length=None)

            result = [doc['user_id'] for doc in afk_docs]
            self._set_cache(self._afk_users_cache, cache_key, result)
            return result
        except Exception as e:
            print(f"Error getting collection AFK users: {e}")
            return []

    async def get_shiny_hunt_afk_users(self, guild_id):
        """Get list of shiny hunt AFK user IDs for a guild with caching"""
        cache_key = f"shiny_afk_{guild_id}"

        if self._is_cache_valid(cache_key) and cache_key in self._afk_users_cache:
            return self._afk_users_cache[cache_key]

        if self.db is None:
            return []

        try:
            afk_docs = await self.db.shiny_hunt_afk_users.find(
                {"guild_id": guild_id, "afk": True},
                {"user_id": 1}  # Only fetch user_id field
            ).to_list(length=None)

            result = [doc['user_id'] for doc in afk_docs]
            self._set_cache(self._afk_users_cache, cache_key, result)
            return result
        except Exception as e:
            print(f"Error getting shiny hunt AFK users: {e}")
            return []

    async def get_collectors_for_pokemon(self, pokemon_name, guild_id):
        """Get all users who have collected this Pokemon in the given guild (optimized with caching)"""
        cache_key = f"collectors_{guild_id}_{normalize_pokemon_name(pokemon_name).lower()}"

        if self._is_cache_valid(cache_key) and cache_key in self._collectors_cache:
            return self._collectors_cache[cache_key]

        if self.db is None:
            return []

        pokemon_data = load_pokemon_data()
        collectors = []
        normalized_spawn_name = normalize_pokemon_name(pokemon_name).lower()

        try:
            # Run queries in parallel for better performance
            afk_users_task = self.get_collection_afk_users(guild_id)
            collections_task = self.db.collections.find(
                {"guild_id": guild_id, "pokemon": {"$exists": True, "$ne": []}},
                {"user_id": 1, "pokemon": 1}
            ).to_list(length=None)

            collection_afk_users, collections = await asyncio.gather(
                afk_users_task, collections_task
            )

            afk_users_set = set(collection_afk_users)  # O(1) lookup

            for collection in collections:
                user_id = collection['user_id']

                if user_id in afk_users_set:
                    continue

                user_pokemon = collection.get('pokemon', [])

                # Check direct match first (most common case)
                if any(normalize_pokemon_name(p).lower() == normalized_spawn_name 
                       for p in user_pokemon):
                    collectors.append(user_id)
                    continue

                # Check for variant matching
                target_pokemon = find_pokemon_by_name(pokemon_name, pokemon_data)
                if target_pokemon and target_pokemon.get('is_variant'):
                    base_form = target_pokemon.get('variant_of')
                    if base_form:
                        normalized_base_form = normalize_pokemon_name(base_form).lower()
                        if any(normalize_pokemon_name(p).lower() == normalized_base_form 
                               for p in user_pokemon):
                            if user_id not in collectors:  # Avoid duplicates
                                collectors.append(user_id)

            self._set_cache(self._collectors_cache, cache_key, collectors)

        except Exception as e:
            print(f"Error getting collectors: {e}")

        return collectors

    async def get_shiny_hunters_for_pokemon(self, pokemon_name, guild_id):
        """Get all users hunting this Pokemon in the given guild (optimized with caching)"""
        cache_key = f"hunters_{guild_id}_{normalize_pokemon_name(pokemon_name).lower()}"

        if self._is_cache_valid(cache_key) and cache_key in self._hunters_cache:
            return self._hunters_cache[cache_key]

        if self.db is None:
            return []

        pokemon_data = load_pokemon_data()
        hunters = []
        normalized_spawn_name = normalize_pokemon_name(pokemon_name).lower()

        try:
            # Run queries in parallel
            afk_users_task = self.get_shiny_hunt_afk_users(guild_id)
            hunts_task = self.db.shiny_hunts.find(
                {"guild_id": guild_id, "pokemon": {"$exists": True}},
                {"user_id": 1, "pokemon": 1}
            ).to_list(length=None)

            shiny_hunt_afk_users, shiny_hunts = await asyncio.gather(
                afk_users_task, hunts_task
            )

            afk_users_set = set(shiny_hunt_afk_users)

            for hunt in shiny_hunts:
                user_id = hunt['user_id']
                hunting_pokemon = hunt.get('pokemon')

                if hunting_pokemon:
                    normalized_hunting_name = normalize_pokemon_name(hunting_pokemon).lower()

                    if normalized_hunting_name == normalized_spawn_name:
                        if user_id in afk_users_set:
                            hunters.append(f"{user_id}(AFK)")
                        else:
                            hunters.append(f"<@{user_id}>")
                        continue

                    # Check for variant matching
                    target_pokemon = find_pokemon_by_name(pokemon_name, pokemon_data)
                    if target_pokemon and target_pokemon.get('is_variant'):
                        base_form = target_pokemon.get('variant_of')
                        if base_form:
                            normalized_base_form = normalize_pokemon_name(base_form).lower()
                            if normalized_hunting_name == normalized_base_form:
                                if user_id in afk_users_set:
                                    hunters.append(f"{user_id}(AFK)")
                                else:
                                    hunters.append(f"<@{user_id}>")

            self._set_cache(self._hunters_cache, cache_key, hunters)

        except Exception as e:
            print(f"Error getting shiny hunters: {e}")

        return hunters

    async def get_rare_collectors(self, guild_id):
        """Get all users who want rare pings (optimized)"""
        if self.db is None:
            return []

        try:
            # Run queries in parallel
            afk_users_task = self.get_collection_afk_users(guild_id)
            rare_users_task = self.db.rare_pings.find(
                {"guild_id": guild_id, "enabled": True},
                {"user_id": 1}
            ).to_list(length=None)

            collection_afk_users, rare_ping_users = await asyncio.gather(
                afk_users_task, rare_users_task
            )

            afk_users_set = set(collection_afk_users)
            collectors = []

            for rare_ping_doc in rare_ping_users:
                user_id = rare_ping_doc['user_id']
                if user_id not in afk_users_set:
                    collectors.append(user_id)

            return collectors

        except Exception as e:
            print(f"Error getting rare collectors: {e}")
            return []

    async def get_collectors_for_spawn(self, pokemon_name, guild_id):
        """Get all users to ping for a Pokemon spawn (optimized with parallel queries)"""
        # Run both queries in parallel
        regular_collectors_task = self.get_collectors_for_pokemon(pokemon_name, guild_id)

        # Check if this is a rare Pokemon
        pokemon_data = load_pokemon_data()
        pokemon = find_pokemon_by_name(pokemon_name, pokemon_data)

        if pokemon and is_rare_pokemon(pokemon):
            rare_collectors_task = self.get_rare_collectors(guild_id)
            regular_collectors, rare_collectors = await asyncio.gather(
                regular_collectors_task, rare_collectors_task
            )

            # Combine without duplicates
            all_collectors = list(set(regular_collectors + rare_collectors))
            return all_collectors
        else:
            return await regular_collectors_task

    async def toggle_user_collection_afk(self, user_id, guild_id):
        """Toggle user's collection AFK status for a guild"""
        if self.db is None:
            return "Database not available", False

        try:
            current_afk = await self.db.collection_afk_users.find_one(
                {"user_id": user_id, "guild_id": guild_id}
            )

            if current_afk and current_afk.get('afk', False):
                await self.db.collection_afk_users.delete_one(
                    {"user_id": user_id, "guild_id": guild_id}
                )
                self._invalidate_guild_caches(guild_id)
                return "Collection pings enabled. You will be pinged for Pokemon you have collected.", False
            else:
                await self.db.collection_afk_users.update_one(
                    {"user_id": user_id, "guild_id": guild_id},
                    {"$set": {"user_id": user_id, "guild_id": guild_id, "afk": True}},
                    upsert=True
                )
                self._invalidate_guild_caches(guild_id)
                return "Collection pings disabled. You won't be pinged for Pokemon you have collected.", True
        except Exception as e:
            print(f"Error toggling collection AFK status: {e}")
            return f"Database error: {str(e)[:100]}", False

    async def toggle_user_shiny_hunt_afk(self, user_id, guild_id):
        """Toggle user's shiny hunt AFK status for a guild"""
        if self.db is None:
            return "Database not available", False

        try:
            current_afk = await self.db.shiny_hunt_afk_users.find_one(
                {"user_id": user_id, "guild_id": guild_id}
            )

            if current_afk and current_afk.get('afk', False):
                await self.db.shiny_hunt_afk_users.delete_one(
                    {"user_id": user_id, "guild_id": guild_id}
                )
                self._invalidate_guild_caches(guild_id)
                return "Shiny hunt pings enabled. You will be pinged for Pokemon you're hunting.", False
            else:
                await self.db.shiny_hunt_afk_users.update_one(
                    {"user_id": user_id, "guild_id": guild_id},
                    {"$set": {"user_id": user_id, "guild_id": guild_id, "afk": True}},
                    upsert=True
                )
                self._invalidate_guild_caches(guild_id)
                return "Shiny hunt pings disabled. Your ID will be shown but you won't be pinged for Pokemon you're hunting.", True
        except Exception as e:
            print(f"Error toggling shiny hunt AFK status: {e}")
            return f"Database error: {str(e)[:100]}", False

    async def is_user_collection_afk(self, user_id, guild_id):
        """Check if a user is collection AFK"""
        if self.db is None:
            return False

        try:
            afk_doc = await self.db.collection_afk_users.find_one(
                {"user_id": user_id, "guild_id": guild_id}
            )
            return afk_doc and afk_doc.get('afk', False)
        except Exception as e:
            print(f"Error checking collection AFK status: {e}")
            return False

    async def is_user_shiny_hunt_afk(self, user_id, guild_id):
        """Check if a user is shiny hunt AFK"""
        if self.db is None:
            return False

        try:
            afk_doc = await self.db.shiny_hunt_afk_users.find_one(
                {"user_id": user_id, "guild_id": guild_id}
            )
            return afk_doc and afk_doc.get('afk', False)
        except Exception as e:
            print(f"Error checking shiny hunt AFK status: {e}")
            return False

    async def set_shiny_hunt(self, user_id, guild_id, pokemon_name):
        """Set user's shiny hunt Pokemon for a guild"""
        if self.db is None:
            return "Database not available"

        if not pokemon_name:
            return "No Pokemon name provided"

        pokemon_data = load_pokemon_data()
        if not pokemon_data:
            return "Pokemon data not available"

        pokemon = find_pokemon_by_name_flexible(pokemon_name, pokemon_data)

        if not pokemon or not pokemon.get('name'):
            return f"Invalid Pokemon name: {pokemon_name}"

        try:
            await self.db.shiny_hunts.update_one(
                {"user_id": user_id, "guild_id": guild_id},
                {"$set": {"user_id": user_id, "guild_id": guild_id, "pokemon": pokemon['name']}},
                upsert=True
            )

            self._invalidate_guild_caches(guild_id)
            return f"Now hunting: **{pokemon['name']}**"

        except Exception as e:
            print(f"Database error in set_shiny_hunt: {e}")
            return f"Database error: {str(e)[:100]}"

    async def clear_shiny_hunt(self, user_id, guild_id):
        """Clear user's shiny hunt for a guild"""
        if self.db is None:
            return "Database not available"

        try:
            result = await self.db.shiny_hunts.delete_one(
                {"user_id": user_id, "guild_id": guild_id}
            )

            if result.deleted_count > 0:
                self._invalidate_guild_caches(guild_id)
                return "Shiny hunt cleared successfully"
            else:
                return "You are not hunting anything"

        except Exception as e:
            print(f"Database error in clear_shiny_hunt: {e}")
            return f"Database error: {str(e)[:100]}"

    async def get_user_shiny_hunt(self, user_id, guild_id):
        """Get user's current shiny hunt Pokemon"""
        if self.db is None:
            return "Database not available"

        try:
            hunt = await self.db.shiny_hunts.find_one(
                {"user_id": user_id, "guild_id": guild_id}
            )

            if hunt and hunt.get('pokemon'):
                return f"You are currently hunting: **{hunt['pokemon']}**"
            else:
                return "You are not hunting anything"

        except Exception as e:
            print(f"Database error in get_user_shiny_hunt: {e}")
            return f"Database error: {str(e)[:100]}"

    async def add_pokemon_to_collection(self, user_id, guild_id, pokemon_names):
        """Add Pokemon to user's collection (optimized batch processing)"""
        if self.db is None:
            return "Database not available"

        if not pokemon_names:
            return "No Pokemon names provided"

        pokemon_data = load_pokemon_data()
        if not pokemon_data:
            return "Pokemon data not available"

        added_pokemon = []
        invalid_pokemon = []

        # Process names efficiently
        for name in pokemon_names:
            if not name or not isinstance(name, str):
                continue

            name = name.strip()
            if not name:
                continue

            pokemon = find_pokemon_by_name_flexible(name, pokemon_data)

            if pokemon and pokemon.get('name'):
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
            await self.db.collections.update_one(
                {"user_id": user_id, "guild_id": guild_id},
                {"$addToSet": {"pokemon": {"$each": added_pokemon}}},
                upsert=True
            )

            self._invalidate_guild_caches(guild_id)

            # Format response efficiently
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

    async def remove_pokemon_from_collection(self, user_id, guild_id, pokemon_names):
        """Remove Pokemon from user's collection (optimized)"""
        if self.db is None:
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

            pokemon = find_pokemon_by_name_flexible(name, pokemon_data)

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
            result = await self.db.collections.update_one(
                {"user_id": user_id, "guild_id": guild_id},
                {"$pullAll": {"pokemon": removed_pokemon}}
            )

            if result.modified_count > 0:
                self._invalidate_guild_caches(guild_id)

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

    async def clear_user_collection(self, user_id, guild_id):
        """Clear user's entire collection for the guild"""
        if self.db is None:
            return "Database not available"

        try:
            result = await self.db.collections.delete_one(
                {"user_id": user_id, "guild_id": guild_id}
            )

            if result.deleted_count > 0:
                self._invalidate_guild_caches(guild_id)
                return "Collection cleared successfully"
            else:
                return "Your collection is already empty"

        except Exception as e:
            print(f"Database error in clear_user_collection: {e}")
            return f"Database error: {str(e)[:100]}"

    async def create_collection_embed(self, user_id, guild_id, page=1):
        """Create an embed for user's Pokemon collection with pagination"""
        if self.db is None:
            return None

        try:
            collection = await self.db.collections.find_one(
                {"user_id": user_id, "guild_id": guild_id}
            )

            if not collection or not collection.get('pokemon'):
                embed = discord.Embed(
                    title="📦 Your Collection",
                    description="Your collection is empty! Start adding Pokémon with `m!cl add <pokemon>`",
                    color=0xf4e5ba
                )
                return embed

            pokemon_list = sorted(collection['pokemon'])
            items_per_page = 20
            total_pages = math.ceil(len(pokemon_list) / items_per_page)

            page = max(1, min(page, total_pages))

            start_index = (page - 1) * items_per_page
            end_index = start_index + items_per_page
            page_pokemon = pokemon_list[start_index:end_index]

            # Create embed with enhanced look - one Pokemon per line
            description = "\n".join([f"• {pokemon}" for pokemon in page_pokemon])

            embed = discord.Embed(
                title="📦 Your Collection for this Server",
                description=description,
                color=0xf4e5ba
            )

            embed.set_footer(text=f"Showing {start_index + 1}-{min(end_index, len(pokemon_list))} of {len(pokemon_list)} Pokémon that you are collecting! • Page {page}/{total_pages}")

            return embed

        except Exception as e:
            print(f"Database error in create_collection_embed: {e}")
            return None

    @commands.command(name="sh")
    async def shiny_hunt_command(self, ctx, *, args: str = None):
        """Manage shiny hunt - set, clear, or check current hunt"""
        if not args:
            result = await self.get_user_shiny_hunt(ctx.author.id, ctx.guild.id)
            await ctx.reply(result, mention_author=False)
            return

        args = args.strip().lower()

        if args in ["clear", "none"]:
            result = await self.clear_shiny_hunt(ctx.author.id, ctx.guild.id)
            await ctx.reply(result, mention_author=False)
            return

        pokemon_names = [name.strip() for name in args.split(",") if name.strip()]

        if len(pokemon_names) > 1:
            await ctx.reply("You can't hunt more than one Pokemon!", mention_author=False)
            return

        if len(pokemon_names) == 1:
            result = await self.set_shiny_hunt(ctx.author.id, ctx.guild.id, pokemon_names[0])
            await ctx.reply(result, mention_author=False)
        else:
            await ctx.reply("Please provide a Pokemon name to hunt, or use 'clear'/'none' to stop hunting.", mention_author=False)

    @commands.group(name="cl", invoke_without_command=True)
    async def collection_group(self, ctx):
        """Collection management commands"""
        if ctx.invoked_subcommand is None:
            await ctx.reply("Usage: m!cl [add/remove/clear/list] [pokemon names]", mention_author=False)

    @collection_group.command(name="add")
    async def collection_add(self, ctx, *, pokemon_names: str):
        """Add Pokemon to your collection"""
        pokemon_names_list = [name.strip() for name in pokemon_names.split(",") if name.strip()]

        if not pokemon_names_list:
            await ctx.reply("No valid Pokemon names provided", mention_author=False)
            return

        result = await self.add_pokemon_to_collection(ctx.author.id, ctx.guild.id, pokemon_names_list)
        await ctx.reply(result, mention_author=False)

    @collection_group.command(name="remove")
    async def collection_remove(self, ctx, *, pokemon_names: str):
        """Remove Pokemon from your collection"""
        pokemon_names_list = [name.strip() for name in pokemon_names.split(",") if name.strip()]

        if not pokemon_names_list:
            await ctx.reply("No valid Pokemon names provided", mention_author=False)
            return

        result = await self.remove_pokemon_from_collection(ctx.author.id, ctx.guild.id, pokemon_names_list)
        await ctx.reply(result, mention_author=False)

    @collection_group.command(name="clear")
    async def collection_clear(self, ctx):
        """Clear your entire collection"""
        result = await self.clear_user_collection(ctx.author.id, ctx.guild.id)
        await ctx.reply(result, mention_author=False)

    @collection_group.command(name="list")
    async def collection_list(self, ctx):
        """List your Pokemon collection in an embed"""
        embed = await self.create_collection_embed(ctx.author.id, ctx.guild.id, 1)

        if embed:
            # Check if there are multiple pages
            collection = await self.db.collections.find_one(
                {"user_id": ctx.author.id, "guild_id": ctx.guild.id}
            )

            if collection and collection.get('pokemon'):
                pokemon_list = collection['pokemon']
                items_per_page = 20
                total_pages = math.ceil(len(pokemon_list) / items_per_page)

                if total_pages > 1:
                    view = CollectionPaginationView(ctx.author.id, ctx.guild.id, 1, total_pages, self)
                    await ctx.reply(embed=embed, view=view, mention_author=False)
                else:
                    await ctx.reply(embed=embed, mention_author=False)
            else:
                await ctx.reply(embed=embed, mention_author=False)
        else:
            await ctx.reply("Error loading collection.", mention_author=False)

async def setup(bot):
    await bot.add_cog(Collection(bot))
