# Data import API

CSV import:

```text
POST /api/v1/data/imports/csv
```

Multipart form fields include:

- `file`
- `symbol`
- `instrument_name`
- `asset_class`
- `exchange`
- `currency`
- `timezone`
- `timeframe`
- `source_name`
- `timeframe_seconds`
- `dry_run`

Inspection:

```text
GET /api/v1/data/imports
GET /api/v1/data/imports/{import_id}
GET /api/v1/data/imports/{import_id}/issues
```

The API returns summaries and paginated issue records. It does not expose local filesystem paths.

