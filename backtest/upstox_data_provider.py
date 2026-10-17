"""
Upstox API Data Provider and Historical Cache
=============================================
Fetches and caches daily OHLCV candles from the Upstox Developer API (v3)
for the liquid Top 50 NSE F&O universe.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

UPSTOX_HISTORICAL_V3_BASE = "https://api.upstox.com/v3/historical-candle"

# 50 Liquid F&O Underlyings with NSE_EQ Instrument Keys, Lot Sizes, and Strike Steps
TOP_50_UNIVERSE: Dict[str, Dict[str, Any]] = {
    "MARUTI":     {"key": "NSE_EQ|INE585B01010", "lot": 50,   "step": 100.0, "roe": 16.8, "secRoe": 17.5, "pat": 13.2},
    "BAJAJ-AUTO": {"key": "NSE_EQ|INE917I01010", "lot": 75,   "step": 100.0, "roe": 27.8, "secRoe": 17.5, "pat": 19.4},
    "GODREJCP":   {"key": "NSE_EQ|INE102D01028", "lot": 500,  "step": 10.0,  "roe": 17.4, "secRoe": 24.0, "pat": 4.8},
    "INFY":       {"key": "NSE_EQ|INE009A01021", "lot": 400,  "step": 20.0,  "roe": 31.8, "secRoe": 24.5, "pat": 8.7},
    "KOTAKBANK":  {"key": "NSE_EQ|INE237A01036", "lot": 2000, "step": 5.0,   "roe": 15.4, "secRoe": 14.2, "pat": 12.1},
    "DIVISLAB":   {"key": "NSE_EQ|INE361B01024", "lot": 100,  "step": 50.0,  "roe": 16.4, "secRoe": 15.2, "pat": 21.5},
    "HEROMOTOCO": {"key": "NSE_EQ|INE158A01026", "lot": 150,  "step": 50.0,  "roe": 24.1, "secRoe": 17.5, "pat": 16.8},
    "TRENT":      {"key": "NSE_EQ|INE849A01020", "lot": 225,  "step": 100.0, "roe": 32.5, "secRoe": 18.0, "pat": 41.0},
    "TECHM":      {"key": "NSE_EQ|INE669C01036", "lot": 600,  "step": 20.0,  "roe": 15.8, "secRoe": 24.5, "pat": 18.2},
    "BRITANNIA":  {"key": "NSE_EQ|INE216A01030", "lot": 125,  "step": 50.0,  "roe": 54.2, "secRoe": 24.0, "pat": 7.5},
    "SBIN":       {"key": "NSE_EQ|INE062A01020", "lot": 750,  "step": 10.0,  "roe": 17.8, "secRoe": 14.2, "pat": 20.4},
    "TATASTEEL":  {"key": "NSE_EQ|INE081A01020", "lot": 2750, "step": 2.5,   "roe": 9.4,  "secRoe": 12.4, "pat": 4.2},
    "WIPRO":      {"key": "NSE_EQ|INE075A01022", "lot": 3000, "step": 2.5,   "roe": 15.6, "secRoe": 24.5, "pat": 5.4},
    "CHOLAFIN":   {"key": "NSE_EQ|INE121A01024", "lot": 625,  "step": 20.0,  "roe": 20.6, "secRoe": 15.8, "pat": 23.7},
    "VOLTAS":     {"key": "NSE_EQ|INE226A01021", "lot": 375,  "step": 20.0,  "roe": 9.8,  "secRoe": 15.0, "pat": 11.2},
    "GRASIM":     {"key": "NSE_EQ|INE047A01021", "lot": 250,  "step": 40.0,  "roe": 13.8, "secRoe": 11.9, "pat": 11.5},
    "ONGC":       {"key": "NSE_EQ|INE213A01029", "lot": 2250, "step": 2.5,   "roe": 15.1, "secRoe": 12.0, "pat": 6.1},
    "ASIANPAINT": {"key": "NSE_EQ|INE021A01026", "lot": 250,  "step": 20.0,  "roe": 26.4, "secRoe": 18.5, "pat": 6.4},
    "NTPC":       {"key": "NSE_EQ|INE733E01010", "lot": 1500, "step": 5.0,   "roe": 14.2, "secRoe": 12.8, "pat": 11.4},
    "ABB":        {"key": "NSE_EQ|INE117A01022", "lot": 125,  "step": 100.0, "roe": 22.8, "secRoe": 14.5, "pat": 28.5},
    "NESTLEIND":  {"key": "NSE_EQ|INE239A01024", "lot": 500,  "step": 20.0,  "roe": 84.0, "secRoe": 24.0, "pat": 9.8},
    "APOLLOHOSP": {"key": "NSE_EQ|INE437A01024", "lot": 125,  "step": 100.0, "roe": 18.2, "secRoe": 14.8, "pat": 25.4},
    "JSWSTEEL":   {"key": "NSE_EQ|INE019A01038", "lot": 675,  "step": 20.0,  "roe": 14.1, "secRoe": 12.4, "pat": 13.8},
    "COALINDIA":  {"key": "NSE_EQ|INE522F01014", "lot": 1350, "step": 5.0,   "roe": 42.5, "secRoe": 16.0, "pat": 12.9},
    "BAJFINANCE": {"key": "NSE_EQ|INE296A01032", "lot": 750,  "step": 10.0,  "roe": 22.1, "secRoe": 15.8, "pat": 22.4},
    "HAL":        {"key": "NSE_EQ|INE066F01020", "lot": 150,  "step": 50.0,  "roe": 28.9, "secRoe": 16.0, "pat": 26.4},
    "RELIANCE":   {"key": "NSE_EQ|INE002A01018", "lot": 500,  "step": 20.0,  "roe": 11.2, "secRoe": 12.0, "pat": 7.9},
    "TCS":        {"key": "NSE_EQ|INE467B01029", "lot": 225,  "step": 20.0,  "roe": 51.4, "secRoe": 24.5, "pat": 9.4},
    "HDFCBANK":   {"key": "NSE_EQ|INE040A01034", "lot": 650,  "step": 10.0,  "roe": 16.1, "secRoe": 14.2, "pat": 15.4},
    "POWERGRID":  {"key": "NSE_EQ|INE752E01010", "lot": 1900, "step": 5.0,   "roe": 18.6, "secRoe": 12.8, "pat": 8.9},
    "DLF":        {"key": "NSE_EQ|INE271C01023", "lot": 950,  "step": 10.0,  "roe": 11.8, "secRoe": 10.2, "pat": 24.0},
    "PIDILITIND": {"key": "NSE_EQ|INE318A01026", "lot": 500,  "step": 20.0,  "roe": 23.6, "secRoe": 16.5, "pat": 17.9},
    "DRREDDY":    {"key": "NSE_EQ|INE089A01031", "lot": 625,  "step": 20.0,  "roe": 19.4, "secRoe": 15.2, "pat": 14.2},
    "INDIGO":     {"key": "NSE_EQ|INE646L01027", "lot": 150,  "step": 50.0,  "roe": 44.0, "secRoe": 14.0, "pat": 22.8},
    "BHARTIARTL": {"key": "NSE_EQ|INE397D01024", "lot": 475,  "step": 20.0,  "roe": 16.9, "secRoe": 11.0, "pat": 34.2},
    "CIPLA":      {"key": "NSE_EQ|INE059A01026", "lot": 425,  "step": 20.0,  "roe": 16.8, "secRoe": 15.2, "pat": 16.4},
    "TITAN":      {"key": "NSE_EQ|INE280A01028", "lot": 175,  "step": 50.0,  "roe": 31.2, "secRoe": 18.0, "pat": 15.8},
    "AXISBANK":   {"key": "NSE_EQ|INE238A01034", "lot": 625,  "step": 20.0,  "roe": 17.2, "secRoe": 14.2, "pat": 14.6},
    "SUNPHARMA":  {"key": "NSE_EQ|INE044A01036", "lot": 350,  "step": 20.0,  "roe": 17.6, "secRoe": 15.2, "pat": 18.9},
    "HINDALCO":   {"key": "NSE_EQ|INE038A01020", "lot": 700,  "step": 10.0,  "roe": 14.9, "secRoe": 12.4, "pat": 24.6},
    "BEL":        {"key": "NSE_EQ|INE263A01024", "lot": 1425, "step": 5.0,   "roe": 26.4, "secRoe": 16.0, "pat": 29.1},
    "HCLTECH":    {"key": "NSE_EQ|INE860A01027", "lot": 400,  "step": 20.0,  "roe": 25.2, "secRoe": 24.5, "pat": 11.8},
    "HAVELLS":    {"key": "NSE_EQ|INE176B01034", "lot": 500,  "step": 20.0,  "roe": 18.9, "secRoe": 15.0, "pat": 14.1},
    "ITC":        {"key": "NSE_EQ|INE154A01025", "lot": 1725, "step": 5.0,   "roe": 28.4, "secRoe": 24.0, "pat": 6.8},
    "M&M":        {"key": "NSE_EQ|INE101A01026", "lot": 200,  "step": 50.0,  "roe": 19.8, "secRoe": 17.5, "pat": 21.6},
    "ICICIBANK":  {"key": "NSE_EQ|INE090A01021", "lot": 700,  "step": 20.0,  "roe": 18.4, "secRoe": 14.2, "pat": 17.2},
    "LT":         {"key": "NSE_EQ|INE018A01030", "lot": 175,  "step": 50.0,  "roe": 16.5, "secRoe": 13.8, "pat": 15.1},
    "ULTRACEMCO": {"key": "NSE_EQ|INE481G01011", "lot": 50,   "step": 100.0, "roe": 13.5, "secRoe": 11.9, "pat": 14.8},
    "SIEMENS":    {"key": "NSE_EQ|INE003A01024", "lot": 175,  "step": 50.0,  "roe": 17.9, "secRoe": 14.5, "pat": 21.0},
    "DABUR":      {"key": "NSE_EQ|INE016A01026", "lot": 1250, "step": 5.0,   "roe": 19.2, "secRoe": 24.0, "pat": 5.2},
}


# All 220 Active NSE Instruments with Upstox NSE_EQ Keys
ALL_220_UNIVERSE_KEYS: Dict[str, str] = {
    "360ONE": "NSE_EQ|INE466L01038",
    "ABB": "NSE_EQ|INE117A01022",
    "ABCAPITAL": "NSE_EQ|INE674K01013",
    "ADANIENSOL": "NSE_EQ|INE931S01010",
    "ADANIENT": "NSE_EQ|INE423A01024",
    "ADANIGREEN": "NSE_EQ|INE364U01010",
    "ADANIPORTS": "NSE_EQ|INE742F01042",
    "ADANIPOWER": "NSE_EQ|INE814H01029",
    "ALKEM": "NSE_EQ|INE540L01014",
    "AMBER": "NSE_EQ|INE371P01015",
    "AMBUJACEM": "NSE_EQ|INE079A01024",
    "ANANDRATHI": "NSE_EQ|INE463V01026",
    "ANGELONE": "NSE_EQ|INE732I01021",
    "APLAPOLLO": "NSE_EQ|INE702C01027",
    "APOLLOHOSP": "NSE_EQ|INE437A01024",
    "ASHOKLEY": "NSE_EQ|INE208A01029",
    "ASIANPAINT": "NSE_EQ|INE021A01026",
    "ASTRAL": "NSE_EQ|INE006I01046",
    "ATHERENERG": "NSE_EQ|INE0LEZ01016",
    "AUBANK": "NSE_EQ|INE949L01017",
    "AUROPHARMA": "NSE_EQ|INE406A01037",
    "AXISBANK": "NSE_EQ|INE238A01034",
    "BAJAJ-AUTO": "NSE_EQ|INE917I01010",
    "BAJAJFINSV": "NSE_EQ|INE918I01026",
    "BAJAJHLDNG": "NSE_EQ|INE118A01012",
    "BAJFINANCE": "NSE_EQ|INE296A01032",
    "BANDHANBNK": "NSE_EQ|INE545U01014",
    "BANKBARODA": "NSE_EQ|INE028A01039",
    "BANKINDIA": "NSE_EQ|INE084A01016",
    "BDL": "NSE_EQ|INE171Z01026",
    "BEL": "NSE_EQ|INE263A01024",
    "BHARATFORG": "NSE_EQ|INE465A01025",
    "BHARTIARTL": "NSE_EQ|INE397D01024",
    "BHEL": "NSE_EQ|INE257A01026",
    "BIOCON": "NSE_EQ|INE376G01013",
    "BLUESTARCO": "NSE_EQ|INE472A01039",
    "BOSCHLTD": "NSE_EQ|INE323A01026",
    "BPCL": "NSE_EQ|INE029A01011",
    "BRITANNIA": "NSE_EQ|INE216A01030",
    "BSE": "NSE_EQ|INE118H01025",
    "CAMS": "NSE_EQ|INE596I01020",
    "CANBK": "NSE_EQ|INE476A01022",
    "CDSL": "NSE_EQ|INE736A01011",
    "CENTRALBK": "NSE_EQ|INE483A01010",
    "CGPOWER": "NSE_EQ|INE067A01029",
    "CHOLAFIN": "NSE_EQ|INE121A01024",
    "CIPLA": "NSE_EQ|INE059A01026",
    "COALINDIA": "NSE_EQ|INE522F01014",
    "COCHINSHIP": "NSE_EQ|INE704P01025",
    "COFORGE": "NSE_EQ|INE591G01025",
    "COLPAL": "NSE_EQ|INE259A01022",
    "CONCOR": "NSE_EQ|INE111A01025",
    "CROMPTON": "NSE_EQ|INE299U01018",
    "CUMMINSIND": "NSE_EQ|INE298A01020",
    "DABUR": "NSE_EQ|INE016A01026",
    "DELHIVERY": "NSE_EQ|INE148O01028",
    "DIVISLAB": "NSE_EQ|INE361B01024",
    "DIXON": "NSE_EQ|INE935N01020",
    "DLF": "NSE_EQ|INE271C01023",
    "DMART": "NSE_EQ|INE192R01011",
    "DRREDDY": "NSE_EQ|INE089A01031",
    "EICHERMOT": "NSE_EQ|INE066A01021",
    "ENRIN": "NSE_EQ|INE1NPP01017",
    "ETERNAL": "NSE_EQ|INE758T01015",
    "FEDERALBNK": "NSE_EQ|INE171A01029",
    "FORCEMOT": "NSE_EQ|INE451A01017",
    "FORTIS": "NSE_EQ|INE061F01013",
    "GAIL": "NSE_EQ|INE129A01019",
    "GLENMARK": "NSE_EQ|INE935A01035",
    "GMRAIRPORT": "NSE_EQ|INE776C01039",
    "GODFRYPHLP": "NSE_EQ|INE260B01028",
    "GODREJCP": "NSE_EQ|INE102D01028",
    "GODREJPROP": "NSE_EQ|INE484J01027",
    "GRASIM": "NSE_EQ|INE047A01021",
    "GVT&D": "NSE_EQ|INE200A01026",
    "HAL": "NSE_EQ|INE066F01020",
    "HAVELLS": "NSE_EQ|INE176B01034",
    "HCLTECH": "NSE_EQ|INE860A01027",
    "HDFCAMC": "NSE_EQ|INE127D01025",
    "HDFCBANK": "NSE_EQ|INE040A01034",
    "HDFCLIFE": "NSE_EQ|INE795G01014",
    "HEROMOTOCO": "NSE_EQ|INE158A01026",
    "HFCL": "NSE_EQ|INE548A01028",
    "HINDALCO": "NSE_EQ|INE038A01020",
    "HINDPETRO": "NSE_EQ|INE094A01015",
    "HINDUNILVR": "NSE_EQ|INE030A01027",
    "HINDZINC": "NSE_EQ|INE267A01025",
    "HUDCO": "NSE_EQ|INE031A01017",
    "HYUNDAI": "NSE_EQ|INE0V6F01027",
    "ICICIBANK": "NSE_EQ|INE090A01021",
    "ICICIGI": "NSE_EQ|INE765G01017",
    "ICICIPRULI": "NSE_EQ|INE726G01019",
    "IDEA": "NSE_EQ|INE669E01016",
    "IDFCFIRSTB": "NSE_EQ|INE092T01019",
    "IEX": "NSE_EQ|INE022Q01020",
    "INDHOTEL": "NSE_EQ|INE053A01029",
    "INDIANB": "NSE_EQ|INE562A01011",
    "INDIGO": "NSE_EQ|INE646L01027",
    "INDUSINDBK": "NSE_EQ|INE095A01012",
    "INDUSTOWER": "NSE_EQ|INE121J01017",
    "INFY": "NSE_EQ|INE009A01021",
    "INOXWIND": "NSE_EQ|INE066P01011",
    "IOC": "NSE_EQ|INE242A01010",
    "IRB": "NSE_EQ|INE821I01022",
    "IREDA": "NSE_EQ|INE202E01016",
    "IRFC": "NSE_EQ|INE053F01010",
    "ITC": "NSE_EQ|INE154A01025",
    "ITI": "NSE_EQ|INE248A01017",
    "JINDALSTEL": "NSE_EQ|INE749A01030",
    "JIOFIN": "NSE_EQ|INE758E01017",
    "JSWENERGY": "NSE_EQ|INE121E01018",
    "JSWSTEEL": "NSE_EQ|INE019A01038",
    "JUBLFOOD": "NSE_EQ|INE797F01020",
    "KALYANKJIL": "NSE_EQ|INE303R01014",
    "KAYNES": "NSE_EQ|INE918Z01012",
    "KEI": "NSE_EQ|INE878B01027",
    "KFINTECH": "NSE_EQ|INE138Y01010",
    "KOTAKBANK": "NSE_EQ|INE237A01036",
    "KPITTECH": "NSE_EQ|INE04I401011",
    "LAURUSLABS": "NSE_EQ|INE947Q01028",
    "LICHSGFIN": "NSE_EQ|INE115A01026",
    "LICI": "NSE_EQ|INE0J1Y01017",
    "LODHA": "NSE_EQ|INE670K01029",
    "LT": "NSE_EQ|INE018A01030",
    "LTF": "NSE_EQ|INE498L01015",
    "LTM": "NSE_EQ|INE214T01019",
    "LUPIN": "NSE_EQ|INE326A01037",
    "M&M": "NSE_EQ|INE101A01026",
    "MAHABANK": "NSE_EQ|INE457A01014",
    "MANAPPURAM": "NSE_EQ|INE522D01027",
    "MANKIND": "NSE_EQ|INE634S01028",
    "MARICO": "NSE_EQ|INE196A01026",
    "MARUTI": "NSE_EQ|INE585B01010",
    "MAXHEALTH": "NSE_EQ|INE027H01010",
    "MAZDOCK": "NSE_EQ|INE249Z01020",
    "MCX": "NSE_EQ|INE745G01043",
    "MFSL": "NSE_EQ|INE180A01020",
    "MOTHERSON": "NSE_EQ|INE775A01035",
    "MOTILALOFS": "NSE_EQ|INE338I01027",
    "MPHASIS": "NSE_EQ|INE356A01018",
    "MUTHOOTFIN": "NSE_EQ|INE414G01012",
    "NAM-INDIA": "NSE_EQ|INE298J01013",
    "NATIONALUM": "NSE_EQ|INE139A01034",
    "NAUKRI": "NSE_EQ|INE663F01032",
    "NBCC": "NSE_EQ|INE095N01031",
    "NESTLEIND": "NSE_EQ|INE239A01024",
    "NHPC": "NSE_EQ|INE848E01016",
    "NIFTYFPI": "NSE_INDEX|Nifty FPI 150",
    "NMDC": "NSE_EQ|INE584A01023",
    "NTPC": "NSE_EQ|INE733E01010",
    "NYKAA": "NSE_EQ|INE388Y01029",
    "OBEROIRLTY": "NSE_EQ|INE093I01010",
    "OFSS": "NSE_EQ|INE881D01027",
    "OIL": "NSE_EQ|INE274J01014",
    "ONGC": "NSE_EQ|INE213A01029",
    "PAGEIND": "NSE_EQ|INE761H01022",
    "PATANJALI": "NSE_EQ|INE619A01035",
    "PAYTM": "NSE_EQ|INE982J01020",
    "PERSISTENT": "NSE_EQ|INE262H01021",
    "PETRONET": "NSE_EQ|INE347G01014",
    "PFC": "NSE_EQ|INE134E01011",
    "PGEL": "NSE_EQ|INE457L01029",
    "PHOENIXLTD": "NSE_EQ|INE211B01039",
    "PIDILITIND": "NSE_EQ|INE318A01026",
    "PIIND": "NSE_EQ|INE603J01030",
    "PNB": "NSE_EQ|INE160A01022",
    "PNBHOUSING": "NSE_EQ|INE572E01012",
    "POLICYBZR": "NSE_EQ|INE417T01026",
    "POLYCAB": "NSE_EQ|INE455K01017",
    "POWERGRID": "NSE_EQ|INE752E01010",
    "POWERINDIA": "NSE_EQ|INE07Y701011",
    "PREMIERENE": "NSE_EQ|INE0BS701011",
    "PRESTIGE": "NSE_EQ|INE811K01011",
    "RADICO": "NSE_EQ|INE944F01028",
    "RBLBANK": "NSE_EQ|INE976G01028",
    "RECLTD": "NSE_EQ|INE020B01018",
    "RELIANCE": "NSE_EQ|INE002A01018",
    "RVNL": "NSE_EQ|INE415G01027",
    "SAGILITY": "NSE_EQ|INE0W2G01015",
    "SAIL": "NSE_EQ|INE114A01011",
    "SBICARD": "NSE_EQ|INE018E01016",
    "SBILIFE": "NSE_EQ|INE123W01016",
    "SBIN": "NSE_EQ|INE062A01020",
    "SHREECEM": "NSE_EQ|INE070A01015",
    "SHRIRAMFIN": "NSE_EQ|INE721A01047",
    "SIEMENS": "NSE_EQ|INE003A01024",
    "SJVN": "NSE_EQ|INE002L01015",
    "SOLARINDS": "NSE_EQ|INE343H01029",
    "SONACOMS": "NSE_EQ|INE073K01018",
    "SRF": "NSE_EQ|INE647A01010",
    "SUNPHARMA": "NSE_EQ|INE044A01036",
    "SUPREMEIND": "NSE_EQ|INE195A01028",
    "SUZLON": "NSE_EQ|INE040H01021",
    "SWIGGY": "NSE_EQ|INE00H001014",
    "TATACONSUM": "NSE_EQ|INE192A01025",
    "TATAELXSI": "NSE_EQ|INE670A01012",
    "TATAPOWER": "NSE_EQ|INE245A01021",
    "TATASTEEL": "NSE_EQ|INE081A01020",
    "TCS": "NSE_EQ|INE467B01029",
    "TECHM": "NSE_EQ|INE669C01036",
    "TIINDIA": "NSE_EQ|INE974X01010",
    "TITAN": "NSE_EQ|INE280A01028",
    "TMPV": "NSE_EQ|INE155A01022",
    "TORNTPHARM": "NSE_EQ|INE685A01028",
    "TRENT": "NSE_EQ|INE849A01020",
    "TVSMOTOR": "NSE_EQ|INE494B01023",
    "UJJIVANSFB": "NSE_EQ|INE551W01018",
    "ULTRACEMCO": "NSE_EQ|INE481G01011",
    "UNIONBANK": "NSE_EQ|INE692A01016",
    "UNITDSPR": "NSE_EQ|INE854D01024",
    "UNOMINDA": "NSE_EQ|INE405E01023",
    "UPL": "NSE_EQ|INE628A01036",
    "VBL": "NSE_EQ|INE200M01039",
    "VEDL": "NSE_EQ|INE205A01025",
    "VMM": "NSE_EQ|INE01EA01019",
    "VOLTAS": "NSE_EQ|INE226A01021",
    "WAAREEENER": "NSE_EQ|INE377N01017",
    "WIPRO": "NSE_EQ|INE075A01022",
    "YESBANK": "NSE_EQ|INE528G01035",
    "ZYDUSLIFE": "NSE_EQ|INE010B01027",
}



def get_upstox_token() -> str:
    """Discovers Upstox API bearer token from .env or environment."""
    env_token = os.environ.get("UPSTOX_ACCESS_TOKEN", "").strip()
    if env_token:
        return env_token

    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("UPSTOX_ACCESS_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


class UpstoxDataProvider:
    """Manages fetching, caching, and chronological ordering of Upstox daily candles."""

    def __init__(self, cache_dir: Optional[str] = None):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.cache_dir = cache_dir or os.path.join(base_dir, ".data_cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.token = get_upstox_token()
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        self._in_memory_cache: Dict[str, List[Dict[str, Any]]] = {}

    def fetch_candle_data_from_api(self, instrument_key: str, from_date: str = "2020-01-01", to_date: Optional[str] = None) -> List[List[Any]]:
        """Calls Upstox v3 historical candle API and returns raw candle array."""
        target_to_date = to_date or dt.date.today().strftime("%Y-%m-%d")
        enc_key = urllib.parse.quote(instrument_key, safe="")
        url = f"{UPSTOX_HISTORICAL_V3_BASE}/{enc_key}/days/1/{target_to_date}/{from_date}"
        req = urllib.request.Request(url, headers=self.headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            candles = data.get("data", {}).get("candles", [])
            return candles

    def load_or_fetch_symbol(
        self,
        sym: str,
        instrument_key: Optional[str] = None,
        force_refresh: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Loads candles for `sym` from local cache or fetches from Upstox API.
        If force_refresh is True, attempts to fetch fresh candles from Upstox API first.
        If that fails, falls back to disk cache if available.
        Returns chronologically sorted list of dicts:
        [{date: '2020-01-01', open: 334.7, high: 335.95, low: 332.15, close: 334.45, volume: 17379320}]
        """
        if sym in self._in_memory_cache and not force_refresh:
            return self._in_memory_cache[sym]

        cache_file = os.path.join(self.cache_dir, f"{sym}.json")
        if os.path.exists(cache_file) and not force_refresh:
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    candles = json.load(f)
                    self._in_memory_cache[sym] = candles
                    return candles
            except Exception:
                pass

        # Resolve instrument key
        key = instrument_key
        if not key:
            info = TOP_50_UNIVERSE.get(sym)
            if info:
                key = info.get("key")
            elif sym in ALL_220_UNIVERSE_KEYS:
                key = ALL_220_UNIVERSE_KEYS[sym]
            else:
                key = f"NSE_EQ|{sym}"

        # Fetch from Upstox API if token is present
        if self.token:
            try:
                raw_candles = self.fetch_candle_data_from_api(key)
                if raw_candles:
                    # Upstox returns candles in reverse chronological order (newest first).
                    # We reverse them to be strictly chronological (oldest first).
                    reversed_candles = list(reversed(raw_candles))

                    formatted: List[Dict[str, Any]] = []
                    for c in reversed_candles:
                        date_str = c[0][:10]
                        formatted.append({
                            "date": date_str,
                            "open": float(c[1]),
                            "high": float(c[2]),
                            "low": float(c[3]),
                            "close": float(c[4]),
                            "volume": int(c[5]),
                            "oi": int(c[6]) if len(c) > 6 else 0,
                        })

                    # Save to disk cache
                    try:
                        with open(cache_file, "w", encoding="utf-8") as f:
                            json.dump(formatted, f)
                    except Exception:
                        pass

                    self._in_memory_cache[sym] = formatted
                    return formatted
            except Exception as e:
                # If fetch failed but cache exists, fallback to cache
                if os.path.exists(cache_file):
                    try:
                        with open(cache_file, "r", encoding="utf-8") as f:
                            candles = json.load(f)
                            self._in_memory_cache[sym] = candles
                            return candles
                    except Exception:
                        pass
                raise ValueError(f"Failed to fetch candles for '{sym}' ({key}): {e}") from e

        # If no token, check disk cache fallback
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    candles = json.load(f)
                    self._in_memory_cache[sym] = candles
                    return candles
            except Exception:
                pass

        raise ValueError(f"No candle data available for symbol '{sym}' (no token and not found in cache)")

    def preload_all_universe(self, symbols: Optional[List[str]] = None, verbose: bool = True) -> Dict[str, int]:
        """Preloads all symbols in the universe and returns count of loaded candles."""
        targets = symbols or list(TOP_50_UNIVERSE.keys())
        results = {}
        if verbose:
            print(f"Preloading historical candles from Upstox API for {len(targets)} symbols...")
        for idx, sym in enumerate(targets, 1):
            try:
                t0 = time.time()
                data = self.load_or_fetch_symbol(sym)
                dt_sec = time.time() - t0
                results[sym] = len(data)
                if verbose:
                    cached_flag = "CACHE" if dt_sec < 0.05 else "UPSTOX API"
                    print(f"  [{idx:02d}/{len(targets):02d}] {sym:<12}: {len(data)} candles ({cached_flag}, {dt_sec:.2f}s)")
            except Exception as e:
                print(f"  [{idx:02d}/{len(targets):02d}] {sym:<12}: FAILED ({e})")
                results[sym] = 0
        return results
