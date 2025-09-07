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

        # Collection AFK button
        if collection_afk:
            collection_button = discord.ui.Button(
                label="Collection Pings: OFF",
                style=discord.ButtonStyle.danger,
                emoji="🔕",
                row=0
            )
        else:
            collection_button = discord.ui.Button(
                label="Collection Pings: ON",
                style=discord.ButtonStyle.success,
                emoji="🔔",
                row=0
            )

        collection_button.callback = self.toggle_collection_afk
        self.add_item(collection_button)

        # Shiny Hunt AFK button
        if shiny_hunt_afk:
            shiny_button = discord.ui.Button(
                label="Shiny Hunt Pings: OFF",
                style=discord.ButtonStyle.danger,
                emoji="😴",
                row=1
            )
        else:
            shiny_button = discord.ui.Button(
                label="Shiny Hunt Pings: ON",
                style=discord.ButtonStyle.success,
                emoji="✨",
                row=1
            )

        shiny_button.callback = self.toggle_shiny_hunt_afk
        self.add_item(shiny_button)

    async def toggle_collection_afk(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button is not for you!", ephemeral=True)
            return

        collection_cog = self.cog.bot.get_cog('Collection')
        if not collection_cog:
            await interaction.response.send_message("Collection system not available", ephemeral=True)
            return

        message, new_collection_afk = await collection_cog.toggle_user_collection_afk(self.user_id, self.guild_id)
        current_shiny_hunt_afk = await collection_cog.is_user_shiny_hunt_afk(self.user_id, self.guild_id)

        self.update_buttons(new_collection_afk, current_shiny_hunt_afk)
        await interaction.response.edit_message(content=message, view=self)

    async def toggle_shiny_hunt_afk(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button is not for you!", ephemeral=True)
            return

        collection_cog = self.cog.bot.get_cog('Collection')
        if not collection_cog:
            await interaction.response.send_message("Collection system not available", ephemeral=True)
            return

        message, new_shiny_hunt_afk = await collection_cog.toggle_user_shiny_hunt_afk(self.user_id, self.guild_id)
        current_collection_afk = await collection_cog.is_user_collection_afk(self.user_id, self.guild_id)

        self.update_buttons(current_collection_afk, new_shiny_hunt_afk)
        await interaction.response.edit_message(content=message, view=self)


class HelpDropdownSelect(discord.ui.Select):
    def __init__(self, embeds):
        self.embeds = embeds

        # Define dropdown options
        options = [
            discord.SelectOption(
                label=" Overview & Basic Commands",
                description="Basic commands, ping, and Pokemon prediction",
                emoji="🏠",
                value="overview"
            ),
            discord.SelectOption(
                label=" Collection Management",
                description="Manage your Pokemon collection and get notified",
                emoji="📚",
                value="collection"
            ),
            discord.SelectOption(
                label=" Shiny Hunt System", 
                description="Hunt for specific shiny Pokemon",
                emoji="✨",
                value="shiny"
            ),
            discord.SelectOption(
                label=" AFK & Notifications",
                description="Control when you receive pings",
                emoji="😴", 
                value="afk"
            ),
            discord.SelectOption(
                label=" Starboard System",
                description="Showcase rare catches automatically",
                emoji="⭐",
                value="starboard"
            ),
            discord.SelectOption(
                label=" Admin Commands",
                description="Server management for administrators",
                emoji="👑",
                value="admin"
            ),
            discord.SelectOption(
                label=" Features Overview",
                description="All bot features and capabilities",
                emoji="🎯",
                value="features"
            )
        ]

        super().__init__(
            placeholder="📋 Choose a help category...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        # Map selection values to embed indices
        embed_map = {
            "overview": 0,
            "collection": 1, 
            "shiny": 2,
            "afk": 3,
            "starboard": 4,
            "admin": 5,
            "features": 6
        }

        selected_page = embed_map.get(self.values[0], 0)
        embed = self.embeds[selected_page]

        # Update footer with current selection
        category_names = {
            "overview": "Overview & Basic Commands",
            "collection": "Collection Management", 
            "shiny": "Shiny Hunt System",
            "afk": "AFK & Notifications",
            "starboard": "Starboard System",
            "admin": "Admin Commands", 
            "features": "Features Overview"
        }

        category_name = category_names.get(self.values[0], "Overview")
        embed.set_footer(text=f"Showing: {category_name} | Bot created for Pokemon collection management")

        await interaction.response.edit_message(embed=embed, view=self.view)


class HelpView(discord.ui.View):
    def __init__(self, embeds):
        super().__init__(timeout=300)  # 5 minutes timeout
        self.embeds = embeds

        # Add the dropdown select menu
        self.dropdown = HelpDropdownSelect(embeds)
        self.add_item(self.dropdown)

    @discord.ui.button(label='🏠 Home', style=discord.ButtonStyle.green, row=1)
    async def home_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = self.embeds[0]  # First embed (overview)
        embed.set_footer(text="Showing: Overview & Basic Commands | Bot created for Pokemon collection management")

        # Reset dropdown to placeholder
        self.dropdown.placeholder = "📋 Choose a help category..."

        await interaction.response.edit_message(embed=embed, view=self)


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

    # ===== HELP COMMAND (AT THE START) =====
    @commands.command(name="help")
    async def help_command(self, ctx):
        """Show help message with all bot commands organized with dropdown menu"""

        # Page 1: Overview and Basic Commands
        embed1 = discord.Embed(
            title="🤖 Pokemon Helper Bot - Command Guide",
            description="Welcome to the Pokemon Helper Bot! This bot helps you manage Pokemon collections, hunt for shinies, and provides automatic Pokemon detection.\n\n**Navigation:** Use the dropdown menu below to browse through different command categories.",
            color=0xf4e5ba
        )

        embed1.add_field(
            name="🔧 Basic Commands",
            value=(
                "`m!ping` - Check bot latency and response time\n"
                "`m!help` - Show this help message\n"
                "`m!serverpage` - View server settings (roles, starboard channel)"
            ),
            inline=False
        )

        embed1.add_field(
            name="🔍 Pokemon Prediction",
            value=(
                "`m!predict <image_url>` - Predict Pokemon from image URL\n"
                "`m!predict` (reply to image) - Predict Pokemon from replied image\n"
                "🤖 **Auto-detection:** Automatically identifies Poketwo spawns!"
            ),
            inline=False
        )

        # Page 2: Collection Management
        embed2 = discord.Embed(
            title="📚 Collection Management Commands",
            description="Manage your Pokemon collection and get notified when your Pokemon spawn!",
            color=0xf4e5ba
        )

        embed2.add_field(
            name="📚 Collection Commands",
            value=(
                "`m!cl add <pokemon1, pokemon2, ...>` - Add Pokemon to your collection\n"
                "`m!cl remove <pokemon1, pokemon2, ...>` - Remove Pokemon from collection\n"
                "`m!cl list` - View your collection (with pagination)\n"
                "`m!cl clear` - Clear your entire collection"
            ),
            inline=False
        )

        embed2.add_field(
            name="📚 How Collection Works",
            value=(
                "• Add Pokemon you want to be notified about\n"
                "• When those Pokemon spawn, you'll be mentioned\n"
                "• Perfect for completing your Pokedex\n"
                "• Works with Pokemon name variations and forms"
            ),
            inline=False
        )

        # Page 3: Shiny Hunt System
        embed3 = discord.Embed(
            title="✨ Shiny Hunt System",
            description="Hunt for specific shiny Pokemon and get notified when they spawn!",
            color=0xf4e5ba
        )

        embed3.add_field(
            name="✨ Shiny Hunt Commands",
            value=(
                "`m!sh <pokemon>` - Set Pokemon to hunt (only one at a time)\n"
                "`m!sh` - Check what Pokemon you're currently hunting\n"
                "`m!sh clear` or `m!sh none` - Stop hunting"
            ),
            inline=False
        )

        embed3.add_field(
            name="✨ How Shiny Hunting Works",
            value=(
                "• Set one Pokemon to actively hunt for\n"
                "• Get pinged when that Pokemon spawns\n"
                "• Other hunters will see your name when the Pokemon spawns\n"
                "• Great for coordinated shiny hunting with friends"
            ),
            inline=False
        )

        # Page 4: AFK System
        embed4 = discord.Embed(
            title="😴 AFK & Notification System",
            description="Control when you receive pings and notifications from the bot.",
            color=0xf4e5ba
        )

        embed4.add_field(
            name="😴 AFK Commands",
            value=(
                "`m!afk` - Toggle AFK status with interactive buttons\n"
                "`m!rareping` - Toggle rare Pokemon pings (if available)"
            ),
            inline=False
        )

        embed4.add_field(
            name="😴 AFK Types Explained",
            value=(
                "**Collection AFK:** Won't be pinged when your collected Pokemon spawn\n"
                "**Shiny Hunt AFK:** Your ID shows but won't be pinged when hunting Pokemon spawn\n"
                "• Use buttons in `m!afk` to toggle each individually\n"
                "• Perfect for when you're away but want others to see you're hunting"
            ),
            inline=False
        )

        # Page 5: Starboard System
        embed5 = discord.Embed(
            title="⭐ Starboard System",
            description="Automatically showcase rare catches, shinies, and high IV Pokemon Including Eggs!",
            color=0xf4e5ba
        )

        embed5.add_field(
            name="⭐ Starboard Commands (Admin Only)",
            value=(
                "`m!starboard-channel <#channel>` - Set server starboard channel\n"
                "`m!globalstarboard-channel <#channel>` - Set global starboard (Owner only)\n"
                "`m!manualcheck` (reply to catch or id) - Manually check a catch message\n"
                "`m!eggcheck` (reply to catch or id) - Manually check a catch message for egg related"
            ),
            inline=False
        )

        embed5.add_field(
            name="⭐ What Gets Posted to Starboard",
            value=(
                "✨ **Shiny Pokemon** - All shiny catches including eggs\n"
                "🎯 **Gigantamax Pokemon** - All Gigantamax catches including eggs\n"
                "📈 **High IV Pokemon** - 90% IV or higher including eggs\n"
                "📉 **Low IV Pokemon** - 10% IV or lower including eggs\n"
                "• Automatic detection from Poketwo catch messages\n"
                "• Includes Pokemon images, stats, and jump-to-message links"
            ),
            inline=False
        )

        # Page 6: Admin Commands
        embed6 = discord.Embed(
            title="👑 Admin Commands",
            description="Server management commands for administrators.",
            color=0xf4e5ba
        )

        embed6.add_field(
            name="👑 Role Management",
            value=(
                "`m!rare-role @role` - Set role to ping for rare Pokemon\n"
                "`m!regional-role @role` - Set role to ping for regional Pokemon\n"
                "`m!starboard-channel <#channel>` - Set starboard channel\n"
                "*Requires Administrator permission*"
            ),
            inline=False
        )

        embed6.add_field(
            name="👑 Server Settings",
            value=(
                "`m!serverpage` - View all server settings\n"
                "• Shows rare role, regional role, and starboard channel\n"
                "• Displays guild ID for reference\n"
                "• Available to all users"
            ),
            inline=False
        )

        # Page 7: Features Overview
        embed7 = discord.Embed(
            title="🎯 Bot Features & Capabilities",
            description="Comprehensive overview of all bot features and how they work together.",
            color=0xf4e5ba
        )

        embed7.add_field(
            name="🎯 Automatic Features",
            value=(
                "• **Auto Pokemon Detection** - Identifies Poketwo spawns automatically\n"
                "• **Shiny Hunter Pinging** - Mentions users hunting that Pokemon\n"
                "• **Collector Pinging** - Mentions users who have that Pokemon in collection\n"
                "• **Starboard Auto-posting** - Rare catches posted automatically\n"
                "• **Command Edit Support** - Commands work even with message edits"
            ),
            inline=False
        )

        embed7.add_field(
            name="🎯 Advanced Support",
            value=(
                "• **Gender Variants** - Supports male/female Pokemon forms\n"
                "• **Regional Forms** - Handles Alolan, Galarian, etc.\n"
                "• **Gigantamax Support** - Special handling for G-Max Pokemon\n"
                "• **Multi-language** - Works with various Pokemon name formats\n"
                "• **High Performance** - Optimized database queries and caching"
            ),
            inline=False
        )

        # Create list of all embeds
        embeds = [embed1, embed2, embed3, embed4, embed5, embed6, embed7]

        # Set footer for first embed
        embeds[0].set_footer(text="Showing: Overview & Basic Commands | Bot created for Pokemon collection management")

        # Create view with dropdown menu
        view = HelpView(embeds)

        await ctx.send(embed=embeds[0], view=view)

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
    @commands.command(name="ping")
    async def ping_command(self, ctx):
        """Check bot latency and response time"""
        start_time = time.time()

        # Send initial message
        sent_message = await ctx.send("🏓 Pinging...")

        # Calculate latency
        end_time = time.time()
        message_latency = round((end_time - start_time) * 1000, 2)  # Convert to milliseconds
        websocket_latency = round(self.bot.latency * 1000, 2)  # Bot's websocket latency in ms

        # Edit message with actual ping info
        embed = discord.Embed(title="🏓 Pong!", color=0xf4e5ba)
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

    @commands.command(name="afk")
    async def afk_command(self, ctx):
        """Toggle AFK status with separate buttons for collection and shiny hunt pings"""
        collection_cog = self.bot.get_cog('Collection')
        if not collection_cog:
            await ctx.reply("Collection system not available")
            return

        # Get current AFK statuses concurrently
        current_collection_afk, current_shiny_hunt_afk = await asyncio.gather(
            collection_cog.is_user_collection_afk(ctx.author.id, ctx.guild.id),
            collection_cog.is_user_shiny_hunt_afk(ctx.author.id, ctx.guild.id)
        )

        collection_status = "OFF" if current_collection_afk else "ON"
        shiny_hunt_status = "OFF" if current_shiny_hunt_afk else "ON"

        initial_message = f"**Your current AFK settings:**\nCollection Pings: {collection_status}\nShiny Hunt Pings: {shiny_hunt_status}\n\nUse the buttons below to toggle each setting individually."

        view = AFKView(ctx.author.id, ctx.guild.id, current_collection_afk, current_shiny_hunt_afk, self)
        await ctx.reply(initial_message, view=view)

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
                                # Use async prediction with confidence threshold
                                name, confidence = await self.predictor.predict(image_url, self.http_session)

                                if name and confidence:
                                    # Parse confidence and check threshold
                                    confidence_str = str(confidence).rstrip('%')
                                    try:
                                        confidence_value = float(confidence_str)
                                        if confidence_value >= 70.0:  # Only show if confidence >= 70%
                                            formatted_output = format_pokemon_prediction(name, confidence)

                                            # Get all ping information concurrently
                                            collection_cog = self.bot.get_cog('Collection')
                                            if collection_cog:
                                                # Run all database queries concurrently for better performance
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
                                        else:
                                            print(f"Low confidence prediction skipped: {name} ({confidence})")
                                    except ValueError:
                                        print(f"Could not parse confidence value: {confidence}")
                            except Exception as e:
                                print(f"Auto-detection error: {e}")


async def setup(bot):
    await bot.add_cog(General(bot))
