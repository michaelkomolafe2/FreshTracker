# Expiry alert job

The scheduler runs as the dedicated `expiry-alerts` Compose service rather
than inside a Gunicorn worker. This ensures there is one scheduler even though
the API uses multiple worker processes.

The nightly job claims active items expiring on or before the configured local
date plus three days. Claiming is a single
`UPDATE ... WHERE alert_sent = false RETURNING ...` statement, so concurrent
job invocations cannot email the same item twice. The claim is committed before
mail is sent.

## Configuration

Delivery is a dry run by default. Dry runs select and log eligible item IDs
without sending mail or changing `alert_sent`. Set both of the following to
enable SMTP delivery and atomic claims:

- `MAIL_ENABLED=true`
- `MAIL_SERVER` and `MAIL_DEFAULT_SENDER`

Optional SMTP settings are `MAIL_PORT` (default `587`), `MAIL_USE_TLS`
(default `true`), `MAIL_USE_SSL` (default `false`), `MAIL_USERNAME`, and
`MAIL_PASSWORD`.

The schedule defaults to 07:00 UTC. Configure it with
`EXPIRY_ALERT_TIMEZONE`, `EXPIRY_ALERT_HOUR`, and `EXPIRY_ALERT_MINUTE`.
The scheduler also runs once when its process starts so a restart does not
silently skip that day's alerts.
The `flask --app app:app send-expiry-alerts` command provides a one-shot
operational run.

## Delivery guarantee

This design provides at-most-once delivery. SMTP and the database cannot share
an atomic transaction, so a process failure after the claim commits but before
SMTP accepts a message can lose that alert. Reliable retry requires a
transactional outbox and a delivery worker; avoiding duplicate mail during
ambiguous SMTP failures additionally requires provider-supported idempotency.

## Inventory completion transaction

`PATCH /items/<id>` accepts only `used` or `wasted`. It locks the owning active
inventory row, updates its status, and inserts the matching `waste_logs` record
inside one explicit SQLAlchemy transaction. A failed log insert therefore
rolls the status change back as well, and the active-only guard prevents retries
from producing duplicate logs.

The inventory list removes an item optimistically when either action is
selected. If the request fails, the original item is merged back into the list
in expiry order and the API error is shown.

# Recipe suggestions

`GET /recipe-suggestions` derives ingredients from the authenticated user's
active inventory. It excludes expired items, places items expiring in zero
through seven days first, deduplicates normalized names, and fills the remaining
25-ingredient limit with longer-dated items. The response identifies the
`priority_ingredients` so the client can explain why those recipes were chosen.

The existing authenticated `POST /recipe-suggestions` remains available for
explicit ingredient lists. Ingredient names are Unicode-normalized, trimmed,
case-folded, and deduplicated. Both endpoints send the Spoonacular key in the
`x-api-key` header and never return or log it.

Set `SPOONACULAR_API_KEY` in the root `.env` file used by Compose. Successful
responses are cached in-process for six hours, with a bounded 24-hour stale
copy used only when Spoonacular times out, fails, or rejects a request because
of quota or rate limiting. The `source` response field is `spoonacular`,
`cache`, or `stale-cache`.

The Compose API currently runs two Gunicorn workers. Each worker therefore has
an independent cache, which can duplicate upstream calls and yield different
eviction times. Move these entries to Redis before scaling beyond one process
or instance if shared cache behavior and quota efficiency are required.

# Waste outcome category analytics

`GET /waste-logs/category-summary` returns the authenticated user's used and
wasted event counts per category. The endpoint executes one aggregate query
grouped by `waste_logs.category` and `waste_logs.action`, then pivots those rows
into `{category, used, wasted}` JSON objects. Categories remain nullable so
uncategorized logs are not conflated with a user-entered category named
`Unsorted`.

The category on each waste log is the event-time snapshot copied from its
inventory item. Inventory items use the trained grocery model only when the
client does not supply a category; an explicit category remains authoritative.

The React chart derives percentages from the raw counts with `useMemo` and
renders a 100% stacked bar for each category. These percentages describe logged
item outcomes, not food quantity or weight. Quantity-based waste analytics
would require the log to snapshot quantity and a normalized unit.

# Expiry state

Inventory responses include `days_until_expiry` and `expiry_status`. The status
is `expired` for negative day counts, `expiring_soon` for zero through seven
days inclusive, and `active` above seven days.

These values are computed from the non-null indexed `expiry_date` when a
response is serialized. They are intentionally not stored: persisted expiry
states would become incorrect at midnight and would require a scheduled data
rewrite. A single current date is reused while serializing each response so
every item in that payload uses the same boundary.
