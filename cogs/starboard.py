import discord
import re
import json
import os
from datetime import datetime
from discord.ext import commands

class Starboard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pokemon_data = self.load_pokemon_data()

    @property
    def db(self):
        """Get database from main module"""
        import __main__
        return getattr(__main__, 'db', None)

    def load_pokemon_data(self):
        """Load Pokemon data from starboard.txt file"""
        try:
            # Try to load from the same directory as the cog
            starboard_file = os.path.join(os.path.dirname(__file__), '..', 'starboard.txt')
            if not os.path.exists(starboard_file):
                # Fallback to current directory
                starboard_file = 'starboard.txt'

            with open(starboard_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data
        except Exception as e:
            print(f"Error loading Pokemon data: {e}")
            return {}

    def find_pokemon_image_url(self, pokemon_name, is_shiny=False, gender=None, is_gigantamax=False):
        """Find Pokemon image URL from the loaded data with gender and Gigantamax support"""
        # Normalize the pokemon name for matching
        normalized_name = pokemon_name.strip().lower()

        # If it's Gigantamax, search for Gigantamax variant first
        if is_gigantamax:
            # First try to find Gigantamax variant
            gigantamax_name = f"gigantamax {normalized_name}"

            for key, value in self.pokemon_data.items():
                if key.startswith('variant_') and 'gigantamax' in key.lower():
                    pokemon_display_name = value.get('name', '').lower()
                    if gigantamax_name == pokemon_display_name:
                        base_url = value.get('image_url', '')
                        if is_shiny and base_url:
                            # Replace 'images' with 'shiny' for shiny Gigantamax
                            return base_url.replace('/images/', '/shiny/')
                        return base_url

        # Function to search for Pokemon with proper female variant handling
        def search_pokemon(search_name, prefer_female=False):
            # First, try to find exact match
            for key, value in self.pokemon_data.items():
                pokemon_entry_name = value.get('name', '').lower()

                # Handle the case where female variants have "_female" in the name
                if prefer_female and gender == 'female':
                    # First try to find female variant
                    if pokemon_entry_name == f"{search_name}_female":
                        return value.get('image_url', '')

                # Try exact match with the search name
                if pokemon_entry_name == search_name:
                    return value.get('image_url', '')

            # If no exact match, try partial matching
            for key, value in self.pokemon_data.items():
                pokemon_entry_name = value.get('name', '').lower()

                # Handle female variants in partial matching
                if prefer_female and gender == 'female':
                    if f"{search_name}_female" in pokemon_entry_name or pokemon_entry_name in f"{search_name}_female":
                        return value.get('image_url', '')

                # Regular partial matching
                if search_name in pokemon_entry_name or pokemon_entry_name in search_name:
                    return value.get('image_url', '')

            return None

        # Search for Pokemon image URL
        base_url = search_pokemon(normalized_name, prefer_female=True)

        # If female variant not found and we were looking for female, try the base name
        if base_url is None and gender == 'female':
            base_url = search_pokemon(normalized_name, prefer_female=False)

        if base_url and is_shiny:
            # Replace 'images' with 'shiny' for shiny Pokemon
            return base_url.replace('/images/', '/shiny/')

        return base_url

    async def set_starboard_channel(self, guild_id, channel_id):
        """Set the starboard channel for a guild"""
        if self.db is None:
            return "Database not available"

        try:
            await self.db.guild_settings.update_one(
                {"guild_id": guild_id},
                {"$set": {"starboard_channel_id": channel_id}},
                upsert=True
            )
            return "Starboard channel set successfully!"
        except Exception as e:
            print(f"Error setting starboard channel: {e}")
            return f"Database error: {str(e)[:100]}"

    async def set_global_starboard_channel(self, channel_id):
        """Set the global starboard channel"""
        if self.db is None:
            return "Database not available"

        try:
            await self.db.global_settings.update_one(
                {"_id": "starboard"},
                {"$set": {"global_starboard_channel_id": channel_id}},
                upsert=True
            )
            return "Global starboard channel set successfully!"
        except Exception as e:
            print(f"Error setting global starboard channel: {e}")
            return f"Database error: {str(e)[:100]}"

    async def get_starboard_channel(self, guild_id):
        """Get the starboard channel for a guild"""
        if self.db is None:
            return None

        try:
            guild_settings = await self.db.guild_settings.find_one({"guild_id": guild_id})
            if guild_settings:
                return guild_settings.get('starboard_channel_id')
        except Exception as e:
            print(f"Error getting starboard channel: {e}")
        return None

    async def get_global_starboard_channel(self):
        """Get the global starboard channel"""
        if self.db is None:
            return None

        try:
            global_settings = await self.db.global_settings.find_one({"_id": "starboard"})
            if global_settings:
                return global_settings.get('global_starboard_channel_id')
        except Exception as e:
            print(f"Error getting global starboard channel: {e}")
        return None

    async def get_server_settings(self, guild_id):
        """Get server settings including rare role, regional role, and starboard channel"""
        if self.db is None:
            return None, None, None

        try:
            guild_settings = await self.db.guild_settings.find_one({"guild_id": guild_id})
            if guild_settings:
                return (
                    guild_settings.get('rare_role_id'),
                    guild_settings.get('regional_role_id'),
                    guild_settings.get('starboard_channel_id')
                )
        except Exception as e:
            print(f"Error getting server settings: {e}")
        return None, None, None

    def parse_poketwo_catch_message(self, message_content):
        """Parse Poketwo catch message to extract relevant information"""
        # Pattern to match the congratulations message with gender emojis
        catch_pattern = r"Congratulations <@!?(\d+)>! You caught a Level (\d+) (.+?)(?:<:[^:]+:\d+>)? \((\d+\.?\d*)%\)!"

        match = re.search(catch_pattern, message_content)
        if not match:
            return None

        user_id = match.group(1)
        level = match.group(2)
        pokemon_name_with_gender = match.group(3).strip()
        iv = match.group(4)

        # Extract gender from emoji
        gender = None
        pokemon_name = pokemon_name_with_gender

        # Check for male emoji
        if "<:male:" in pokemon_name_with_gender:
            gender = 'male'
            pokemon_name = re.sub(r'<:male:\d+>', '', pokemon_name_with_gender).strip()
        # Check for female emoji
        elif "<:female:" in pokemon_name_with_gender:
            gender = 'female'
            pokemon_name = re.sub(r'<:female:\d+>', '', pokemon_name_with_gender).strip()

        # Check for shiny
        is_shiny = "These colors seem unusual... ✨" in message_content

        # Check for gigantamax
        is_gigantamax = "Woah! It seems that this pokémon has the Gigantamax Factor..." in message_content

        # Check for shiny streak reset
        shiny_chain = None
        chain_pattern = r"Shiny streak reset\. \(\*\*(\d+)\*\*\)"
        chain_match = re.search(chain_pattern, message_content)
        if chain_match:
            shiny_chain = chain_match.group(1)

        return {
            'user_id': user_id,
            'level': level,
            'pokemon_name': pokemon_name,
            'iv': float(iv),
            'is_shiny': is_shiny,
            'is_gigantamax': is_gigantamax,
            'shiny_chain': shiny_chain,
            'gender': gender
        }

    def create_catch_embed(self, catch_data, embed_type, message=None):
        """Create embed for different types of catches"""
        user_id = catch_data['user_id']
        pokemon_name = catch_data['pokemon_name']
        level = catch_data['level']
        iv = catch_data['iv']
        is_shiny = catch_data['is_shiny']
        is_gigantamax = catch_data['is_gigantamax']
        shiny_chain = catch_data['shiny_chain']
        gender = catch_data.get('gender')

        # Get Pokemon image URL with gender and Gigantamax support
        image_url = self.find_pokemon_image_url(pokemon_name, is_shiny, gender, is_gigantamax)

        embed = discord.Embed(color=0xf4e5ba, timestamp=datetime.utcnow())

        if embed_type == 'gigantamax':
            embed.title = "<:gigantamax:1413843021241384960> Gigantamax Catch Detected <:gigantamax:1413843021241384960>"
            embed.description = f"**Caught By:** <@{user_id}>\n**Pokémon:** Gigantamax {pokemon_name}\n**Level:** {level}\n**IV:** {iv}%"

        elif embed_type == 'shiny':
            embed.title = "✨ Shiny Catch Detected ✨"
            embed.description = f"**Caught By:** <@{user_id}>\n**Pokémon:** {pokemon_name}\n**Level:** {level}\n**IV:** {iv}%"
            if shiny_chain:
                embed.description += f"\n**Chain:** {shiny_chain}"

        elif embed_type == 'iv_high':
            embed.title = "📈 Rare IV Catch Detected 📈"
            embed.description = f"**Caught By:** <@{user_id}>\n**Pokémon:** {pokemon_name}\n**Level:** {level}\n**IV:** {iv}%"

        elif embed_type == 'iv_low':
            embed.title = "📉 Rare IV Catch Detected 📉"
            embed.description = f"**Caught By:** <@{user_id}>\n**Pokémon:** {pokemon_name}\n**Level:** {level}\n**IV:** {iv}%"

        if image_url:
            embed.set_thumbnail(url=image_url)

        # Create view with jump to message button
        view = discord.ui.View()
        if message:
            jump_button = discord.ui.Button(
                label="Jump to Message",
                url=message.jump_url,
                emoji="🔗",
                style=discord.ButtonStyle.link
            )
            view.add_item(jump_button)

        return embed, view

    async def send_to_starboard_channels(self, guild, catch_data, original_message=None):
        """Send catch data to appropriate starboard channels"""
        is_shiny = catch_data['is_shiny']
        is_gigantamax = catch_data['is_gigantamax']
        iv = catch_data['iv']

        # Get server starboard channel
        server_starboard_id = await self.get_starboard_channel(guild.id)
        server_starboard_channel = None
        if server_starboard_id:
            server_starboard_channel = guild.get_channel(server_starboard_id)

        # Get global starboard channel
        global_starboard_id = await self.get_global_starboard_channel()
        global_starboard_channel = None
        if global_starboard_id:
            global_starboard_channel = self.bot.get_channel(global_starboard_id)

        embeds_to_send = []

        # Determine what type of catch this is
        if is_gigantamax and is_shiny:
            # Gigantamax Shiny (very rare)
            embed, view = self.create_catch_embed(catch_data, 'gigantamax', original_message)
            embed.title = "<:gigantamax:1413843021241384960> ✨ Gigantamax Shiny Catch Detected ✨ <:gigantamax:1413843021241384960>"
            embeds_to_send.append((embed, view))
        elif is_gigantamax:
            # Gigantamax only
            embed, view = self.create_catch_embed(catch_data, 'gigantamax', original_message)
            embeds_to_send.append((embed, view))
        elif is_shiny:
            # Shiny only
            embed, view = self.create_catch_embed(catch_data, 'shiny', original_message)
            embeds_to_send.append((embed, view))

        # Check for rare IV (>90 or <10)
        if iv >= 90:
            embed, view = self.create_catch_embed(catch_data, 'iv_high', original_message)
            embeds_to_send.append((embed, view))
        elif iv <= 10:
            embed, view = self.create_catch_embed(catch_data, 'iv_low', original_message)
            embeds_to_send.append((embed, view))

        # Send to server starboard if configured and there are embeds to send
        if server_starboard_channel and embeds_to_send:
            for embed, view in embeds_to_send:
                try:
                    await server_starboard_channel.send(embed=embed, view=view)
                except Exception as e:
                    print(f"Error sending to server starboard: {e}")

        # Send to global starboard if configured and there are embeds to send
        if global_starboard_channel and embeds_to_send:
            for embed, view in embeds_to_send:
                try:
                    await global_starboard_channel.send(embed=embed, view=view)
                except Exception as e:
                    print(f"Error sending to global starboard: {e}")

    @commands.command(name="starboard-channel")
    @commands.has_permissions(administrator=True)
    async def starboard_channel_command(self, ctx, channel: discord.TextChannel = None):
        """Set the starboard channel for this server"""
        if channel is None:
            # Try to parse channel from mention or ID
            if ctx.message.content.count(' ') > 0:
                channel_mention = ctx.message.content.split(' ', 1)[1].strip()

                # Try to get channel by ID if it's a number
                if channel_mention.isdigit():
                    channel = ctx.guild.get_channel(int(channel_mention))
                # Try to parse mention
                elif channel_mention.startswith('<#') and channel_mention.endswith('>'):
                    channel_id = channel_mention[2:-1]
                    if channel_id.isdigit():
                        channel = ctx.guild.get_channel(int(channel_id))

        if channel is None:
            await ctx.reply("Please provide a valid channel mention or ID.")
            return

        if channel.guild != ctx.guild:
            await ctx.reply("The channel must be in this server.")
            return

        result = await self.set_starboard_channel(ctx.guild.id, channel.id)
        await ctx.reply(f"{result} Starboard channel set to {channel.mention}")

    @starboard_channel_command.error
    async def starboard_channel_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("You need administrator permissions to use this command.")
        elif isinstance(error, commands.BadArgument):
            await ctx.reply("Invalid channel mention or ID.")

    @commands.command(name="globalstarboard-channel")
    @commands.is_owner()
    async def global_starboard_channel_command(self, ctx, channel: discord.TextChannel = None):
        """Set the global starboard channel (bot owner only)"""
        if channel is None:
            # Try to parse channel from mention or ID
            if ctx.message.content.count(' ') > 0:
                channel_mention = ctx.message.content.split(' ', 1)[1].strip()

                # Try to get channel by ID if it's a number
                if channel_mention.isdigit():
                    channel = self.bot.get_channel(int(channel_mention))
                # Try to parse mention
                elif channel_mention.startswith('<#') and channel_mention.endswith('>'):
                    channel_id = channel_mention[2:-1]
                    if channel_id.isdigit():
                        channel = self.bot.get_channel(int(channel_id))

        if channel is None:
            await ctx.reply("Please provide a valid channel mention or ID.")
            return

        result = await self.set_global_starboard_channel(channel.id)
        await ctx.reply(f"{result} Global starboard channel set to {channel.mention}")

    @global_starboard_channel_command.error
    async def global_starboard_channel_error(self, ctx, error):
        if isinstance(error, commands.NotOwner):
            await ctx.reply("Only the bot owner can use this command.")
        elif isinstance(error, commands.BadArgument):
            await ctx.reply("Invalid channel mention or ID.")

    @commands.command(name="serverpage")
    async def serverpage_command(self, ctx):
        """Show server settings including rare role, regional role, and starboard channel"""
        rare_role_id, regional_role_id, starboard_channel_id = await self.get_server_settings(ctx.guild.id)

        embed = discord.Embed(
            title=f"Server Settings for {ctx.guild.name}",
            color=0x3498db,
            timestamp=datetime.utcnow()
        )

        # Rare role
        if rare_role_id:
            embed.add_field(name="Rare Role", value=f"<@&{rare_role_id}>", inline=True)
        else:
            embed.add_field(name="Rare Role", value="Not set", inline=True)

        # Regional role
        if regional_role_id:
            embed.add_field(name="Regional Role", value=f"<@&{regional_role_id}>", inline=True)
        else:
            embed.add_field(name="Regional Role", value="Not set", inline=True)

        # Starboard channel
        if starboard_channel_id:
            embed.add_field(name="Starboard Channel", value=f"<#{starboard_channel_id}>", inline=True)
        else:
            embed.add_field(name="Starboard Channel", value="Not set", inline=True)

        embed.set_footer(text=f"Guild ID: {ctx.guild.id}")
        await ctx.send(embed=embed)

    @commands.command(name="manualcheck")
    @commands.has_permissions(administrator=True)
    async def manual_check_command(self, ctx, *, catch_message=None):
        """Manually check a Poketwo catch message and send to starboard if it meets criteria"""

        # If no message provided, check if replying to a message
        original_message = None
        if catch_message is None:
            if ctx.message.reference and ctx.message.reference.resolved:
                catch_message = ctx.message.reference.resolved.content
                original_message = ctx.message.reference.resolved
            else:
                await ctx.reply("Please provide a Poketwo catch message or reply to one.\n"
                               "Example: `m!manualcheck Congratulations <@123456789>! You caught a Level 50 Pikachu (95.5%)!`")
                return

        # Parse the catch message
        catch_data = self.parse_poketwo_catch_message(catch_message)
        if not catch_data:
            await ctx.reply("❌ Invalid catch message format. Please make sure it's a proper Poketwo catch message.")
            return

        # Check if this catch meets starboard criteria
        is_shiny = catch_data['is_shiny']
        is_gigantamax = catch_data['is_gigantamax']
        iv = catch_data['iv']

        criteria_met = []
        if is_shiny:
            criteria_met.append("✨ Shiny")
        if is_gigantamax:
            criteria_met.append("<:gigantamax:1413843021241384960> Gigantamax")
        if iv >= 90:
            criteria_met.append(f"📈 High IV ({iv}%)")
        if iv <= 10:
            criteria_met.append(f"📉 Low IV ({iv}%)")

        if not criteria_met:
            await ctx.reply(f"❌ This catch doesn't meet starboard criteria.\n"
                           f"**Pokémon:** {catch_data['pokemon_name']}\n"
                           f"**IV:** {iv}% (need ≥90% or ≤10%)\n"
                           f"**Shiny:** {'Yes' if is_shiny else 'No'}\n"
                           f"**Gigantamax:** {'Yes' if is_gigantamax else 'No'}")
            return

        # Send to starboard
        await self.send_to_starboard_channels(ctx.guild, catch_data, original_message)

        criteria_text = ", ".join(criteria_met)
        await ctx.reply(f"✅ Catch sent to starboard!\n"
                       f"**Criteria met:** {criteria_text}\n"
                       f"**Pokémon:** {catch_data['pokemon_name']} (Level {catch_data['level']}, {iv}%)")

    @manual_check_command.error
    async def manual_check_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("You need administrator permissions to use this command.")

    @commands.Cog.listener()
    async def on_message(self, message):
        """Listen for Poketwo catch messages"""
        # Only process messages from Poketwo
        if message.author.id != 716390085896962058:
            return

        # Check if it's a catch message
        if not message.content.startswith("Congratulations"):
            return

        # Parse the catch message
        catch_data = self.parse_poketwo_catch_message(message.content)
        if not catch_data:
            return

        # Check if this catch is worthy of starboard
        is_shiny = catch_data['is_shiny']
        is_gigantamax = catch_data['is_gigantamax']
        iv = catch_data['iv']

        # Only send to starboard if it's shiny, gigantamax, or rare IV
        if is_shiny or is_gigantamax or iv >= 90 or iv <= 10:
            await self.send_to_starboard_channels(message.guild, catch_data, message)

async def setup(bot):
    await bot.add_cog(Starboard(bot))
