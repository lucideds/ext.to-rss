from typing import Dict, List

TORZNAB_CATEGORIES: Dict[int, str] = {
    1000: "Console",
    1010: "Console/NDS",
    1020: "Console/PSP",
    1030: "Console/Wii",
    1040: "Console/XBox",
    1050: "Console/PS3",
    1060: "Console/PS4",
    1070: "Console/PS5",
    1080: "Console/Switch",
    2000: "Movies",
    2010: "Movies/3D",
    2030: "Movies/SD",
    2040: "Movies/HD",
    2045: "Movies/UHD",
    2050: "Movies/Bluray",
    3000: "Audio",
    3010: "Audio/MP3",
    3020: "Audio/Video",
    3030: "Audio/Audiobook",
    3040: "Audio/Lossless",
    4000: "PC",
    4010: "PC/0day",
    4020: "PC/ISO",
    4030: "PC/Mac",
    4040: "PC/Mobile-Other",
    4050: "PC/Games",
    5000: "TV",
    5020: "TV/FOREIGN",
    5030: "TV/SD",
    5040: "TV/HD",
    5045: "TV/UHD",
    5070: "TV/Anime",
    5080: "TV/Documentary",
    6000: "XXX",
    7000: "Books",
    7010: "Books/EBook",
    7020: "Books/Comics",
    7030: "Books/Magazines",
    8000: "Other",
}


def map_cat_to_torznab(cat_str: str) -> int:
    """Map ext.to category string to standard Torznab category ID."""
    if not cat_str:
        return 8000
    
    cat_lower = cat_str.lower()
    if "movie" in cat_lower:
        return 2000
    elif "tv" in cat_lower or "show" in cat_lower or "episode" in cat_lower:
        return 5000
    elif "music" in cat_lower or "audio" in cat_lower:
        return 3000
    elif "game" in cat_lower:
        return 1000
    elif "app" in cat_lower or "software" in cat_lower:
        return 4000
    elif "book" in cat_lower or "doc" in cat_lower or "ebook" in cat_lower:
        return 7000
    elif "anime" in cat_lower:
        return 5070
    elif "xxx" in cat_lower or "adult" in cat_lower:
        return 6000
    return 8000


def get_all_categories_xml() -> str:
    """Generate XML snippet for Torznab capabilities categories."""
    lines = ['<categories>']
    for cat_id, cat_name in TORZNAB_CATEGORIES.items():
        if cat_id % 1000 == 0:
            lines.append(f'  <category id="{cat_id}" name="{cat_name}">')
            # Subcategories
            for sub_id, sub_name in TORZNAB_CATEGORIES.items():
                if sub_id != cat_id and sub_id // 1000 == cat_id // 1000:
                    sub_short = sub_name.split("/")[-1]
                    lines.append(f'    <subcat id="{sub_id}" name="{sub_short}"/>')
            lines.append('  </category>')
    lines.append('</categories>')
    return "\n".join(lines)
