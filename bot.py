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
        await message.reply("Pong!")
        return

    # 2) Manual predict command
    if message.content.startswith("m!predict "):
        url_part = message.content.split(" ", 1)
        if len(url_part) < 2:
            await message.reply("Please provide an image URL after m!predict")
            return
            
        url = url_part[1].strip()
        await message.reply("Identifying Pokemon...")
        
        try:
            name, confidence = predictor.predict(url)
            await message.reply(f"{name}: {confidence}")
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
                                await message.reply(f"{name}: {confidence}")
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
