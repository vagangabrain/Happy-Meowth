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
        print("✅ Predictor initialized successfully")
    except Exception as e:
        print(f"❌ Failed to initialize predictor: {e}")

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    if predictor is None:
        await initialize_predictor()

@bot.event
async def on_message(message):
    # Don't respond to the bot's own messages
    if message.author == bot.user:
        return
    
    print(f"📩 Message from {message.author}: {message.content}")

    # Check if predictor is available
    if predictor is None:
        print("⚠️ Predictor not initialized, attempting to initialize...")
        await initialize_predictor()
        if predictor is None:
            return

    # 1) Test command
    if message.content.lower() == "!ping":
        await message.channel.send("🏓 Pong!")
        return

    # 2) Manual predict command
    if message.content.startswith("!identify "):
        url_part = message.content.split(" ", 1)
        if len(url_part) < 2:
            await message.channel.send("❌ Please provide an image URL after !identify")
            return
            
        url = url_part[1].strip()
        await message.channel.send("🔍 Identifying Pokémon...")
        
        try:
            name, confidence = predictor.predict(url)
            # Format name: replace underscores and hyphens, capitalize properly
            formatted_name = format_pokemon_name(name)
            await message.channel.send(f"**{formatted_name}**: {confidence}")
        except Exception as e:
            await message.channel.send(f"❌ Error: {e}")
        return

    # 3) Auto-detect Pokétwo spawns
    if message.author.id == 716390085896962058:  # Pokétwo user ID
        image_url = await get_image_url_from_message(message)
        
        if image_url:
            try:
                name, confidence = predictor.predict(image_url)
                formatted_name = format_pokemon_name(name)
                
                # Add confidence threshold to avoid low-confidence predictions
                confidence_value = float(confidence.rstrip('%'))
                if confidence_value >= 70.0:  # Only show if confidence >= 70%
                    await message.channel.send(f"**{formatted_name}**: {confidence}")
                else:
                    print(f"Low confidence prediction skipped: {formatted_name} ({confidence})")
            except Exception as e:
                print(f"❌ Auto-detection error: {e}")
                # Don't send error messages for auto-detection to avoid spam

def format_pokemon_name(name):
    """Format Pokemon name for better display"""
    # Replace underscores and hyphens with spaces
    formatted = name.replace("_", " ").replace("-", " ")
    
    # Capitalize each word
    words = formatted.split()
    capitalized_words = []
    
    for word in words:
        # Special handling for certain Pokemon name patterns
        if word.lower() in ['jr', 'mime', 'oh']:
            capitalized_words.append(word.upper() if word.lower() in ['jr'] else word.capitalize())
        else:
            capitalized_words.append(word.capitalize())
    
    return " ".join(capitalized_words)

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
        print("❌ Error: DISCORD_TOKEN environment variable not set")
        return
    
    try:
        bot.run(TOKEN)
    except discord.LoginFailure:
        print("❌ Error: Invalid Discord token")
    except Exception as e:
        print(f"❌ Error starting bot: {e}")

if __name__ == "__main__":
    main()
