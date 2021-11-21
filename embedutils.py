import copy
import re
import typing

import discord


def add_long_field(embed: discord.Embed, name: str, value: str, inline: bool = False,
                   erroriftoolong: bool = False) -> discord.Embed:
    """
    add fields every 1024 characters to a discord embed
    :param inline: inline of embed
    :param embed: embed
    :param name: title of embed
    :param value: long value
    :param erroriftoolong: if true, throws an error if embed exceeds 6000 in length
    :return: updated embed
    """
    if len(value) <= 1024:
        return embed.add_field(name=name, value=value, inline=inline)
    else:
        for i, section in enumerate(re.finditer('.{1,1024}', value, flags=re.S)):  # split every 1024 chars
            embed.add_field(name=f"{name} `({i + 1}/{len(value) // 1024})`", value=section[0], inline=inline)
    if len(embed) > 6000 and erroriftoolong:
        raise Exception(f"Generated embed exceeds maximum size. ({len(embed)} > 6000)")
    return embed


def split_embed(embed: discord.Embed) -> typing.List[discord.Embed]:
    """
    splits one embed into one or more embeds to avoid hitting the 6000 char limit
    :param embed: the initial embed
    :return: a list of embeds, none of which should have more than 25 fields or more than 6000 chars
    """
    out = []
    baseembed = copy.deepcopy(embed)
    baseembed.clear_fields()
    if len(baseembed) > 6000:
        raise Exception(f"Embed without fields exceeds 6000 chars.")
    currentembed = copy.deepcopy(baseembed)
    for field in embed.fields:  # for every field in the embed
        currentembed.add_field(name=field.name, value=field.value,
                               inline=field.inline)  # add it to the "currentembed" object we are working on
        if len(currentembed) > 6000 or len(currentembed.fields) > 25:  # if the currentembed object is too big
            currentembed.remove_field(-1)  # remove the field
            out.append(currentembed)  # add the embed to our output
            currentembed = copy.deepcopy(baseembed)  # make a new embed
            currentembed.add_field(name=field.name, value=field.value,
                                   inline=field.inline)  # add the field to our new embed instead
    out.append(currentembed)  # add the final embed which didnt exceed 6000 to the output
    return out
