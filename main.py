import re
import requests
from bs4 import BeautifulSoup
from parseAndAddCalendar import parse


def get_all_event_links():
    BASE_URL = "https://www.ufc.com/events"
    response = requests.get(BASE_URL)
    soup = BeautifulSoup(response.content, "html.parser")

    links = set()
    for a in soup.find('details', id='events-list-upcoming').find_all('h3', class_="c-card-event--result__headline"):
        href = a.find('a')['href']

        if re.search(r'/ufc-\d{3}', href):
            try:
                parse(BASE_URL[:-len('/events')] + href, numberedEvent=True)
            except Exception as e:
                print(f"  [ERROR] Could not parse numbered event {href}: {e}")
        else:
            links.add(href)

    links = [BASE_URL[:-len('/events')] + link for link in sorted(links)]

    for link in links:
        try:
            parse(link)
        except Exception as e:
            print(f"  [ERROR] Could not parse {link}: {e}")


get_all_event_links()

# import re
#
# import requests
# from bs4 import BeautifulSoup
#
# from parseAndAddCalendar import parse
#
#
# def get_all_event_links():
#     BASE_URL = "https://www.ufc.com/events"
#     response = requests.get(BASE_URL)
#     soup = BeautifulSoup(response.content, "html.parser")
#
#     links = set()
#     for a in soup.find('details', id='events-list-upcoming').find_all('h3', class_="c-card-event--result__headline"):
#         href = a.find('a')['href']
#
#         if re.search(r'/ufc-\d{3}', href):
#             try:
#                 parse(BASE_URL[:-len('/events')] + href, numberedEvent=True)
#             except Exception as e:
#                 print(f"❌ Error parsing numbered event {href}: {e}")
#         else:
#             links.add(href)
#
#     links = [BASE_URL[:-len('/events')] + link for link in sorted(links)]
#
#     for link in links:
#         try:
#             parse(link)
#         except Exception as e:
#             print(f"❌ Error parsing {link}: {e}")
#
#
# get_all_event_links()
