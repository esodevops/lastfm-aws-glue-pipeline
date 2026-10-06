"""Beginner-friendly Last.fm ETL for local development and Glue Python shell."""
import argparse
import csv
import io
import json
import os
import time
import ssl
import certifi
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

COLUMNS = ["track_name", "artist_name", "listeners", "playcount", "track_url", "extracted_at"]


def fetch_page(api_key, page, limit):
    parameters = {
        "method": "chart.gettoptracks",
        "api_key": api_key,
        "format": "json",
        "page": page,
        "limit": limit,
    }

    base_url = "https://ws.audioscrobbler.com/2.0/"
    request_url = base_url + "?" + urlencode(parameters)

    for attempt in range(3):
        try:
            ssl_context = ssl.create_default_context(cafile=certifi.where())

            with urlopen(
                request_url,
                timeout=30,
                context=ssl_context
            ) as response:

                response_text = response.read().decode("utf-8")
                payload = json.loads(response_text)

            # Last.fm may return an error inside a successful HTTP response.
            if "error" in payload:
                error_code = int(payload["error"])

                # Retry temporary API failures and rate limits.
                if error_code in (8, 11, 16, 29) and attempt < 2:
                    print("Temporary Last.fm error. Retrying...")
                    time.sleep(2 ** (attempt + 1))
                    continue

                raise RuntimeError(f"Last.fm API failed with error code {error_code}")

            if not isinstance(payload.get("tracks"), dict):
                raise RuntimeError("Last.fm returned an unexpected response.")

            return payload

        # HTTPError must come before URLError because it is a subclass.
        except HTTPError as error:
            if (error.code == 429 or error.code >= 500) and attempt < 2:
                print(f"HTTP error {error.code}. Retrying...")
                time.sleep(2 ** (attempt + 1))
                continue

            raise RuntimeError(f"Last.fm HTTP request failed: {error.code}") from None

        except URLError as error:
            if attempt < 2:
                print("Connection failed. Retrying...")
                time.sleep(2 ** (attempt + 1))
                continue

            raise RuntimeError(f"Cannot connect to Last.fm: {error.reason}") from None

        except TimeoutError:
            if attempt < 2:
                print("Request timed out. Retrying...")
                time.sleep(2 ** (attempt + 1))
                continue

            raise RuntimeError(
                "Last.fm request timed out after three attempts."
            ) from None

    raise RuntimeError("Last.fm retries exhausted.")


def count_or_none(value):
    try:
        number = int(str(value))
        return number if number >= 0 else None
    except (ValueError, TypeError):
        return None


def clean_tracks(tracks, extracted_at):
    rows = []
    seen = set()
    for track in tracks:
        if not isinstance(track, dict):
            continue
        artist = track.get("artist") or {}
        name = str(track.get("name") or "").strip()
        artist_name = str(artist.get("name") or "").strip()
        if not name or not artist_name:
            continue
        identity = (name, artist_name)
        if identity in seen:
            continue
        seen.add(identity)
        rows.append({
            "track_name": name, "artist_name": artist_name,
            "listeners": count_or_none(track.get("listeners")),
            "playcount": count_or_none(track.get("playcount")),
            "track_url": track.get("url") or "",
            "extracted_at": extracted_at,
        })
    # Missing counts sort after valid counts, including zero.
    rows.sort(key=lambda row: row["playcount"] if row["playcount"] is not None else -1,
              reverse=True)
    return rows


def make_csv(rows):
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def save_file(key, content, content_type, bucket, output_dir, s3=None):
    if bucket:
        s3.put_object(Bucket=bucket, Key=key, Body=content, ContentType=content_type)
        print(f"Saved s3://{bucket}/{key}")
    else:
        destination = Path(output_dir) / key
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        print(f"Saved {destination}")


def main():
    parser = argparse.ArgumentParser(description="Last.fm chart to local files or S3")
    parser.add_argument("--LASTFM_API_KEY", default=os.getenv("LASTFM_API_KEY"))
    parser.add_argument("--S3_BUCKET_NAME", default=os.getenv("S3_BUCKET_NAME"))
    parser.add_argument("--LASTFM_SECRET_ID", default=os.getenv("LASTFM_SECRET_ID"))
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--output-dir", default="data")
    args, _ = parser.parse_known_args()  # Glue supplies additional arguments.
    if args.pages < 1 or not 1 <= args.limit <= 50:
        parser.error("Use --pages >= 1 and --limit between 1 and 50")
    if args.LASTFM_SECRET_ID:
        import boto3
        secret = boto3.client("secretsmanager").get_secret_value(SecretId=args.LASTFM_SECRET_ID)
        args.LASTFM_API_KEY = json.loads(secret["SecretString"])["LASTFM_API_KEY"]
    if not args.LASTFM_API_KEY:
        parser.error("Provide LASTFM_API_KEY or LASTFM_SECRET_ID")
    s3 = None
    if args.S3_BUCKET_NAME:
        import boto3
        s3 = boto3.client("s3")
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%d_%H%M%S_%f")
    tracks = []
    for page_number in range(1, args.pages + 1):
        payload = fetch_page(args.LASTFM_API_KEY, page_number, args.limit)
        raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        key = f"raw-data/{run_id}/page_{page_number}.json"
        save_file(key, raw, "application/json; charset=utf-8", args.S3_BUCKET_NAME, args.output_dir, s3)
        page = payload["tracks"]
        items = page.get("track", [])
        if isinstance(items, dict):
            items = [items]
        tracks.extend(items)
        total_pages = int(page.get("@attr", {}).get("totalPages", args.pages))
        if not items or page_number >= total_pages:
            break
        time.sleep(1)
    rows = clean_tracks(tracks, now.isoformat())
    save_file(f"transformed-data/lastfm_clean_{run_id}.csv", make_csv(rows),
              "text/csv; charset=utf-8", args.S3_BUCKET_NAME, args.output_dir, s3)
    print(f"Complete: {len(tracks)} extracted, {len(rows)} cleaned")


if __name__ == "__main__":
    main()
