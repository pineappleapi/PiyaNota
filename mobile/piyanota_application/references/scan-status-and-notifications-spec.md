# Spec: Scan Status & Notification Bell

**App:** Music app that converts sheet music images into piano guides (OMR)
**Feature:** Show scan progress in the library and a notification bell, with consistent navigation between the Processing screen and Playback screen.

---

## 1. Design Principles

- **One source of truth.** The processing screen, library card, and bell all read the same progress data so they never disagree.
- **Bell shows what needs attention.** Use the red badge only for completed or failed scans. Show in-progress scans with a subtle animated ring or spinner.
- **Progress appears in two places:** the bell panel and the score card in the library.
- **Short, friendly copy.** Don't repeat "Hang on tight" on every update.
- **Consistent wording.** Always say "scan" and "piano guide". Avoid mixing "convert" and "process" in user-facing text where possible.

---

## 2. Score States

Every score has exactly one status. A score is created in the library the moment a scan starts, with status `processing`.

| Status | Meaning | Tapping the score opens |
|---|---|---|
| `processing` | Scan in progress | Processing screen |
| `completed` | Piano guide ready | Playback screen |
| `failed` | Scan error | Failure screen or dialog with Retry / Delete |
| `cancelled` | User cancelled | Score is removed from the library |

**Navigation rule (use everywhere):**
- If status is `processing` → open the **Processing screen**.
- If status is `completed` → open the **Playback screen**.

---

## 3. Processing Screen

**Contents**
- Score name
- Progress bar and percentage
- Current stage text (e.g. "Reading your sheet music…", "Detecting notes…")
- Helper text: "We'll notify you when your piano guide is ready."
- Optional time estimate: "About 1 minute left."

**Buttons**

| Button | Style | Behavior |
|---|---|---|
| **Keep browsing** | Primary (filled) | Returns to the library. The scan continues. |
| **Cancel scan** | Text button (neutral or red) | Opens a confirm dialog. |

**Cancel confirm dialog**
- Title: "Cancel scan?"
- Body: "You'll lose your progress."
- Actions: **Cancel scan** / **Keep scanning**
- On confirm: stop the job and delete the placeholder score from the library.

**Auto-redirect:** If the user opens this screen after the scan has finished, send them to the Playback screen.

**Layout sketch**

```
Reading your sheet music…
▓▓▓▓▓▓░░░░  60%
We'll notify you when your piano guide is ready.

[ Keep browsing ]   ·   Cancel scan
```

---

## 4. Library Screen: Score Card While Processing

- Placeholder card shows the title, a small progress bar (or ring), and the label "Converting… 60%".
- Thumbnail is dimmed, or shows the scanned image.
- **Tap** opens the Processing screen.
- **Long-press** (optional) shows "Cancel scan".
- On completion, the card updates **in place** to its normal look. Tap now opens the Playback screen.

---

## 5. Notification Bell (Library Header)

### 5.1 Bell states

| State | Appearance |
|---|---|
| Idle | Plain bell, nothing active |
| Processing | Bell with a small animated ring or spinner |
| Unread items | Red dot or count badge (completed and failed items only) |

### 5.2 Bell panel

Tapping the bell opens a panel or dropdown listing recent items, **newest first**.

### 5.3 Row types

**Processing row**
> **Clair de Lune** is still being converted. Hang on tight!
> ▓▓▓▓▓▓░░░░ 60%

- Progress bar updates live.
- Tap opens the **Processing screen**.
- Not dismissible while active.

**Completed row**
> **Clair de Lune** is ready to play 🎹
> Just now

- Tap opens the **Playback screen** and marks the item as read.
- Unread rows show a dot or bold title.

**Failed row**
> **Clair de Lune** couldn't be converted
> Tap to see what happened

- Tap opens the failure screen with **Retry / Delete** options.

### 5.4 Panel rules

- A processing row turns into a completed row **in place**. Never show both for the same score.
- Keep the last 10–20 items, or auto-clear after about 7 days.
- Provide "Mark all as read".
- Swipe to dismiss completed and failed rows.
- Empty state: "No notifications yet."

---

## 6. Completion Behavior

When a scan finishes:

1. Score status becomes `completed`.
2. The library card updates in place.
3. The bell row changes to "ready" and the bell shows an unread badge.
4. **App in foreground:** show a small in-app banner or toast: "Clair de Lune is ready. [Open]".
5. **App in background or closed:** send a system push notification: "Your piano guide for *Clair de Lune* is ready." Tapping it opens the Playback screen directly.

---

## 7. Edge Cases

| Case | Expected behavior |
|---|---|
| Multiple scans at once | One processing row per score. Bell ring shows if any scan is active. |
| App closed mid-scan | The job keeps running (server-side or background task). Status is restored when the app reopens. |
| No internet or app killed | Show a "Paused" or "Failed" state with Retry, not an endless progress bar. |
| Cancel from the library | Optional: long-press a processing card for "Cancel scan". |
| Progress stalls | After no updates for a while, change the message to "Still working, this one's a long piece." |
| Notification permission denied | Fall back to the bell and in-app banners. Consider a one-time prompt explaining why notifications help. |
| User opens a score that just completed | Redirect to Playback screen (see navigation rule). |

---

## 8. Developer Notes

**Data model (per score or notification record)**

| Field | Type | Notes |
|---|---|---|
| `status` | enum | `processing`, `completed`, `failed`, `cancelled` |
| `progress` | int (0-100) | Current percent |
| `stage` | string | Current stage label |
| `createdAt` | timestamp | |
| `isRead` | bool | For completed/failed notifications |

**Implementation guidelines**
- Use **one shared progress source** that the Processing screen, library card, and bell all subscribe to.
- **Throttle progress updates** (for example every 1–2 seconds) to avoid UI jitter and battery drain.
- The scan job must run independently of the Processing screen's lifecycle.
- Persist status so it survives app restarts.
- Apply the navigation rule from Section 2 in every tap handler.

---

## 9. Copy Summary

| Place | Text |
|---|---|
| Processing screen title | "Reading your sheet music…" |
| Processing helper text | "We'll notify you when your piano guide is ready." |
| Primary button | "Keep browsing" |
| Secondary button | "Cancel scan" |
| Cancel confirm | "Cancel scan? You'll lose your progress." |
| Library card label | "Converting… 60%" |
| Bell: processing row | "[Score] is still being converted. Hang on tight!" |
| Bell: completed row | "[Score] is ready to play" |
| Bell: failed row | "[Score] couldn't be converted" |
| In-app toast | "[Score] is ready. [Open]" |
| Push notification | "Your piano guide for [Score] is ready." |
| Stalled progress | "Still working, this one's a long piece." |
| Empty bell panel | "No notifications yet." |

---

## 10. Acceptance Checklist

- [ ] Starting a scan immediately creates a library card with status `processing`.
- [ ] Tapping a processing card opens the Processing screen.
- [ ] Tapping a completed card opens the Playback screen.
- [ ] "Keep browsing" returns to the library without stopping the scan.
- [ ] "Cancel scan" asks for confirmation, then removes the placeholder score.
- [ ] Bell shows an animated state while any scan is active.
- [ ] Bell panel shows a live progress row that opens the Processing screen.
- [ ] Completion converts the row in place, adds an unread badge, and opens Playback on tap.
- [ ] Foreground completion shows an in-app toast; background completion sends a push notification.
- [ ] Scan continues if the app is closed, and state is restored on reopen.
- [ ] Failed scans show a clear state with Retry / Delete.
- [ ] Progress is identical across the Processing screen, library card, and bell.
