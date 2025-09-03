import os
import discord
import asyncio
from predict import Prediction

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True  # Required for reading message content
bot = discord.Client(intents=intents)

# Initialize predictor with error handling
predictor = None

async def initialize_predictor():
    """Initialize the predictor asynchronously"""
    global predictor
    try:
        predictor = Prediction()
        print("Predictor initialized successfully")
    except Exception as e:
        print(f"Failed to initialize predictor: {e}")

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

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    if predictor is None:
        await initialize_predictor()

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

    # 2) Manual predict command
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
            await message.reply(formatted_output)
        except Exception as e:
            await message.reply(f"Error: {e}")
        return

    # 3) Auto-detect Poketwo spawns
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
