# Bramble Kiosk: where each capability stands

> A fictional sample project: a self-service kiosk for a town library. This table is the only place a row's status
> changes. `STATUS.md` beside it is generated.

## Statuses

- **Live:** in the kiosks at the branches; the note names the release.
- **Built, not live (branch):** on a reviewed branch, named in the status.
- **Demo only:** works against the sample catalogue; no real loan changes.
- **Partial:** part of it exists; the note says which part.
- **Not built.**

## Counts

| # | Domain | All | Live | Built, not live | Demo only | Partial | Not built |
|---|---|---|---|---|---|---|---|
| 1 | Catalogue search | 4 | 2 | 1 |  | 1 | 0 |
| 2 | Lending | 4 | 1 | 1 | 1 |  | 1 |
| 3 | Accounts | 3 | 1 |  |  | 1 | 1 |
| | **Launch** | **11** | **4** | **2** | **1** | **2** | **2** |
| 4 | Reporting | 3 | 0 |  |  |  | 3 |
| 5 | Accessibility | 2 | 0 |  |  | 1 | 1 |
| | **Later** | **5** |  |  |  | **1** | **4** |
| | **All** | **16** | **4** | **2** | **1** | **3** | **6** |

## Launch: eleven capabilities

### 1. Catalogue search (4)

| # | Capability | Status | What exists |
|---|---|---|---|
| 1 | Title and author search | Live | Search by title or author on the kiosk; released in `1a2b3c4`. |
| 2 | Availability by branch | Live | Which branch holds a copy, read from the catalogue feed (PR #12). |
| 3 | Reading-list import | Built, not live (reading-lists) | Imports a list from a CSV file; reviewed on its branch. |
| 4 | Barcode lookup | Partial | Reads ISBN barcodes; the older shelf codes are not read. |

### 2. Lending (4)

| # | Capability | Status | What exists |
|---|---|---|---|
| 5 | Self-checkout | Live | Scan a card and a book, get a receipt; released in `5d6e7f8`. |
| 6 | Self-return | Demo only | Runs on the sample catalogue at the open day; no real loan changes. |
| 7 | Renewals | Built, not live (renewals) | Renew from the receipt's code; reviewed on its branch. |
| 8 | Fines and holds | Not built | |

### 3. Accounts (3)

| # | Capability | Status | What exists |
|---|---|---|---|
| 9 | Card sign-in | Live | Library card and PIN. |
| 10 | Staff override | Partial | Staff sign in; the override screen is not there yet. |
| 11 | Account notices | Not built | |

## Later: five capabilities

### 4. Reporting (3): none built

All three are Not built: daily use, overdue lists, stock counts.

### 5. Accessibility (2)

| # | Capability | Status | What exists |
|---|---|---|---|
| 15 | Screen-reader mode | Partial | Spoken prompts on the search screen only. |
| 16 | High-contrast theme | Not built | |
