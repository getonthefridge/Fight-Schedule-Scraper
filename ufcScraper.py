from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import country_converter as coco
import requests
from bs4 import BeautifulSoup


@dataclass
class Fighter:
    name: str
    url: str
    country: str
    rank: Optional[str]
    image_url: str
    outcome: Optional[str]


@dataclass
class Fight:
    fight_id: str
    status: str
    card_section: str
    card_order: int
    weight_class: str
    red_corner: Fighter
    blue_corner: Fighter
    result_round: Optional[str]
    result_time: Optional[str]
    result_method: Optional[str]
    broadcast_time_timestamp: Optional[str]
    broadcast_start_datetime: Optional[datetime]
    broadcaster: Optional[str]
    broadcaster_url: Optional[str]


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.ufc.com/events",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}


def get_fighter_name(corner_div):
    given = corner_div.find(class_="c-listing-fight__corner-given-name")
    family = corner_div.find(class_="c-listing-fight__corner-family-name")
    if given and family:
        return f"{given.get_text(strip=True)} {family.get_text(strip=True)}"
    anchor = corner_div.find("a")
    if anchor:
        return anchor.get_text(strip=True)
    return "Unknown"


def parse_fighter(corner_div, rank_div, country_div, image_div):
    anchor = corner_div.find("a")
    url = anchor["href"] if anchor else None
    rank = None
    if rank_div:
        rank_span = rank_div.find("span")
        if rank_span:
            rank = rank_span.get_text(strip=True)
    country = ""

    country_text_div = country_div.find(class_="c-listing-fight__country-text")
    if country_text_div:
        raw_country = country_text_div.get_text(strip=True)
        if raw_country:
            UK_REGIONS = {"Scotland", "Wales", "England", "Northern Ireland"}
            if raw_country in UK_REGIONS:
                country = "GBR"
            else:
                try:
                    converted = coco.convert(names=raw_country, to='ISO3')
                    country = converted if converted != "not found" else raw_country
                except Exception:
                    country = raw_country

    image_url = ""
    img = image_div.find("img") if image_div else None
    if img:
        image_url = img.get("src", "")
        if image_url.startswith("/") and not image_url.startswith("//"):
            image_url = "https://www.ufc.com" + image_url

    outcome = None
    outcome_div = corner_div.find(class_="c-listing-fight__outcome")
    if outcome_div:
        outcome = outcome_div.get_text(strip=True) or None

    if url and url.startswith("/"):
        url = "https://www.ufc.com" + url

    return Fighter(
        name=get_fighter_name(corner_div),
        url=url,
        country=country,
        rank=rank,
        image_url=image_url,
        outcome=outcome,
    )


def parse_fight(item, card_section):
    listing = item.find(class_="c-listing-fight")
    fight_id = listing.get("data-fmid")
    status = listing.get("data-status")
    card_order = int(item.get("data-order", 0))
    weight_class_div = listing.find(class_="c-listing-fight__class--desktop")
    weight_class = ""
    if weight_class_div:
        wc_text = weight_class_div.find(class_="c-listing-fight__class-text")
        weight_class = wc_text.get_text(strip=True) if wc_text else ""
    red_corner_div = listing.find(class_="c-listing-fight__corner-name--red")
    blue_corner_div = listing.find(class_="c-listing-fight__corner-name--blue")
    rank_row = listing.find(class_="c-listing-fight__ranks-row")
    ranks = rank_row.find_all(class_="c-listing-fight__corner-rank") if rank_row else []
    red_rank_div = ranks[0] if len(ranks) > 0 else None
    blue_rank_div = ranks[1] if len(ranks) > 1 else None
    red_country_div = listing.find(class_="c-listing-fight__country--red")
    blue_country_div = listing.find(class_="c-listing-fight__country--blue")
    red_image_div = listing.find(class_="c-listing-fight__corner-image--red")
    blue_image_div = listing.find(class_="c-listing-fight__corner-image--blue")
    red_fighter = parse_fighter(red_corner_div, red_rank_div, red_country_div, red_image_div)
    blue_fighter = parse_fighter(blue_corner_div, blue_rank_div, blue_country_div, blue_image_div)
    results_div = listing.find(class_="c-listing-fight__results--desktop")
    result_round = result_time = result_method = None
    if results_div:
        result_round = results_div.find(class_="round").get_text(strip=True) or None
        result_time = results_div.find(class_="time").get_text(strip=True) or None
        result_method = results_div.find(class_="method").get_text(strip=True) or None
    return Fight(
        fight_id=fight_id,
        status=status,
        card_section=card_section,
        card_order=card_order,
        weight_class=weight_class,
        red_corner=red_fighter,
        blue_corner=blue_fighter,
        result_round=result_round,
        result_time=result_time,
        result_method=result_method,
        broadcast_time_timestamp=None,
        broadcast_start_datetime=None,
        broadcaster=None,
        broadcaster_url=None,
    )


