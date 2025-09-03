import discord
from discord.ext import commands
import json
import os
from pymongo import MongoClient
from typing import List, Dict, Optional

class PokemonCollectionCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pokemon_data = self.load_pokemon_data()
        self.db_client = MongoClient(os.getenv("MONGODB_URL"))
        self.db = self.db_client['pokemon_bot']
        self.collection = self.db['collections']
        
    def load_pokemon_data(self):
        """Load Pokemon data from pokemondata.json"""
        try:
            with open('pokemondata.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            print("Warning: pokemondata.json not found")
            return []
        except json.JSONDecodeError:
            print("Error: Invalid JSON in pokemondata.json")
            return []
    
    def get_pokemon_by_name(self, name: str) -> Optional[Dict]:
        """Find Pokemon by name (case-insensitive)"""
        name_lower = name.lower()
        for pokemon in self.pokemon_data:
            if pokemon['name'].lower() == name_lower:
                return pokemon
        return None
    
    def get_base_pokemon_and_variants(self, pokemon_name: str) -> List[Dict]:
        """Get base Pokemon and all its variants"""
        base_pokemon = self.get_pokemon_by_name(pokemon_name)
        if not base_pokemon:
            return []
        
        result = [base_pokemon]
        
        # If this is a base Pokemon (not a variant), find all its variants
        if not base_pokemon.get('is_variant', False):
            base_name = base_pokemon['name']
            for pokemon in self.pokemon_data:
                if (pokemon.get('is_variant', False) and 
                    pokemon.get('variant_of', '').lower() == base_name.lower()):
                    result.append(pokemon)
        
        return result
    
    def normalize_pokemon_name(self, name: str) -> str:
        """Normalize Pokemon name for prediction matching"""
        # Remove gender suffixes for matching
        if name.endswith('-Male') or name.endswith('-Female'):
            return name.rsplit('-', 1)[0]
        return name
    
    async def get_collectors_for_pokemon(self, guild_id: int, pokemon_name: str) -> List[int]:
        """Get all users who collect a specific Pokemon or its base form"""
        normalized_name = self.normalize_pokemon_name(pokemon_name)
        collectors = set()
        
        # Find the Pokemon in our data
        pokemon = self.get_pokemon_by_name(normalized_name)
        if not pokemon:
            return list(collectors)
        
        # Query database for collectors
        query = {"guild_id": guild_id}
        guild_collections = self.collection.find(query)
        
        for user_collection in guild_collections:
            user_pokemon_list = user_collection.get('pokemon', [])
            
            for collected_pokemon in user_pokemon_list:
                # Check if user collects this exact Pokemon
                if collected_pokemon.lower() == normalized_name.lower():
                    collectors.add(user_collection['user_id'])
                    continue
                
                # Check if user collects the base form and this is a variant
                if pokemon.get('is_variant', False):
                    variant_of = pokemon.get('variant_of', '')
                    if collected_pokemon.lower() == variant_of.lower():
                        collectors.add(user_collection['user_id'])
        
        return list(collectors)
    
    @commands.group(name='cl', invoke_without_command=True)
    async def collection(self, ctx):
        """Pokemon collection commands"""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="Pokemon Collection Commands",
                description="Manage your Pokemon collection list",
                color=0x3498db
            )
            embed.add_field(
                name="Commands",
                value="`m!cl add <pokemon>` - Add a Pokemon to your collection\n"
                      "`m!cl remove <pokemon>` - Remove a Pokemon from your collection\n"
                      "`m!cl list` - View your collection list\n"
                      "`m!cl clear` - Clear your entire collection",
                inline=False
            )
            await ctx.send(embed=embed)
    
    @collection.command(name='add')
    async def add_pokemon(self, ctx, *, pokemon_name: str):
        """Add a Pokemon to your collection"""
        if not pokemon_name:
            await ctx.send("Please specify a Pokemon name!")
            return
        
        # Validate Pokemon name (including other language names)
        pokemon = self.get_pokemon_by_name(pokemon_name)
        if not pokemon:
            await ctx.send(f"❌ '{pokemon_name}' is not a valid Pokemon name!")
            return
        
        # Always use the English name for storage
        correct_name = pokemon['name']
        guild_id = ctx.guild.id
        user_id = ctx.author.id
        
        # Check if user already has this Pokemon
        user_collection = self.collection.find_one({
            "guild_id": guild_id,
            "user_id": user_id
        })
        
        if user_collection:
            if correct_name in user_collection.get('pokemon', []):
                await ctx.send(f"❌ You already have **{correct_name}** in your collection!")
                return
            
            # Add to existing collection
            self.collection.update_one(
                {"guild_id": guild_id, "user_id": user_id},
                {"$push": {"pokemon": correct_name}}
            )
        else:
            # Create new collection
            self.collection.insert_one({
                "guild_id": guild_id,
                "user_id": user_id,
                "pokemon": [correct_name]
            })
        
        # Show confirmation with input name if different from English name
        input_name = pokemon_name if pokemon_name.lower() != correct_name.lower() else correct_name
        if input_name != correct_name:
            confirmation_text = f"✅ Added **{correct_name}** (from '{input_name}') to your collection!"
        else:
            confirmation_text = f"✅ Added **{correct_name}** to your collection!"
        
        # Show what variants will be included
        variants = self.get_base_pokemon_and_variants(correct_name)
        if len(variants) > 1 and not pokemon.get('is_variant', False):
            variant_names = [v['name'] for v in variants if v['name'] != correct_name]
            variant_text = f"\n*You'll also be pinged for: {', '.join(variant_names)}*"
        else:
            variant_text = ""
        
        await ctx.send(f"{confirmation_text}{variant_text}")
    
    @collection.command(name='remove')
    async def remove_pokemon(self, ctx, *, pokemon_name: str):
        """Remove a Pokemon from your collection"""
        if not pokemon_name:
            await ctx.send("Please specify a Pokemon name!")
            return
        
        # Validate Pokemon name (including other language names)
        pokemon = self.get_pokemon_by_name(pokemon_name)
        if not pokemon:
            await ctx.send(f"❌ '{pokemon_name}' is not a valid Pokemon name!")
            return
        
        # Always use the English name
        correct_name = pokemon['name']
        guild_id = ctx.guild.id
        user_id = ctx.author.id
        
        # Remove from collection
        result = self.collection.update_one(
            {"guild_id": guild_id, "user_id": user_id},
            {"$pull": {"pokemon": correct_name}}
        )
        
        if result.modified_count > 0:
            await ctx.send(f"✅ Removed **{correct_name}** from your collection!")
        else:
            await ctx.send(f"❌ **{correct_name}** was not in your collection!")
    
    @collection.command(name='list')
    async def list_pokemon(self, ctx):
        """List all Pokemon in your collection"""
        guild_id = ctx.guild.id
        user_id = ctx.author.id
        
        user_collection = self.collection.find_one({
            "guild_id": guild_id,
            "user_id": user_id
        })
        
        if not user_collection or not user_collection.get('pokemon'):
            await ctx.send("❌ Your collection is empty!")
            return
        
        pokemon_list = user_collection['pokemon']
        pokemon_list.sort()  # Sort alphabetically
        
        # Split into chunks if too long
        if len(pokemon_list) <= 20:
            pokemon_str = ", ".join(pokemon_list)
            embed = discord.Embed(
                title=f"{ctx.author.display_name}'s Pokemon Collection",
                description=pokemon_str,
                color=0x2ecc71
            )
            embed.set_footer(text=f"Total: {len(pokemon_list)} Pokemon")
            await ctx.send(embed=embed)
        else:
            # Send in multiple messages if too long
            chunks = [pokemon_list[i:i+20] for i in range(0, len(pokemon_list), 20)]
            for i, chunk in enumerate(chunks):
                pokemon_str = ", ".join(chunk)
                embed = discord.Embed(
                    title=f"{ctx.author.display_name}'s Pokemon Collection (Part {i+1}/{len(chunks)})",
                    description=pokemon_str,
                    color=0x2ecc71
                )
                if i == len(chunks) - 1:  # Last chunk
                    embed.set_footer(text=f"Total: {len(pokemon_list)} Pokemon")
                await ctx.send(embed=embed)
    
    @collection.command(name='clear')
    async def clear_collection(self, ctx):
        """Clear your entire collection"""
        guild_id = ctx.guild.id
        user_id = ctx.author.id
        
        # Ask for confirmation
        embed = discord.Embed(
            title="⚠️ Confirm Clear Collection",
            description="Are you sure you want to clear your entire Pokemon collection?\n"
                       "This action cannot be undone!",
            color=0xe74c3c
        )
        
        message = await ctx.send(embed=embed)
        await message.add_reaction("✅")
        await message.add_reaction("❌")
        
        def check(reaction, user):
            return (user == ctx.author and 
                   str(reaction.emoji) in ["✅", "❌"] and 
                   reaction.message.id == message.id)
        
        try:
            reaction, user = await self.bot.wait_for('reaction_add', timeout=30.0, check=check)
            
            if str(reaction.emoji) == "✅":
                # Clear the collection
                result = self.collection.delete_one({
                    "guild_id": guild_id,
                    "user_id": user_id
                })
                
                if result.deleted_count > 0:
                    await ctx.send("✅ Your collection has been cleared!")
                else:
                    await ctx.send("❌ Your collection was already empty!")
            else:
                await ctx.send("❌ Collection clear cancelled!")
                
        except asyncio.TimeoutError:
            await ctx.send("❌ Collection clear timed out!")

async def setup(bot):
    await bot.add_cog(PokemonCollectionCog(bot))
