import re

import requests
from bs4 import BeautifulSoup

from parseAndAddCalendar import parse


def main():
    url = "https://www.ufc.com/events"
    response = requests.get(url)
    soup = BeautifulSoup(response.content, "html.parser")
    links = [link.get('href') for link in soup.find('div', class_='l-container').find_all("a")]
    goodLinks = []
    # if '/event/' in link and 'https' not in link
    for link in links:
        if re.search(r'/ufc-\d{3}', link):
            parse(f'https://www.ufc.com{link}', numberedEvent=True)
            # goodLinks.append(link)
        if '/event/' in link:
            if 'https' not in link:
                goodLinks.append(link)

    links = list(set([url[:-7] + link for link in links]))

    for link in links:
        try:
            status = requests.get(link).status_code
            if status == 200:
                parse(link)
            else:
                print(link)
        except Exception as e:
            print(link, e)


if __name__ == "__main__":
    main()
