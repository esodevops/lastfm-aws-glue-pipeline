# Last.fm data pipeline

A beginner-friendly VS Code project that extracts Last.fm top-chart tracks, stores each original API response, removes incomplete and duplicate records, converts counts to numbers, and writes a cleaned CSV. Runs locally or as an AWS Glue Python shell job. Uses standard Python libraries for transformation and boto3 for AWS.

## Install

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

On Windows activate with `.venv\Scripts\Activate.ps1` and select `.venv\Scripts\python.exe` using **Python: Select Interpreter**.

Create an API key at https://www.last.fm/api/account/create . Edit `.env` with your key. Leave the bucket blank to save locally. Press F5 and choose **Run Last.fm pipeline**. The debugger reads `.env`; terminal Python does not read it automatically.

For a terminal run on macOS/Linux:

```sh
read -s LASTFM_API_KEY
export LASTFM_API_KEY
python src/lastfm_pipeline.py --pages 1 --limit 50
```

Enter the key after the `read` command. For terminal S3 output, also set `S3_BUCKET_NAME` and configure AWS credentials, for example through an existing AWS profile. Never put AWS access keys in the script.

## Output

- `data/raw-data/<UTC run ID>/page_1.json`: original response, before cleaning.
- `data/transformed-data/lastfm_clean_<UTC run ID>.csv`: cleaned tracks.

When a bucket is configured the same keys are written into S3. Each run is a new snapshot. Across runs tracks can recur; this is not an incremental pipeline. Raw pages remain available even if a later page fails. Only a fully extracted run writes cleaned output.

CSV columns: track_name, artist_name, listeners, playcount, track_url, extracted_at. Counts are API-provided values; extraction time is not a release date. The chart has no release-year filter. Sorting by playcount is the pipeline's chosen ordering, not preserved chart rank. Missing counts remain empty. Deduplication uses exact track and artist names because MusicBrainz IDs can be missing.

## AWS Glue setup

1. Create an S3 bucket and upload `src/lastfm_pipeline.py` to an S3 scripts location.
2. Create a Glue **Python shell** job using **Python 3.9**. Enable common analytics libraries (includes boto3). This is a small-data Python job, not a Spark job.
3. Select the script and a Glue IAM execution role. Give that role script-read access, logging permissions, and output-write access. `iam-policy.example.json` is supplemental output/secret access, not a complete Glue role or trust policy. Replace every placeholder. Customer-managed KMS encryption may need additional key permissions.
4. Recommended: create a Secrets Manager secret named `lastfm/api` containing JSON `{"LASTFM_API_KEY":"your-key"}`. This stores the API key, not Last.fm's API secret.
5. Add the parameters shown in `glue-job-parameters.json`, replacing the bucket. Alternatively omit `--LASTFM_SECRET_ID` and supply `--LASTFM_API_KEY`; avoid sharing that value in exported job configuration.
6. Ensure the job can reach Last.fm over HTTPS. A private VPC connection needs appropriate outbound access, typically NAT, plus access to AWS services.
7. Run the job and inspect its logs and S3 output. Unhandled errors mark the job failed. Retries cover temporary API/network failures; invalid credentials fail immediately.

No Last.fm API secret is required for chart.getTopTracks. Schedule runs using a Glue trigger after validating a manual run. This project does not deploy resources automatically or create a Data Catalog table. To query CSV snapshots with Athena, configure a crawler on the transformed prefix and account for repeated snapshots.

## Test without accounts

```sh
python -m unittest discover -s tests -v
```

Tests cover cleaning, missing counts, CSV quoting, empty results, and API errors using mocks. Live Last.fm and AWS execution require your credentials and resources.
