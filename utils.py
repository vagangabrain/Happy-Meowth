import json
import unicodedata
import re

def load_pokemon_data():
    """Load Pokemon data from pokemondata.json"""
    try:
        with open('pokemondata.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Failed to load pokemondata.json: {e}")
        return []

def normalize_pokemon_name(name):
    """
    Normalize Pokemon name by:
    1. Removing accents/diacritics
    2. Removing gender suffixes (-Male, -Female)
    """
    if not name:
        return ""

    # Remove accents/diacritics using Unicode normalization
    # NFD decomposes characters, then we filter out combining characters
    normalized = unicodedata.normalize('NFD', name)
    without_accents = ''.join(char for char in normalized if unicodedata.category(char) != 'Mn')

    # Remove gender suffixes
    if without_accents.endswith("-Male"):
        without_accents = without_accents[:-5]  # Remove "-Male"
    elif without_accents.endswith("-Female"):
        without_accents = without_accents[:-7]  # Remove "-Female"

    return without_accents.strip()

def find_pokemon_by_name(name, pokemon_data):
    """Find Pokemon by name (including other language names) - original function"""
    name_lower = name.lower().strip()
    for pokemon in pokemon_data:
        # Check main name
        if pokemon.get('name', '').lower() == name_lower:
            return pokemon
        # Check other language names (only if the key exists and is not None)
        other_names = pokemon.get('other_names')
        if other_names and isinstance(other_names, dict):
            for lang_name in other_names.values():
                if lang_name and isinstance(lang_name, str) and lang_name.lower() == name_lower:
                    return pokemon
    return None

def find_pokemon_by_name_flexible(search_name, pokemon_data):
    """
    Find Pokemon by name with flexible matching (accent-insensitive)
    """
    if not search_name or not pokemon_data:
        return None

    # Normalize the search name
    normalized_search = normalize_pokemon_name(search_name).lower()

    # First try exact match with normalization
    for pokemon in pokemon_data:
        # Check main name
        if normalize_pokemon_name(pokemon.get('name', '')).lower() == normalized_search:
            return pokemon

        # Check other language names
        other_names = pokemon.get('other_names')
        if other_names and isinstance(other_names, dict):
            for lang_name in other_names.values():
                if lang_name and isinstance(lang_name, str):
                    if normalize_pokemon_name(lang_name).lower() == normalized_search:
                        return pokemon

    # If no exact match, try partial match (contains)
    for pokemon in pokemon_data:
        # Check main name
        if normalized_search in normalize_pokemon_name(pokemon.get('name', '')).lower():
            return pokemon

        # Check other language names
        other_names = pokemon.get('other_names')
        if other_names and isinstance(other_names, dict):
            for lang_name in other_names.values():
                if lang_name and isinstance(lang_name, str):
                    if normalized_search in normalize_pokemon_name(lang_name).lower():
                        return pokemon

    return None

def get_pokemon_variants(base_pokemon_name, pokemon_data):
    """Get all variants of a Pokemon (including the base form)"""
    variants = []
    base_pokemon_name_lower = base_pokemon_name.lower()
    for pokemon in pokemon_data:
        pokemon_name = pokemon.get('name', '')
        # Add the base Pokemon itself
        if pokemon_name.lower() == base_pokemon_name_lower:
            variants.append(pokemon_name)
        # Add variants that belong to this base Pokemon
        elif (pokemon.get('is_variant') and 
              pokemon.get('variant_of', '').lower() == base_pokemon_name_lower):
            variants.append(pokemon_name)
    return variants

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

async def get_image_url_from_message(message):
    """Extract image URL from message attachments or embeds"""
    image_url = None
    # Check attachments first
    if message.attachments:
        for attachment in message.attachments:
            if any(attachment.url.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".webp", ".gif"]):
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
