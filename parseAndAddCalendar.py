import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import EventKit
import Foundation
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
    broadcast_start_datetime: Optional[datetime]  # NEW — parsed from timestamp
    broadcaster: Optional[str]
    broadcaster_url: Optional[str]


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
        if raw_country:  # skip empty strings
            try:
                converted = coco.convert(names=raw_country, to='ISO3')
                # coco returns "not found" string on failure — keep original if so
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

    # Fix URL — only prepend base if it's a relative path
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
        broadcast_start_datetime=None,  # filled in parse_event_page
        broadcaster=None,
        broadcaster_url=None,
    )


def parse_broadcast_info(section_soup):
    # Try both the section-level and page-level broadcaster time div
    time_div = (
            section_soup.find(class_="c-event-fight-card-broadcaster__time tz-change-inner") or
            section_soup.find(class_="c-event-fight-card-broadcaster__time")
    )
    broadcaster_anchor = section_soup.find(class_="broadcaster-cta")
    timestamp = time_div.get("data-timestamp") if time_div else None

    # Some events store it as a data attribute on a child span instead
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

    # Fix URL concatenation — don't prepend base if already absolute
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


def fetch_event_page(url):
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://www.ufc.com/events",
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }
    session = requests.Session()
    session.headers.update(HEADERS)
    response = session.get(url)
    return parse_event_page(response.text)


# ── Calendar helpers ──────────────────────────────────────────────────────────

def _get_authorized_store() -> EventKit.EKEventStore:
    """Return an authorized EKEventStore, prompting for permission if needed."""
    store = EventKit.EKEventStore.alloc().init()
    granted = False
    done = threading.Event()

    def handler(success, error):
        nonlocal granted
        granted = success
        done.set()

    store.requestAccessToEntityType_completion_(EventKit.EKEntityTypeEvent, handler)
    done.wait(timeout=30)

    if not granted:
        raise PermissionError(
            "Calendar access denied. "
            "Go to System Settings → Privacy & Security → Calendars and enable PyCharm."
        )
    return store


def _to_nsdate(dt: datetime):
    """Convert a Python datetime to NSDate."""
    epoch = datetime(2001, 1, 1, tzinfo=timezone.utc)  # make epoch timezone-aware
    seconds = (dt - epoch).total_seconds()
    return Foundation.NSDate.dateWithTimeIntervalSinceReferenceDate_(seconds)


def _get_calendar(store, name: Optional[str]):
    if name is None:
        return store.defaultCalendarForNewEvents()
    for cal in store.calendarsForEntityType_(EventKit.EKEntityTypeEvent):
        if cal.title() == name:
            return cal
    raise ValueError(f"Calendar '{name}' not found.")


def create_ufc_event_in_calendar(
        fights: list[Fight],
        event_url: str,
        calendar_name: str = None,
        alert_minutes: int = 15,
        assumed_duration_hours: int = 3,
):
    store = _get_authorized_store()
    cal = _get_calendar(store, calendar_name)

    from collections import defaultdict
    sections: dict[str, list[Fight]] = defaultdict(list)
    for fight in fights:
        sections[fight.card_section].append(fight)

    main_event = fights[0]
    base_title = f"UFC Fight Night: {main_event.red_corner.name} vs {main_event.blue_corner.name}"

    created = []
    for section_name, section_fights in sections.items():
        first = section_fights[0]

        if first.broadcast_start_datetime is None:
            print(f"⚠️  No broadcast time found for '{section_name}' — skipping.")
            continue

        start_dt = first.broadcast_start_datetime
        end_dt = start_dt + timedelta(hours=assumed_duration_hours)

        # Build a unique identifier for this card section
        unique_tag = f"UFC-EVENT-{event_url.split('/')[-1]}-{section_name.replace(' ', '-')}"

        # Build notes
        notes_lines = [f"🔗 {event_url}", f"[{unique_tag}]\n"]
        for fight in section_fights:
            rank_r = f" {fight.red_corner.rank}" if fight.red_corner.rank else ""
            rank_b = f" {fight.blue_corner.rank}" if fight.blue_corner.rank else ""
            notes_lines.append(
                f"{fight.weight_class}\n"
                f"  🔴{rank_r} {fight.red_corner.name} ({fight.red_corner.country})\n"
                f"  🔵{rank_b} {fight.blue_corner.name} ({fight.blue_corner.country})\n"
            )
        if first.broadcaster:
            notes_lines.append(f"\n📺 {first.broadcaster}")
            if first.broadcaster_url:
                notes_lines.append(f"   {first.broadcaster_url}")

        notes = "\n".join(notes_lines)
        title = f"{base_title}  |  {section_name}"

        # ── Search for an existing event with this unique tag ──
        existing_event = None
        search_start = _to_nsdate(start_dt - timedelta(days=7))
        search_end = _to_nsdate(start_dt + timedelta(days=7))
        predicate = store.predicateForEventsWithStartDate_endDate_calendars_(
            search_start, search_end, None  # None = search all calendars
        )
        all_events = store.eventsMatchingPredicate_(predicate)
        if all_events:
            for e in all_events:
                if e.notes() and unique_tag in e.notes():
                    existing_event = e
                    break

        # ── Update existing or create new ──
        ek_event = existing_event if existing_event else EventKit.EKEvent.eventWithEventStore_(store)
        ek_event.setTitle_(title)
        ek_event.setNotes_(notes)
        ek_event.setStartDate_(_to_nsdate(start_dt))
        ek_event.setEndDate_(_to_nsdate(end_dt))
        ek_event.setCalendar_(cal)

        # Only add alert if this is a new event (avoid duplicating alarms on update)
        if not existing_event:
            alarm = EventKit.EKAlarm.alarmWithRelativeOffset_(-alert_minutes * 60)
            ek_event.addAlarm_(alarm)

        success, error = store.saveEvent_span_commit_error_(
            ek_event, EventKit.EKSpanThisEvent, True, None
        )
        if success:
            action = "Updated" if existing_event else "Added"
            print(f"✅ {action}: {title}  ({start_dt.strftime('%b %d %I:%M %p')})")
            created.append(ek_event.eventIdentifier())
        else:
            print(f"❌ Failed to save '{title}': {error}")

    return created


def fetch_numbered_event_page(url):
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://www.ufc.com/events",
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }
    session = requests.Session()
    session.headers.update(HEADERS)
    response = session.get(url)
    soup = BeautifulSoup(response.text, "html.parser")

    # Try section-level first, then fall back to searching the whole page
    timestamp, start_datetime, broadcaster, broadcaster_url = parse_broadcast_info(soup)

    if not start_datetime:
        # Numbered events sometimes nest the timestamp deeper — search all matching divs
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


def parse(EVENT_URL, numberedEvent=False):
    if numberedEvent:
        fights = fetch_numbered_event_page(EVENT_URL)
    else:
        fights = fetch_event_page(EVENT_URL)

    print(f"\nAdding to Apple Calendar: {EVENT_URL}\n")
    create_ufc_event_in_calendar(
        fights=fights,
        event_url=EVENT_URL,
        calendar_name=None,
        alert_minutes=30,
        assumed_duration_hours=3,
    )

# parse()
