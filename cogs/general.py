import discord
import time
import asyncio
from discord.ext import commands
from utils import (
    load_pokemon_data,
    find_pokemon_by_name,
    format_pokemon_prediction,
    get_image_url_from_message,
    is_rare_pokemon
)


class AFKView(discord.ui.View):
    def __init__(self, user_id, guild_id, collection_afk, shiny_hunt_afk, cog):
        super().__init__(timeout=300)  # 5 minutes timeout
        self.user_id = user_id
        self.guild_id = guild_id
        self.cog = cog
        self.update_buttons(collection_afk, shiny_hunt_afk)

    def update_buttons(self, collection_afk, shiny_hunt_afk):
        # Clear existing buttons
        self.clear_items()

        # Shiny Hunt button (green when ON, red when OFF)
        if shiny_hunt_afk:
            shiny_button = discord.ui.Button(
                label="ShinyHunt",
                style=discord.ButtonStyle.red,
                custom_id="shiny_hunt_afk"
            )
        else:
            shiny_button = discord.ui.Button(
                label="ShinyHunt",
                style=discord.ButtonStyle.green,
                custom_id="shiny_hunt_afk"
            )

        shiny_button.callback = self.toggle_shiny_hunt_afk
        self.add_item(shiny_button)

        # Collection button (green when ON, red when OFF)
        if collection_afk:
            collection_button = discord.ui.Button(
                label="Collection",
                style=discord.ButtonStyle.red,
                custom_id="collection_afk"
            )
        else:
            collection_button = discord.ui.Button(
                label="Collection",
                style=discord.ButtonStyle.green,
                custom_id="collection_afk"
            )

        collection_button.callback = self.toggle_collection_afk
        self.add_item(collection_button)

    async def toggle_collection_afk(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button is not for you!", ephemeral=True)
            return

        collection_cog = self.cog.bot.get_cog('Collection')
        if not collection_cog:
            await interaction.response.send_message("Collection system not available", ephemeral=True)
            return

        _, new_collection_afk = await collection_cog.toggle_user_collection_afk(self.user_id, self.guild_id)
        current_shiny_hunt_afk = await collection_cog.is_user_shiny_hunt_afk(self.user_id, self.guild_id)

        self.update_buttons(new_collection_afk, current_shiny_hunt_afk)

        # Create updated embed
        embed = self._create_afk_embed(new_collection_afk, current_shiny_hunt_afk)

        await interaction.response.edit_message(embed=embed, view=self)

    async def toggle_shiny_hunt_afk(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button is not for you!", ephemeral=True)
            return

        collection_cog = self.cog.bot.get_cog('Collection')
        if not collection_cog:
            await interaction.response.send_message("Collection system not available", ephemeral=True)
            return

        _, new_shiny_hunt_afk = await collection_cog.toggle_user_shiny_hunt_afk(self.user_id, self.guild_id)
        current_collection_afk = await collection_cog.is_user_collection_afk(self.user_id, self.guild_id)

        self.update_buttons(current_collection_afk, new_shiny_hunt_afk)

        # Create updated embed
        embed = self._create_afk_embed(current_collection_afk, new_shiny_hunt_afk)

        await interaction.response.edit_message(embed=embed, view=self)

    def _create_afk_embed(self, collection_afk, shiny_hunt_afk):
        """Create embed with current AFK status"""
        # Custom emojis
        green_dot = "<:greendot:1423970586245201920>"
        grey_dot = "<:greydot:1423970632130887710>"

        # Determine status emojis
        shiny_emoji = grey_dot if shiny_hunt_afk else green_dot
        collection_emoji = grey_dot if collection_afk else green_dot

        embed = discord.Embed(
            title="AFK Status",
            description=f"✨ ShinyHunt Pings: {shiny_emoji}\n📚 Collection Pings: {collection_emoji}",
            color=0xf4e5ba
        )

        return embed


class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Cache for guild settings to reduce database queries
        self._guild_settings_cache = {}
        self._cache_timestamps = {}
        self._cache_ttl = 300  # 5 minutes

    @property
    def db(self):
        """Get database from main module"""
        import __main__
        return getattr(__main__, 'db', None)

    @property
    def predictor(self):
        """Get predictor from main module"""
        import __main__
        return getattr(__main__, 'predictor', None)

    @property
    def http_session(self):
        """Get HTTP session from main module"""
        import __main__
        return getattr(__main__, 'http_session', None)

    # ===== UTILITY METHODS =====
    def _is_cache_valid(self, guild_id):
        """Check if guild settings cache is still valid"""
        if guild_id not in self._cache_timestamps:
            return False
        return time.time() - self._cache_timestamps[guild_id] < self._cache_ttl

    async def get_guild_ping_roles(self, guild_id):
        """Get the rare and regional ping roles for a guild with caching"""
        # Check cache first
        if self._is_cache_valid(guild_id) and guild_id in self._guild_settings_cache:
            cached_settings = self._guild_settings_cache[guild_id]
            return cached_settings.get('rare_role_id'), cached_settings.get('regional_role_id')

        if self.db is None:
            return None, None

        try:
            guild_settings = await self.db.guild_settings.find_one({"guild_id": guild_id})
            if guild_settings:
                # Update cache
                self._guild_settings_cache[guild_id] = guild_settings
                self._cache_timestamps[guild_id] = time.time()
                return guild_settings.get('rare_role_id'), guild_settings.get('regional_role_id')
        except Exception as e:
            print(f"Error getting guild ping roles: {e}")

        # Cache empty result to avoid repeated database queries
        self._guild_settings_cache[guild_id] = {}
        self._cache_timestamps[guild_id] = time.time()
        return None, None

    async def set_rare_role(self, guild_id, role_id):
        """Set the rare Pokemon ping role for a guild"""
        if self.db is None:
            return "Database not available"

        try:
            result = await self.db.guild_settings.update_one(
                {"guild_id": guild_id},
                {"$set": {"rare_role_id": role_id}},
                upsert=True
            )
            # Invalidate cache
            self._guild_settings_cache.pop(guild_id, None)
            self._cache_timestamps.pop(guild_id, None)
            return "Rare role set successfully!"
        except Exception as e:
            print(f"Error setting rare role: {e}")
            return f"Database error: {str(e)[:100]}"

    async def set_regional_role(self, guild_id, role_id):
        """Set the regional Pokemon ping role for a guild"""
        if self.db is None:
            return "Database not available"

        try:
            result = await self.db.guild_settings.update_one(
                {"guild_id": guild_id},
                {"$set": {"regional_role_id": role_id}},
                upsert=True
            )
            # Invalidate cache
            self._guild_settings_cache.pop(guild_id, None)
            self._cache_timestamps.pop(guild_id, None)
            return "Regional role set successfully!"
        except Exception as e:
            print(f"Error setting regional role: {e}")
            return f"Database error: {str(e)[:100]}"

    async def get_pokemon_ping_info(self, pokemon_name, guild_id):
        """Get ping information for a Pokemon based on its rarity"""
        if self.db is None:
            return None

        pokemon_data = load_pokemon_data()
        pokemon = find_pokemon_by_name(pokemon_name, pokemon_data)

        if not pokemon:
            return None

        rare_role_id, regional_role_id = await self.get_guild_ping_roles(guild_id)

        if is_rare_pokemon(pokemon) and rare_role_id:
            return f"Rare Ping: <@&{rare_role_id}>"

        rarity = pokemon.get('rarity', '').lower()
        if rarity == "regional" and regional_role_id:
            return f"Regional Ping: <@&{regional_role_id}>"

        return None

    async def _predict_pokemon(self, image_url, ctx):
        """Helper method for Pokemon prediction with optimized async handling"""
        if self.predictor is None:
            return "Predictor not initialized, please try again later."

        if self.http_session is None:
            return "HTTP session not available."

        try:
            # Use async prediction
            name, confidence = await self.predictor.predict(image_url, self.http_session)

            if not name or not confidence:
                return "Could not predict Pokemon from the provided image."

            formatted_output = format_pokemon_prediction(name, confidence)

            # Get ping information concurrently
            collection_cog = self.bot.get_cog('Collection')
            if collection_cog:
                # Run database queries concurrently
                hunters_task = collection_cog.get_shiny_hunters_for_pokemon(name, ctx.guild.id)
                collectors_task = collection_cog.get_collectors_for_pokemon(name, ctx.guild.id)
                ping_info_task = self.get_pokemon_ping_info(name, ctx.guild.id)

                hunters, collectors, ping_info = await asyncio.gather(
                    hunters_task, collectors_task, ping_info_task,
                    return_exceptions=True
                )

                # Handle results safely
                if isinstance(hunters, list) and hunters:
                    formatted_output += f"\nShiny Hunters: {' '.join(hunters)}"

                if isinstance(collectors, list) and collectors:
                    collector_mentions = " ".join([f"<@{user_id}>" for user_id in collectors])
                    formatted_output += f"\nCollectors: {collector_mentions}"

                if isinstance(ping_info, str) and ping_info:
                    formatted_output += f"\n{ping_info}"

            return formatted_output

        except Exception as e:
            print(f"Prediction error: {e}")
            return f"Error: {str(e)[:100]}"

    # ===== BASIC COMMANDS =====
    @commands.command(name="afk")
    async def afk_command(self, ctx):
        """Toggle AFK status with separate buttons for collection and shiny hunt pings"""
        collection_cog = self.bot.get_cog('Collection')
        if not collection_cog:
            await ctx.reply("Collection system not available", mention_author=False)
            return

        # Get current AFK statuses concurrently
        current_collection_afk, current_shiny_hunt_afk = await asyncio.gather(
            collection_cog.is_user_collection_afk(ctx.author.id, ctx.guild.id),
            collection_cog.is_user_shiny_hunt_afk(ctx.author.id, ctx.guild.id)
        )

        # Custom emojis
        green_dot = "<:greendot:1423970586245201920>"
        grey_dot = "<:greydot:1423970632130887710>"

        # Determine status emojis
        shiny_emoji = grey_dot if current_shiny_hunt_afk else green_dot
        collection_emoji = grey_dot if current_collection_afk else green_dot

        # Create embed
        embed = discord.Embed(
            title="AFK Status",
            description=f"✨ ShinyHunt Pings: {shiny_emoji}\n📚 Collection Pings: {collection_emoji}",
            color=0xf4e5ba
        )

        view = AFKView(ctx.author.id, ctx.guild.id, current_collection_afk, current_shiny_hunt_afk, self)
        await ctx.reply(embed=embed, view=view, mention_author=False)

    # ===== PREDICTION COMMANDS =====
    @commands.command(name="predict")
    async def predict_command(self, ctx, *, image_url: str = None):
        """Predict Pokemon from image URL or replied message"""
        # If no URL provided, check if replying to a message with image
        if not image_url and ctx.message.reference:
            try:
                replied_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                image_url = await get_image_url_from_message(replied_message)
            except discord.NotFound:
                await ctx.reply("Could not find the replied message.")
                return
            except discord.Forbidden:
                await ctx.reply("I don't have permission to access that message.")
                return
            except Exception as e:
                await ctx.reply(f"Error fetching replied message: {str(e)[:100]}")
                return

        # If still no image URL found
        if not image_url:
            await ctx.reply("Please provide an image URL after m!predict or reply to a message with an image.")
            return

        result = await self._predict_pokemon(image_url, ctx)
        await ctx.reply(result)

    # ===== ADMIN COMMANDS =====
    @commands.command(name="rare-role")
    @commands.has_permissions(administrator=True)
    async def rare_role_command(self, ctx, role: discord.Role):
        """Set the rare Pokemon ping role"""
        result = await self.set_rare_role(ctx.guild.id, role.id)
        await ctx.reply(result)

    @rare_role_command.error
    async def rare_role_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("You need administrator permissions to use this command.")
        elif isinstance(error, commands.BadArgument):
            await ctx.reply("Invalid role mention or ID. Use @role or role ID.")

    @commands.command(name="regional-role")
    @commands.has_permissions(administrator=True)
    async def regional_role_command(self, ctx, role: discord.Role):
        """Set the regional Pokemon ping role"""
        result = await self.set_regional_role(ctx.guild.id, role.id)
        await ctx.reply(result)

    @regional_role_command.error
    async def regional_role_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("You need administrator permissions to use this command.")
        elif isinstance(error, commands.BadArgument):
            await ctx.reply("Invalid role mention or ID. Use @role or role ID.")

    # ===== EVENT LISTENERS =====
    @commands.Cog.listener()
    async def on_message(self, message):
        """Handle auto-detection of Poketwo spawns with optimized processing"""
        # Don't respond to the bot's own messages
        if message.author == self.bot.user:
            return

        # Check if predictor is available
        if self.predictor is None:
            return

        # Auto-detect Poketwo spawns
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
                                # Use async prediction
                                name, confidence = await self.predictor.predict(image_url, self.http_session)

                                if name and confidence:
                                    # Parse confidence
                                    confidence_str = str(confidence).rstrip('%')
                                    try:
                                        confidence_value = float(confidence_str)

                                        # Handle high confidence predictions (>= 80%)
                                        if confidence_value >= 80.0:
                                            formatted_output = format_pokemon_prediction(name, confidence)

                                            # Get all ping information concurrently
                                            collection_cog = self.bot.get_cog('Collection')
                                            if collection_cog:
                                                tasks = [
                                                    collection_cog.get_shiny_hunters_for_pokemon(name, message.guild.id),
                                                    collection_cog.get_collectors_for_pokemon(name, message.guild.id),
                                                    self.get_pokemon_ping_info(name, message.guild.id)
                                                ]

                                                results = await asyncio.gather(*tasks, return_exceptions=True)
                                                hunters, collectors, ping_info = results

                                                # Handle results safely
                                                if isinstance(hunters, list) and hunters:
                                                    formatted_output += f"\nShiny Hunters: {' '.join(hunters)}"

                                                if isinstance(collectors, list) and collectors:
                                                    collector_mentions = " ".join([f"<@{user_id}>" for user_id in collectors])
                                                    formatted_output += f"\nCollectors: {collector_mentions}"

                                                if isinstance(ping_info, str) and ping_info:
                                                    formatted_output += f"\n{ping_info}"

                                            await message.reply(formatted_output)

                                        # Handle low confidence predictions (< 80%) - Event Pokemon
                                        else:
                                            formatted_output = f"Event Pokemon: {confidence}"

                                            # Get collectors who added "event" to their collection
                                            collection_cog = self.bot.get_cog('Collection')
                                            if collection_cog:
                                                try:
                                                    event_collectors = await collection_cog.get_collectors_for_pokemon("event", message.guild.id)

                                                    if isinstance(event_collectors, list) and event_collectors:
                                                        collector_mentions = " ".join([f"<@{user_id}>" for user_id in event_collectors])
                                                        formatted_output += f"\nCollectors: {collector_mentions}"
                                                except Exception as e:
                                                    print(f"Error getting event collectors: {e}")

                                            await message.reply(formatted_output)
                                            print(f"Low confidence prediction sent: Event Pokemon ({confidence})")

                                    except ValueError:
                                        print(f"Could not parse confidence value: {confidence}")
                            except Exception as e:
                                print(f"Auto-detection error: {e}")


async def setup(bot):
    await bot.add_cog(General(bot))