def parse_broadcast_info(section_soup):
    time_div = (
            section_soup.find(class_="c-event-fight-card-broadcaster__time tz-change-inner") or
            section_soup.find(class_="c-event-fight-card-broadcaster__time")
    )
    broadcaster_anchor = section_soup.find(class_="broadcaster-cta")
    timestamp = time_div.get("data-timestamp") if time_div else None

    if not timestamp and time_div:
        child = time_div.find(attrs={"data-timestamp": True})
        if child:
            timestamp = child.get("data-timestamp")

    start_datetime = None
    if timestamp and timestamp.strip():
        try:
            utc_dt = datetime.fromtimestamp(int(timestamp.strip()), tz=timezone.utc)
            start_datetime = utc_dt.astimezone()
        except (ValueError, TypeError):
            pass

    broadcaster = broadcaster_anchor.get_text(strip=True) if broadcaster_anchor else None
    broadcaster_url = broadcaster_anchor.get("href") if broadcaster_anchor else None

    if broadcaster_url and not broadcaster_url.startswith("http"):
        broadcaster_url = "https://www.ufc.com" + broadcaster_url

    return timestamp, start_datetime, broadcaster, broadcaster_url


def parse_event_page(html):
    soup = BeautifulSoup(html, "html.parser")
    fights = []
    sections = {
        "main-card": "Main Card",
        "prelims-card": "Prelims",
        "early-prelims": "Early Prelims",
    }
    for section_id, section_name in sections.items():
        section = soup.find(id=section_id)
        if not section:
            continue
        timestamp, start_datetime, broadcaster, broadcaster_url = parse_broadcast_info(section)
        for item in section.find_all(class_="l-listing__item"):
            fight = parse_fight(item, section_name)
            fight.broadcast_time_timestamp = timestamp
            fight.broadcast_start_datetime = start_datetime
            fight.broadcaster = broadcaster
            fight.broadcaster_url = broadcaster_url
            fights.append(fight)
    section_order = {"Main Card": 0, "Prelims": 1, "Early Prelims": 2}
    fights.sort(key=lambda f: (section_order[f.card_section], f.card_order))
    return fights


def _parse_flat_fight_list(soup):
    """Parse fight cards that have no section divs — a single flat list of fights."""
    timestamp, start_datetime, broadcaster, broadcaster_url = parse_broadcast_info(soup)

    if not start_datetime:
        for div in soup.find_all(attrs={"data-timestamp": True}):
            ts = div.get("data-timestamp", "").strip()
            if ts:
                try:
                    utc_dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
                    start_datetime = utc_dt.astimezone()
                    timestamp = ts
                    break
                except (ValueError, TypeError):
                    continue

    fights = []
    for item in soup.find_all(class_="l-listing__item"):
        if not item.find(class_="c-listing-fight"):
            continue
        fight = parse_fight(item, card_section="Main Card")
        fight.broadcast_time_timestamp = timestamp
        fight.broadcast_start_datetime = start_datetime
        fight.broadcaster = broadcaster
        fight.broadcaster_url = broadcaster_url
        fights.append(fight)

    fights.sort(key=lambda f: f.card_order)
    return fights


def fetch_event_page(url):
    session = requests.Session()
    session.headers.update(HEADERS)
    response = session.get(url)
    html = response.text
    soup = BeautifulSoup(html, "html.parser")

    has_sections = any(
        soup.find(id=section_id)
        for section_id in ["main-card", "prelims-card", "early-prelims"]
    )

    if has_sections:
        return parse_event_page(html)

    print(f"  [INFO] No card sections found, trying flat parse")
    return _parse_flat_fight_list(soup)


def fetch_numbered_event_page(url):
    session = requests.Session()
    session.headers.update(HEADERS)
    response = session.get(url)
    soup = BeautifulSoup(response.text, "html.parser")
    return _parse_flat_fight_list(soup)
