from settings import *
import os

def dashes(seriesName):
    return "_".join(seriesName.split(" ")).lower()

def add_zeros(pgNum):
    digits = len(pgNum)
    zeros = "0" * (EST_MAX_DIGITS - digits)
    return zeros + pgNum

def get_url(seriesName, chpNum, pgNum=1):
    return os.path.join(PROVIDER, dashes(seriesName), f"{dashes(seriesName)}_{chpNum}", f"{dashes(seriesName)}_{chpNum}_{pgNum}{FILE_EXT}").replace("\\", "/")

def get_download_path(seriesName, chpNum):
    formatted_series_name = dashes(seriesName)
    return os.path.join(LOCAL_PATH, formatted_series_name, str(chpNum))
