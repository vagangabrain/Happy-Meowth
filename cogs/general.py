import discord
import time
from discord.ext import commands
from utils import (
    load_pokemon_data,
    find_pokemon_by_name,
    format_pokemon_prediction,
    get_image_url_from_message
)

class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

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

    async def get_guild_ping_roles(self, guild_id):
        """Get the rare and regional ping roles for a guild"""
        if self.db is None:
            return None, None

        try:
            guild_settings = await self.db.guild_settings.find_one({"guild_id": guild_id})
            if guild_settings:
                return guild_settings.get('rare_role_id'), guild_settings.get('regional_role_id')
        except Exception as e:
            print(f"Error getting guild ping roles: {e}")

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

        rarity = pokemon.get('rarity')
        if not rarity:
            return None

        rare_role_id, regional_role_id = await self.get_guild_ping_roles(guild_id)

        if rarity == "rare" and rare_role_id:
            return f"Rare Ping: <@&{rare_role_id}>"
        elif rarity == "regional" and regional_role_id:
            return f"Regional Ping: <@&{regional_role_id}>"

        return None

    @commands.command(name="help")
    async def help_command(self, ctx):
        """Show help message with all bot commands"""
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
                "`m!cl add <pokemon1, pokemon2, ...>` - Add Pokemons to your collection\n"
                "`m!cl remove <pokemon1, pokemon2, ...>` - Remove Pokemons from collection\n"
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
        await ctx.send(embed=embed)

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

    @commands.command(name="predict")
    async def predict_command(self, ctx, *, image_url: str = None):
        """Predict Pokemon from image URL or replied message"""
        # Check if predictor is available
        if self.predictor is None:
            await ctx.reply("Predictor not initialized, please try again later.")
            return

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

        try:
            name, confidence = self.predictor.predict(image_url)
            if name and confidence:
                formatted_output = format_pokemon_prediction(name, confidence)

                # Get collectors for this Pokemon using collection cog
                collection_cog = self.bot.get_cog('Collection')
                if collection_cog:
                    collectors = await collection_cog.get_collectors_for_pokemon(name, ctx.guild.id)
                    if collectors:
                        collector_mentions = " ".join([f"<@{user_id}>" for user_id in collectors])
                        formatted_output += f"\nCollectors: {collector_mentions}"

                # Get ping info for rare/regional Pokemon
                ping_info = await self.get_pokemon_ping_info(name, ctx.guild.id)
                if ping_info:
                    formatted_output += f"\n{ping_info}"

                await ctx.reply(formatted_output)
            else:
                await ctx.reply("Could not predict Pokemon from the provided image.")
        except Exception as e:
            print(f"Prediction error: {e}")
            await ctx.reply(f"Error: {str(e)[:100]}")

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

    @commands.Cog.listener()
    async def on_message(self, message):
        """Handle auto-detection of Poketwo spawns"""
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
                                name, confidence = self.predictor.predict(image_url)

                                if name and confidence:
                                    # Add confidence threshold to avoid low-confidence predictions
                                    confidence_str = str(confidence).rstrip('%')
                                    try:
                                        confidence_value = float(confidence_str)
                                        if confidence_value >= 70.0:  # Only show if confidence >= 70%
                                            formatted_output = format_pokemon_prediction(name, confidence)

                                            # Get collectors for this Pokemon using collection cog
                                            collection_cog = self.bot.get_cog('Collection')
                                            if collection_cog:
                                                collectors = await collection_cog.get_collectors_for_pokemon(name, message.guild.id)
                                                if collectors:
                                                    collector_mentions = " ".join([f"<@{user_id}>" for user_id in collectors])
                                                    formatted_output += f"\nCollectors: {collector_mentions}"

                                            # Get ping info for rare/regional Pokemon
                                            ping_info = await self.get_pokemon_ping_info(name, message.guild.id)
                                            if ping_info:
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
