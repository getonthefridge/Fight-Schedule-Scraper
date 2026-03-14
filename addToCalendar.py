import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

import EventKit
import Foundation

from ufcScraper import Fight, fetch_event_page, fetch_numbered_event_page


def _get_authorized_store() -> EventKit.EKEventStore:
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
            "Go to System Settings > Privacy & Security > Calendars and enable PyCharm."
        )
    return store


def _to_nsdate(dt: datetime):
    epoch = datetime(2001, 1, 1, tzinfo=timezone.utc)
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
    if not fights:
        print(f"  [SKIP] No fights found for {event_url}")
        return []

    store = _get_authorized_store()
    cal = _get_calendar(store, calendar_name)

    sections: dict[str, list[Fight]] = defaultdict(list)
    for fight in fights:
        sections[fight.card_section].append(fight)

    main_event = fights[0]
    base_title = f"UFC Fight Night: {main_event.red_corner.name} vs {main_event.blue_corner.name}"

    created = []
    for section_name, section_fights in sections.items():
        first = section_fights[0]

        if first.broadcast_start_datetime is None:
            print(f"  [SKIP] No broadcast time available for '{section_name}'")
            continue

        start_dt = first.broadcast_start_datetime
        end_dt = start_dt + timedelta(hours=assumed_duration_hours)

        unique_tag = f"UFC-EVENT-{event_url.split('/')[-1]}-{section_name.replace(' ', '-')}"

        notes_lines = [f"URL: {event_url}", f"ID: {unique_tag}\n"]
        for fight in section_fights:
            rank_r = f" {fight.red_corner.rank}" if fight.red_corner.rank else ""
            rank_b = f" {fight.blue_corner.rank}" if fight.blue_corner.rank else ""
            notes_lines.append(
                f"{fight.weight_class}\n"
                f"  Red{rank_r}:  {fight.red_corner.name} ({fight.red_corner.country})\n"
                f"  Blue{rank_b}: {fight.blue_corner.name} ({fight.blue_corner.country})\n"
            )
        if first.broadcaster:
            notes_lines.append(f"\nBroadcast: {first.broadcaster}")
            if first.broadcaster_url:
                notes_lines.append(f"  {first.broadcaster_url}")

        notes = "\n".join(notes_lines)
        notes += f"\nLast updated: {datetime.now().strftime('%A, %B %d, %Y at %I:%M %p')}"
        title = f"{base_title}  |  {section_name}"

        # Search for an existing event with this unique tag
        existing_event = None
        search_start = _to_nsdate(start_dt - timedelta(days=7))
        search_end = _to_nsdate(start_dt + timedelta(days=7))
        predicate = store.predicateForEventsWithStartDate_endDate_calendars_(
            search_start, search_end, None
        )
        all_events = store.eventsMatchingPredicate_(predicate)
        if all_events:
            for e in all_events:
                if e.notes() and unique_tag in e.notes():
                    existing_event = e
                    break

        ek_event = existing_event if existing_event else EventKit.EKEvent.eventWithEventStore_(store)
        ek_event.setTitle_(title)
        ek_event.setNotes_(notes)
        ek_event.setStartDate_(_to_nsdate(start_dt))
        ek_event.setEndDate_(_to_nsdate(end_dt))
        ek_event.setCalendar_(cal)

        if not existing_event:
            alarm = EventKit.EKAlarm.alarmWithRelativeOffset_(-alert_minutes * 60)
            ek_event.addAlarm_(alarm)

        success, error = store.saveEvent_span_commit_error_(
            ek_event, EventKit.EKSpanThisEvent, True, None
        )
        if success:
            action = "UPDATED" if existing_event else "ADDED"
            print(f"  [{action}] {title}  ({start_dt.strftime('%b %d, %Y  %I:%M %p')})")
            created.append(ek_event.eventIdentifier())
        else:
            print(f"  [ERROR] Failed to save '{title}': {error}")

    return created


def parse(event_url: str, numberedEvent: bool = False):
    if numberedEvent:
        fights = fetch_numbered_event_page(event_url)
    else:
        fights = fetch_event_page(event_url)

    print(f"\nProcessing: {event_url}")
    print(f"  {len(fights)} fight(s) found")
    create_ufc_event_in_calendar(
        fights=fights,
        event_url=event_url,
        calendar_name=None,
        alert_minutes=30,
        assumed_duration_hours=3,
    )
