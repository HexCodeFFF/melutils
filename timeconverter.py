import re
from datetime import timedelta

from discord.ext import commands

time_regex = re.compile(r"(\d{1,5}(?:[.,]?\d{1,5})?)([smhdwy])")
time_dict = {"h": 3600, "s": 1, "m": 60, "d": 86400, "w": 604800, "y": 86400 * 365}


def time_converter(argument) -> timedelta:
    """
    Converts a time string such as "6d" or "80m" into a timedelta
    """
    if argument == "0":  # edge case
        return timedelta(seconds=0)
    matches = time_regex.findall(argument.lower())
    time = 0
    if not matches:
        raise commands.BadArgument(f"{argument} is not a valid time string.")
    for v, k in matches:
        try:
            time += time_dict[k] * float(v)
        except KeyError:
            raise commands.BadArgument(f"{k} is an invalid time-key! h/m/s/d/w are valid!")
        except ValueError:
            raise commands.BadArgument(f"{v} is not a number!")
    return timedelta(seconds=time)
