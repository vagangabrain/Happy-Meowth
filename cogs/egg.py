import discord
import re
import json
import os
from datetime import datetime
from discord.ext import commands

class Egg(commands.Cog):
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

    def get_gender_emoji(self, gender):
        """Get gender emoji based on gender"""
        if gender == 'male':
            return "<:male:1386677873586470932>"
        elif gender == 'female':
            return "<:female:1386678736971104339>"
        elif gender == 'unknown':
            return "<:unknown:1386678775487664200>"
        else:
            return ""

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

    def parse_poketwo_hatch_message(self, message_content, hatched_by_id=None):
        """Parse Poketwo egg hatch message to extract relevant information"""
        # Pattern to match egg hatch messages with optional bold formatting and optional IV
        hatch_pattern = r"Your <:egg_[^>]+> \*\*(.+?) Egg\*\* has hatched into a \*\*<:_:\d+> (✨ )?Level (\d+) (.+?)(?:<:[^:]+:\d+>)?(?:\s+\((\d+\.?\d*)%\))?\*\*"

        match = re.search(hatch_pattern, message_content)
        if not match:
            # Try pattern without bold formatting (fallback)
            hatch_pattern_no_bold = r"Your <:egg_[^>]+> (.+?) Egg has hatched into a <:_:\d+> (✨ )?Level (\d+) (.+?)(?:<:[^:]+:\d+>)?(?:\s+\((\d+\.?\d*)%\))?"
            match = re.search(hatch_pattern_no_bold, message_content)

        if not match:
            return None

        egg_pokemon = match.group(1).strip()
        is_shiny = match.group(2) is not None  # ✨ indicates shiny
        level = match.group(3)
        pokemon_name_with_gender = match.group(4).strip()
        iv_str = match.group(5)

        # Handle IV - if not present, it's hidden
        if iv_str:
            iv = float(iv_str)
        else:
            iv = "Hidden"

        # Extract gender from emoji - check the full message content for gender emojis
        gender = None
        pokemon_name = pokemon_name_with_gender

        # First, let's check the full message content for gender emojis
        if re.search(r'<:male:\d+>', message_content):
            gender = 'male'
            # Remove gender emoji from pokemon name if it's there
            pokemon_name = re.sub(r'<:male:\d+>', '', pokemon_name_with_gender).strip()
        elif re.search(r'<:female:\d+>', message_content):
            gender = 'female'
            # Remove gender emoji from pokemon name if it's there
            pokemon_name = re.sub(r'<:female:\d+>', '', pokemon_name_with_gender).strip()
        elif re.search(r'<:unknown:\d+>', message_content):
            gender = 'unknown'
            # Remove gender emoji from pokemon name if it's there
            pokemon_name = re.sub(r'<:unknown:\d+>', '', pokemon_name_with_gender).strip()

        # Debug print to help troubleshoot
        print(f"DEBUG: Hatch parsed - Pokemon: '{pokemon_name}', Gender: '{gender}', Full captured: '{pokemon_name_with_gender}'")

        # Check for gigantamax (in the hatched pokemon name)
        is_gigantamax = pokemon_name.lower().startswith('gigantamax')

        return {
            'egg_pokemon': egg_pokemon,
            'level': level,
            'pokemon_name': pokemon_name,
            'iv': iv,
            'is_shiny': is_shiny,
            'is_gigantamax': is_gigantamax,
            'gender': gender,
            'message_type': 'hatch',
            'hatched_by_id': hatched_by_id
        }

    async def get_hatched_by_user(self, message):
        """Get who hatched the egg from the reply"""
        if not message.reference:
            return None

        try:
            # Try cached first
            if message.reference.resolved:
                return message.reference.resolved.author.id

            # Fetch if not cached
            referenced_message = await message.channel.fetch_message(message.reference.message_id)
            return referenced_message.author.id

        except Exception as e:
            print(f"Error getting hatched user: {e}")
            return None

    def create_hatch_embed(self, hatch_data, embed_type, message=None):
        """Create embed for hatch"""
        pokemon_name = hatch_data['pokemon_name']
        level = hatch_data['level']
        iv = hatch_data['iv']
        is_shiny = hatch_data['is_shiny']
        is_gigantamax = hatch_data['is_gigantamax']
        gender = hatch_data.get('gender')
        hatched_by_id = hatch_data.get('hatched_by_id')

        # Format IV display
        if iv == "Hidden":
            iv_display = "Hidden"
        else:
            iv_display = f"{iv}%"

        # Get gender emoji
        gender_emoji = self.get_gender_emoji(gender)

        # Format Pokemon name with gender emoji - always include if we have gender info
        if gender_emoji:
            pokemon_display = f"{pokemon_name} {gender_emoji}"
        else:
            pokemon_display = pokemon_name

        # Debug print to help troubleshoot
        print(f"DEBUG: Creating hatch embed - Pokemon: '{pokemon_name}', Gender: '{gender}', Gender Emoji: '{gender_emoji}', Display: '{pokemon_display}'")

        # Get Pokemon image URL with gender and Gigantamax support
        image_url = self.find_pokemon_image_url(pokemon_name, is_shiny, gender, is_gigantamax)

        embed = discord.Embed(color=0xf4e5ba, timestamp=datetime.utcnow())

        if embed_type == 'gigantamax':
            embed.title = "<:gigantamax:1413843021241384960> Gigantamax Hatch Detected <:gigantamax:1413843021241384960>"
            base_description = f"**Pokémon:** {pokemon_display}\n**Level:** {level}\n**IV:** {iv_display}"
            if hatched_by_id:
                embed.description = f"**Hatched By:** <@{hatched_by_id}>\n{base_description}"
            else:
                embed.description = base_description

        elif embed_type == 'shiny':
            embed.title = "✨ Sparkling Hatch Detected ✨"
            base_description = f"**Pokémon:** {pokemon_display}\n**Level:** {level}\n**IV:** {iv_display}"
            if hatched_by_id:
                embed.description = f"**Hatched By:** <@{hatched_by_id}>\n{base_description}"
            else:
                embed.description = base_description

        elif embed_type == 'iv_high':
            embed.title = "📈 Rare IV Hatch Detected 📈"
            base_description = f"**Pokémon:** {pokemon_display}\n**Level:** {level}\n**IV:** {iv_display}"
            if hatched_by_id:
                embed.description = f"**Hatched By:** <@{hatched_by_id}>\n{base_description}"
            else:
                embed.description = base_description

        elif embed_type == 'iv_low':
            embed.title = "📉 Rare IV Hatch Detected 📉"
            base_description = f"**Pokémon:** {pokemon_display}\n**Level:** {level}\n**IV:** {iv_display}"
            if hatched_by_id:
                embed.description = f"**Hatched By:** <@{hatched_by_id}>\n{base_description}"
            else:
                embed.description = base_description

        # Handle Gigantamax Shiny combination
        if is_gigantamax and is_shiny:
            embed.title = "<:gigantamax:1413843021241384960> ✨ Gigantamax Sparkling Hatch Detected ✨ <:gigantamax:1413843021241384960>"

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

    async def send_to_starboard_channels(self, guild, hatch_data, original_message=None):
        """Send hatch data to appropriate starboard channels"""
        is_shiny = hatch_data['is_shiny']
        is_gigantamax = hatch_data['is_gigantamax']
        iv = hatch_data['iv']

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

        # Determine what type of hatch this is
        if is_gigantamax and is_shiny:
            # Gigantamax Shiny (very rare)
            embed, view = self.create_hatch_embed(hatch_data, 'gigantamax', original_message)
            embeds_to_send.append((embed, view))
        elif is_gigantamax:
            # Gigantamax only
            embed, view = self.create_hatch_embed(hatch_data, 'gigantamax', original_message)
            embeds_to_send.append((embed, view))
        elif is_shiny:
            # Shiny only
            embed, view = self.create_hatch_embed(hatch_data, 'shiny', original_message)
            embeds_to_send.append((embed, view))

        # Check for rare IV (>90 or <10) - only if IV is a number
        if isinstance(iv, (int, float)):
            if iv >= 90:
                embed, view = self.create_hatch_embed(hatch_data, 'iv_high', original_message)
                embeds_to_send.append((embed, view))
            elif iv <= 10:
                embed, view = self.create_hatch_embed(hatch_data, 'iv_low', original_message)
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

    @commands.command(name="eggcheck")
    @commands.has_permissions(administrator=True)
    async def egg_check_command(self, ctx, *, input_data=None):
        """Manually check a Poketwo hatch message and send to starboard if it meets criteria

        Usage:
        - Reply to a message: m!eggcheck
        - Provide message ID: m!eggcheck 123456789012345678
        - Provide message text: m!eggcheck Your <:egg_green_3:...> **Alolan Meowth Egg** has hatched...
        """

        original_message = None
        hatched_by_id = None
        hatch_message = None

        if input_data is None:
            # User must be replying to a message
            if ctx.message.reference and ctx.message.reference.resolved:
                hatch_message = ctx.message.reference.resolved.content
                original_message = ctx.message.reference.resolved

                # Get the hatched user from the reply
                hatched_by_id = await self.get_hatched_by_user(original_message)
            else:
                await ctx.reply("Please provide a Poketwo hatch message, message ID, or reply to one.\n"
                               "Examples:\n"
                               "`m!eggcheck 123456789012345678` (message ID)\n"
                               "`m!eggcheck Your <:egg_green_3:...> **Alolan Meowth Egg** has hatched...`\n"
                               "Or reply to a message with just `m!eggcheck`")
                return
        else:
            # Check if input_data is a message ID (numeric)
            if input_data.strip().isdigit():
                message_id = int(input_data.strip())
                try:
                    # Try to fetch the message from the current channel first
                    try:
                        original_message = await ctx.channel.fetch_message(message_id)
                    except discord.NotFound:
                        # If not found in current channel, search in all channels in the guild
                        found_message = None
                        for channel in ctx.guild.text_channels:
                            if channel.permissions_for(ctx.guild.me).read_message_history:
                                try:
                                    found_message = await channel.fetch_message(message_id)
                                    original_message = found_message
                                    break
                                except (discord.NotFound, discord.Forbidden):
                                    continue

                        if not found_message:
                            await ctx.reply(f"❌ Could not find message with ID `{message_id}` in this server.")
                            return

                    hatch_message = original_message.content

                    # Check if the message is from Poketwo
                    if original_message.author.id != 716390085896962058:
                        await ctx.reply(f"❌ The message with ID `{message_id}` is not from Poketwo.")
                        return

                    # Get the hatched user from the reply
                    hatched_by_id = await self.get_hatched_by_user(original_message)

                except ValueError:
                    await ctx.reply(f"❌ Invalid message ID: `{input_data.strip()}`")
                    return
                except discord.Forbidden:
                    await ctx.reply(f"❌ I don't have permission to access the message with ID `{message_id}`.")
                    return
                except Exception as e:
                    await ctx.reply(f"❌ Error fetching message: {str(e)}")
                    return
            else:
                # Treat as message content
                hatch_message = input_data

        # Try to parse as hatch message
        hatch_data = self.parse_poketwo_hatch_message(hatch_message, hatched_by_id)

        if not hatch_data:
            await ctx.reply("❌ Invalid message format. Please make sure it's a proper Poketwo egg hatch message.")
            return

        # Check if this meets starboard criteria
        is_shiny = hatch_data['is_shiny']
        is_gigantamax = hatch_data['is_gigantamax']
        iv = hatch_data['iv']
        pokemon_name = hatch_data['pokemon_name']
        level = hatch_data['level']
        gender = hatch_data.get('gender')

        criteria_met = []

        if is_shiny:
            criteria_met.append("✨ Shiny")
        if is_gigantamax:
            criteria_met.append("<:gigantamax:1413843021241384960> Gigantamax")
        if isinstance(iv, (int, float)):
            if iv >= 90:
                criteria_met.append(f"📈 High IV ({iv}%)")
            elif iv <= 10:
                criteria_met.append(f"📉 Low IV ({iv}%)")

        if not criteria_met:
            # Format IV display for error message
            if iv == "Hidden":
                iv_display = "Hidden"
            else:
                iv_display = f"{iv}%"

            # Format pokemon name with gender for error message
            gender_emoji = self.get_gender_emoji(gender)
            pokemon_display = f"{pokemon_name} {gender_emoji}" if gender_emoji else pokemon_name

            await ctx.reply(f"❌ This hatch doesn't meet starboard criteria.\n"
                           f"**Pokémon:** {pokemon_display}\n"
                           f"**Level:** {level}\n"
                           f"**IV:** {iv_display} (need ≥90% or ≤10% for IV criteria)\n"
                           f"**Shiny:** {'Yes' if is_shiny else 'No'}\n"
                           f"**Gigantamax:** {'Yes' if is_gigantamax else 'No'}")
            return

        # Send to starboard
        await self.send_to_starboard_channels(ctx.guild, hatch_data, original_message)

        criteria_text = ", ".join(criteria_met)
        # Format IV for success message
        if iv == "Hidden":
            iv_display = "Hidden"
        else:
            iv_display = f"{iv}%"

        # Add debug info about hatched_by_id and message source
        debug_info = ""
        hatched_by_id_final = hatch_data.get('hatched_by_id')
        if hatched_by_id_final:
            debug_info = f"\n**Hatched By:** <@{hatched_by_id_final}>"
        else:
            debug_info = f"\n**Hatched By:** Could not determine"

        # Add message source info
        if original_message:
            debug_info += f"\n**Message:** [Jump to original]({original_message.jump_url})"

        # Format pokemon name with gender for success message
        gender_emoji = self.get_gender_emoji(gender)
        pokemon_display = f"{pokemon_name} {gender_emoji}" if gender_emoji else pokemon_name

        await ctx.reply(f"✅ Hatch sent to starboard!\n"
                       f"**Criteria met:** {criteria_text}\n"
                       f"**Pokémon:** {pokemon_display} (Level {level}, {iv_display}){debug_info}")

    @egg_check_command.error
    async def egg_check_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("You need administrator permissions to use this command.")
        else:
            # Log unexpected errors
            print(f"Unexpected error in eggcheck: {error}")
            await ctx.reply("❌ An unexpected error occurred. Please try again.")

    @commands.Cog.listener()
    async def on_message(self, message):
        """Listen for Poketwo hatch messages"""
        # Only process messages from Poketwo
        if message.author.id != 716390085896962058:
            return

        # Check if it's a hatch message
        if "Egg has hatched into" in message.content:
            # Get the user who hatched the egg from the reply
            hatched_by_id = await self.get_hatched_by_user(message)
            hatch_data = self.parse_poketwo_hatch_message(message.content, hatched_by_id)

            if not hatch_data:
                return

            # Check if this hatch is worthy of starboard
            is_shiny = hatch_data['is_shiny']
            is_gigantamax = hatch_data['is_gigantamax']
            iv = hatch_data['iv']

            # Check criteria: shiny, gigantamax, or rare IV
            if is_shiny or is_gigantamax or (isinstance(iv, (int, float)) and (iv >= 90 or iv <= 10)):
                await self.send_to_starboard_channels(message.guild, hatch_data, message)

async def setup(bot):
    await bot.add_cog(Egg(bot))
