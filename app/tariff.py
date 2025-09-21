# app/tariff.py
import datetime
import requests
import logging

try:
    # python 3.9+
    from zoneinfo import ZoneInfo
except ImportError:
    # python 3.6-3.8
    from backports.zoneinfo import ZoneInfo

_LOGGER = logging.getLogger("reader")

class Tariff:

    BASE_URL = "https://www.cezdistribuce.cz/webpublic/distHdo/adam/containers/"
    CEZ_TIMEZONE = ZoneInfo("Europe/Prague")

    region = "morava"
    code = "a1b6dp7"

    responseData = {}

    def __init__(self):
        self.responseData = self.get_from_web()


    def getCorrectRegionName(self, region):
        "validate region"
        region = region.lower()
        for x in ["zapad", "sever", "stred", "vychod", "morava"]:
            if x in region:
                return x


    def getRequestUrl(self, region, code):
        "create request URI"
        region = self.getCorrectRegionName(region)
        return self.BASE_URL + region + "?&code=" + code.upper()


    def timeInRange(self, start, end, x):
        "is time in range"
        if start <= end:
            return start <= x <= end
        else:
            return start <= x or x <= end


    def parseTime(self, date_time_str):
        "parse time from source data"
        if not date_time_str:
            return datetime.time(0, 0)
        else:
            return datetime.datetime.strptime(date_time_str, "%H:%M").time()


    def isHdo(self, jsonCalendar):
        """
        Find out if the HDO is enabled for the current timestamp

        :param jsonCalendar: JSON with calendar schedule from CEZ
        :param daytime: relevant time in "Europe/Prague" timezone to check if HDO is on or not
        :return: bool
        """
        daytime = datetime.datetime.now(tz=self.CEZ_TIMEZONE)
        # select Mon-Fri schedule or Sat-Sun schedule according to current date
        if daytime.weekday() < 5:
            dayCalendar = next(
                (x for x in jsonCalendar if x["PLATNOST"] == "Po - Pá" or x["PLATNOST"] == "Po - Ne"), None
            )
        else:
            dayCalendar = next(
                (x for x in jsonCalendar if x["PLATNOST"] == "So - Ne" or x["PLATNOST"] == "Po - Ne"), None
            )

        checkedTime = daytime.time()
        hdo = False

        # iterate over scheduled times in calendar schedule
        for i in range(1, 11):
            startTime = self.parseTime(dayCalendar["CAS_ZAP_" + str(i)])
            endTime = self.parseTime(dayCalendar["CAS_VYP_" + str(i)])
            hdo = hdo or self.timeInRange(start=startTime, end=endTime, x=checkedTime)
        return hdo

    
    def get_from_web(self):
        url = self.getRequestUrl(self.region, self.code)
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            responseJson = response.json()
            _LOGGER.debug("Region %s read data from web: %s", responseJson)
            return responseJson["data"]
        else:
            _LOGGER.warning("Error getting data from CEZ. Status code: %s", 
                            self.code, response.status_code)

    def is_t2(self):
        return self.isHdo(self.responseData)
       