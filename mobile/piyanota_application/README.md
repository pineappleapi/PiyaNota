# PiyaNota mobile app

Flutter app, **Android only**. The user photographs a score, the app uploads it, shows processing status, then
plays the four voices (Soprano, Alto, Tenor, Bass) with a mixer, speed control and export. State management is
Riverpod; session tokens are kept in `flutter_secure_storage` (Keystore), never in `shared_preferences`.

## Run

From this folder:

```bash
flutter pub get
flutter devices                                  # list connected phones/emulators
flutter run -d <device-id>                       # debug: uses the fake backend by default
flutter run -d <device-id> \
  --dart-define=API_BASE_URL=https://<your-render-service>.onrender.com \
  --dart-define=USE_FAKE_AUTH=false              # talk to the real API
flutter build apk --release                      # release builds never use the fake backend
```

`lib/config/api_config.dart` explains both settings. Debug builds default to the fake backend
(`USE_FAKE_AUTH` is true in debug); profile and release builds default to the real one.

## Check before you commit

```bash
flutter analyze
flutter test
```

Both must be clean.

## Where things are (`lib/`)

| Folder | Holds |
|---|---|
| `main.dart`, `app.dart`, `splash_gate.dart` | Entry point, app widget, the splash/auto-login gate. |
| `config/` | `api_config.dart`: backend URL and endpoint paths. |
| `routes/` | `app_routes.dart`: route names. |
| `screens/<feature>/` | One folder per feature: `auth`, `onboarding`, `capture`, `processing`, `library`, `playback`, `retake`, `scan_status`, `settings`. Each has its `*_messages.dart` (user-facing text) and a `widgets/` folder. |
| `state/` | Riverpod providers and the objects they own (auth, capture, processing, library, playback, export, settings). |
| `services/` | API clients (`*_api.dart`), their fake versions (`fake_*_api.dart`), audio (`live_synth*.dart`), local storage, `capture/` (camera/PDF input). |
| `models/` | Plain data classes shared by state, services and screens. |
| `widgets/` | Widgets used by more than one screen. |
| `theme/` | Palette, typography, spacing tokens. Styling comes from here, not inline values. |

`test/` mirrors `lib/` by feature. `assets/branding/` holds the shipped logos.

## Notes

- `THIRD_PARTY_NOTICES.md` lists third-party licences that ship with the app.
- The app talks to the Flask API in `../../backend/`. The API contract check is
  `python -m backend.scripts.smoke <base_url>` from the repo root.
