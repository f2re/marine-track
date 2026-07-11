# Transactional Telegram user state

`telegram_user_state.json` stores per-user saved bounding boxes and output preferences. It is mutable runtime state below `MARINE_TRACK_OUTPUT_DIR`; it is not stored in an immutable release directory.

## Storage contract

Every internal read-modify-write operation holds an inter-process `flock` on:

```text
telegram_user_state.json.lock
```

The lock file is opened without following symbolic links where the platform supports `O_NOFOLLOW`, verified as a regular file, and forced to mode `0600`. A process-local re-entrant lock also serializes threads because independent `flock` descriptors in one process are not a substitute for thread synchronization.

Writers hold the exclusive lock for the complete transaction:

```text
read current document
→ validate schema
→ apply mutation
→ write a same-directory temporary file
→ flush and fsync
→ os.replace
→ fsync parent directory
```

Readers hold a shared lock and can observe only the old or new complete document. The active JSON file is mode `0600`, UTF-8, deterministically serialized, and has exactly one trailing newline. Temporary files are mode `0600` and are removed after a failed write.

## Schema and migration

The current document contains:

```json
{
  "schema_version": 1,
  "users": {}
}
```

The previous unversioned `{"users": ...}` format remains readable. Its next successful mutation writes schema version 1 without service downtime.

An unknown future `schema_version` is not treated as corruption. Reads and mutations fail closed, the original file remains unchanged, and health reports a critical schema error. This prevents an older release from overwriting state written by a newer release.

## Corruption recovery

Malformed JSON, a non-object root, or a non-object `users` member is never silently overwritten. After the shared-lock read detects corruption, the code re-reads under the exclusive lock and moves the still-corrupt active bytes to:

```text
telegram_user_state.corrupt-<UTC timestamp>-<pid>-<random>.json
```

The quarantine file is mode `0600`. The requested mutation can then create a clean versioned document. A plain reader returns an empty snapshot only after the original corrupt bytes have been preserved.

Operators should retain quarantine files for diagnosis and remove them only after review. Quarantine file contents are not emitted by health reports.

## Health reporting

`marine-track-health` exposes a separate `telegram_user_state` check with only:

- schema version;
- user count;
- quarantine count;
- atomic-replace capability;
- inter-process-lock capability.

The report does not emit the state path, user IDs, saved coordinates, or output preferences.

Status rules:

- missing state before first interaction: non-critical warning;
- valid unversioned legacy state: non-critical warning;
- valid schema-1 state: `ok`;
- valid state with historical quarantine files: non-critical warning;
- malformed active JSON or unsupported schema: critical failure.

## Regression coverage

Offline tests cover:

- legacy read and schema-1 upgrade;
- mode `0600` for state, lock, and quarantine files;
- exactly one trailing newline;
- quarantine before mutation and before explicit full replacement;
- fail-closed handling of an unsupported future schema;
- redacted health output;
- multi-process updates to the same bbox without a lost `use_count` increment;
- absence of abandoned same-directory temporary files after the parallel test.
