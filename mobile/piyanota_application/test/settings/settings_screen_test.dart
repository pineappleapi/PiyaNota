import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:piyanota_application/models/auth_session.dart';
import 'package:piyanota_application/models/score_details.dart';
import 'package:piyanota_application/models/voice_part.dart';
import 'package:piyanota_application/routes/app_routes.dart';
import 'package:piyanota_application/screens/auth/auth_messages.dart';
import 'package:piyanota_application/screens/playback/playback_messages.dart';
import 'package:piyanota_application/screens/settings/settings_messages.dart';
import 'package:piyanota_application/screens/settings/settings_screen.dart';
import 'package:piyanota_application/screens/library/widgets/library_header.dart';
import 'package:piyanota_application/screens/scan_status/scan_bell.dart';
import 'package:piyanota_application/services/auth_api.dart';
import 'package:piyanota_application/services/local_results_store.dart';
import 'package:piyanota_application/services/onboarding_prefs_service.dart';
import 'package:piyanota_application/services/session_storage.dart';
import 'package:piyanota_application/services/settings_prefs_service.dart';
import 'package:piyanota_application/state/auth_providers.dart';
import 'package:piyanota_application/state/playback_providers.dart';
import 'package:piyanota_application/state/settings_providers.dart';

import '../auth/auth_test_harness.dart';

const _openSettings = 'open settings';
const _email = 'maria@example.com';
const _token = 'sess_settings';
const _strongPassword = 'NewPassw0rd!';

AuthSession _liveSession() => AuthSession(
  userId: 7,
  email: _email,
  role: 'choir_member',
  sessionToken: _token,
  // Relative to now: the gate compares with the real clock.
  expiresAt: DateTime.now().toUtc().add(const Duration(days: 7)),
);

/// Records every tempo save, and can fail them, so tests can count writes
/// and check that a failed save leaves the screen unsaved.
class _RecordingTempoPrefs extends SettingsPrefsService {
  final List<int> saves = [];
  bool fail = false;

  @override
  Future<void> setDefaultTempo(int bpm) async {
    saves.add(bpm);
    if (fail) throw PlatformException(code: 'disk-full');
    await super.setDefaultTempo(bpm);
  }
}

class _RecordingResultsStore extends LocalResultsStore {
  _RecordingResultsStore()
    : super(
        rootProvider: () async => throw UnimplementedError(),
        downloader: DioFileDownloader(Dio()),
      );

  int deleteAllCalls = 0;

  @override
  Future<void> deleteAll() async => deleteAllCalls++;
}

class _Harness {
  _Harness({
    this.session,
    Map<String, Object> prefs = const {},
    this.version = '1.0.0 (1)',
    this.storeEmail = true,
  }) : storage = FaultySecureStorage(),
       api = ScriptedAuthApi(onChangePassword: () async {}) {
    SharedPreferences.setMockInitialValues(prefs);
  }

  final AuthSession? session;
  final _RecordingTempoPrefs tempoPrefs = _RecordingTempoPrefs();
  final _RecordingResultsStore resultsStore = _RecordingResultsStore();

  /// Null makes the version lookup fail.
  final String? version;

  /// False mimics a session saved before PIYA-212 stored the email.
  final bool storeEmail;
  final FaultySecureStorage storage;
  final ScriptedAuthApi api;
  late final SessionStorage sessionStorage = SessionStorage(storage);

  /// Library stand-in at the root, Settings pushed over it through the
  /// real route, as the bottom bar does.
  Future<void> pump(
    WidgetTester tester, {
    Size logicalSize = const Size(412, 915),
    double textScale = 1.0,
  }) async {
    tester.view.devicePixelRatio = 2.0;
    tester.view.physicalSize = logicalSize * 2.0;
    addTearDown(tester.view.reset);
    final saved = session;
    if (saved != null) await sessionStorage.save(saved);
    if (!storeEmail) storage.values.remove('session_email');

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authApiProvider.overrideWithValue(api),
          localResultsStoreProvider.overrideWithValue(resultsStore),
          sessionStorageProvider.overrideWithValue(sessionStorage),
          settingsPrefsServiceProvider.overrideWithValue(tempoPrefs),
          appVersionProvider.overrideWith(
            (ref) async =>
                version ?? (throw PlatformException(code: 'no-package-info')),
          ),
        ],
        child: MaterialApp(
          builder: (context, child) => MediaQuery(
            data: MediaQuery.of(context)
                .copyWith(textScaler: TextScaler.linear(textScale)),
            child: child!,
          ),
          home: Builder(
            builder: (context) => Scaffold(
              body: Column(
                children: [
                  const Text(libraryMarker),
                  TextButton(
                    onPressed: () =>
                        Navigator.of(context).pushNamed(AppRoutes.settings),
                    child: const Text(_openSettings),
                  ),
                ],
              ),
            ),
          ),
          routes: {
            AppRoutes.settings: (_) => const SettingsGate(),
            AppRoutes.login: (_) => const Scaffold(body: Text(loginMarker)),
            AppRoutes.capture: (_) =>
                const Scaffold(body: Text('ROUTE:capture')),
          },
        ),
      ),
    );
    await tester.tap(find.text(_openSettings));
    await tester.pumpAndSettle();
  }
}

Finder _pill(VoicePart voice) =>
    find.bySemanticsLabel(SettingsMessages.voiceSemantics(voice.label));

Finder get _allVoicesPill => find.bySemanticsLabel(
  SettingsMessages.voiceSemantics(SettingsMessages.allVoices),
);

Finder get _tempoValue => find.byKey(const ValueKey('settings-tempo-value'));

/// Centres [finder] in the list, so it is clear of both the header and
/// the bottom bar that overlaps the list's end.
Future<void> _scrollTo(
  WidgetTester tester,
  Finder finder, {
  bool up = false,
}) async {
  // ListView builds lazily: drag until the row exists, then centre it.
  if (finder.evaluate().isEmpty) {
    await tester.dragUntilVisible(
      finder,
      find
          .descendant(
            of: find.byType(SettingsScreen),
            matching: find.byType(Scrollable),
          )
          .first,
      Offset(0, up ? 120 : -120),
    );
  }
  await Scrollable.ensureVisible(tester.element(finder.first), alignment: 0.5);
  await tester.pumpAndSettle();
}

Finder get _saveChanges => find.byKey(const ValueKey('settings-save'));

Future<void> _save(WidgetTester tester) async {
  await _scrollTo(tester, _saveChanges);
  await tester.tap(_saveChanges);
  await tester.pumpAndSettle();
}

Finder get _prompt => find.byType(AlertDialog);
Finder _promptButton(String label) =>
    find.descendant(of: _prompt, matching: find.text(label));

/// Makes Settings dirty without saving.
Future<void> _dirtyVoice(WidgetTester tester) async {
  await tester.tap(find.text(VoicePart.bass.label));
  await tester.pumpAndSettle();
}

Future<void> _openChangePassword(WidgetTester tester) async {
  await tester.tap(find.text(SettingsMessages.changePasswordHint));
  await tester.pumpAndSettle();
}

Future<void> _fillChangePassword(
  WidgetTester tester, {
  String current = 'OldPassw0rd!',
  String next = _strongPassword,
  String? confirm,
}) async {
  // Scoped to the sheet: the email behind it is a SelectableText, which
  // is an EditableText too.
  final fields = _sheetFields;
  await tester.enterText(fields.at(0), current);
  await tester.enterText(fields.at(1), next);
  await tester.enterText(fields.at(2), confirm ?? next);
  await tester.pump();
}

Finder get _sheetFields => find.descendant(
  of: find.byType(BottomSheet),
  matching: find.byType(EditableText),
);

Finder get _submitButton => find.descendant(
  of: find.byType(BottomSheet),
  matching: buttonLabelled(SettingsMessages.changePassword),
);

/// [text] drawn as part of the [index]th field of the sheet.
Finder _fieldError(int index, String text) => find.descendant(
  of: find
      .descendant(
        of: find.byType(BottomSheet),
        matching: find.byType(TextFormField),
      )
      .at(index),
  matching: find.text(text),
);

Future<void> _submitChangePassword(
  WidgetTester tester,
  _Harness harness,
  Object error,
) async {
  harness.api.onChangePassword = () async => throw error;
  await _openChangePassword(tester);
  await _fillChangePassword(tester);
  await tester.tap(_submitButton);
  await tester.pumpAndSettle();
}

void main() {
  group('account and about (AC1, AC2)', () {
    testWidgets('shows the signed-in email and the app version', (
      tester,
    ) async {
      await _Harness(session: _liveSession()).pump(tester);
      expect(find.text(_email), findsOneWidget);
      expect(find.byType(SelectableText), findsOneWidget);
      await _scrollTo(tester, find.text('1.0.0 (1)'));
      expect(find.text('1.0.0 (1)'), findsOneWidget);
    });

    testWidgets('a session saved without an email says how to show it', (
      tester,
    ) async {
      await _Harness(session: _liveSession(), storeEmail: false).pump(tester);
      expect(find.byType(SettingsScreen), findsOneWidget);
      expect(find.text(SettingsMessages.emailUnknown), findsOneWidget);
    });

    testWidgets('an unreadable version says Unknown', (tester) async {
      await _Harness(session: _liveSession(), version: null).pump(tester);
      final version = find.byKey(const ValueKey('settings-version'));
      await _scrollTo(tester, version);
      expect(
        tester.widget<Text>(version).data,
        SettingsMessages.versionUnknown,
      );
    });

    testWidgets('the real version provider formats PackageInfo', (
      tester,
    ) async {
      PackageInfo.setMockInitialValues(
        appName: 'PiyaNota',
        packageName: 'com.piyanota.app',
        version: '1.2.3',
        buildNumber: '45',
        buildSignature: '',
      );
      final container = ProviderContainer();
      addTearDown(container.dispose);
      expect(await container.read(appVersionProvider.future), '1.2.3 (45)');
    });
  });

  group('session gate (AC5)', () {
    testWidgets('no session goes to Login, not Settings', (tester) async {
      await _Harness().pump(tester);
      expect(find.text(loginMarker), findsOneWidget);
      expect(find.byType(SettingsScreen), findsNothing);
    });

    testWidgets('an expired session goes to Login and is cleared', (
      tester,
    ) async {
      final harness = _Harness(
        session: AuthSession(
          userId: 7,
          email: _email,
          role: 'choir_member',
          sessionToken: _token,
          expiresAt: DateTime.now().toUtc().subtract(const Duration(hours: 1)),
        ),
      );
      await harness.pump(tester);
      expect(find.text(loginMarker), findsOneWidget);
      expect(find.text(_email), findsNothing);
      expect(harness.storage.values, isEmpty);
    });
  });

  group('default voice (AC7)', () {
    testWidgets('shows the onboarding pick and saves a new one', (
      tester,
    ) async {
      await _Harness(
        session: _liveSession(),
        prefs: {'onboarding_default_voice': VoicePart.alto.name},
      ).pump(tester);
      expect(
        tester.getSemantics(_pill(VoicePart.alto)),
        isSemantics(
          isSelected: true,
          isButton: true,
          isInMutuallyExclusiveGroup: true,
        ),
      );
      expect(
        tester.getSemantics(_pill(VoicePart.bass)),
        isSemantics(isSelected: false),
      );

      await tester.tap(find.text(VoicePart.bass.label));
      await tester.pumpAndSettle();
      // Nothing is stored until Save changes.
      expect(
        await OnboardingPrefsService().getDefaultVoicePart(),
        VoicePart.alto,
      );
      await _save(tester);
      expect(
        await OnboardingPrefsService().getDefaultVoicePart(),
        VoicePart.bass,
      );
      expect(
        tester.getSemantics(_pill(VoicePart.bass)),
        isSemantics(isSelected: true),
      );
      expect(
        tester.getSemantics(_pill(VoicePart.alto)),
        isSemantics(isSelected: false),
      );
    });
  });

  group('All voices (PIYA-212-V2.1)', () {
    testWidgets('F6a: one voice per line, in order, same left edge', (
      tester,
    ) async {
      await _Harness(session: _liveSession()).pump(tester);
      final labels = [
        SettingsMessages.allVoices,
        for (final v in VoicePart.values) v.label,
      ];
      final rects = [for (final l in labels) tester.getRect(find.text(l))];
      for (var i = 1; i < rects.length; i++) {
        expect(rects[i].top, greaterThan(rects[i - 1].bottom));
      }
      final pills = [
        for (final l in labels)
          tester.getRect(
            find
                .ancestor(of: find.text(l), matching: find.byType(InkWell))
                .first,
          ),
      ];
      expect(pills.map((r) => r.left).toSet(), hasLength(1));
    });

    testWidgets('AC1: offered next to the four voices', (tester) async {
      await _Harness(session: _liveSession()).pump(tester);
      expect(find.text(SettingsMessages.allVoices), findsOneWidget);
      for (final voice in VoicePart.values) {
        expect(find.text(voice.label), findsOneWidget);
      }
    });

    testWidgets('AC3, AC5: no saved voice shows All voices selected, with a '
        'screen-reader label', (tester) async {
      await _Harness(session: _liveSession()).pump(tester);
      expect(
        tester.getSemantics(_allVoicesPill),
        isSemantics(
          isSelected: true,
          isButton: true,
          isInMutuallyExclusiveGroup: true,
          label: SettingsMessages.voiceSemantics(SettingsMessages.allVoices),
        ),
      );
      for (final voice in VoicePart.values) {
        expect(
          tester.getSemantics(_pill(voice)),
          isSemantics(isSelected: false),
        );
      }
    });

    testWidgets('AC2: choosing it removes the saved voice', (tester) async {
      await _Harness(
        session: _liveSession(),
        prefs: {'onboarding_default_voice': VoicePart.alto.name},
      ).pump(tester);
      await tester.tap(find.text(SettingsMessages.allVoices));
      await tester.pumpAndSettle();
      await _save(tester);

      expect(await OnboardingPrefsService().getDefaultVoicePart(), isNull);
      expect(
        (await SharedPreferences.getInstance()).containsKey(
          'onboarding_default_voice',
        ),
        isFalse,
      );
      expect(
        tester.getSemantics(_allVoicesPill),
        isSemantics(isSelected: true),
      );
      expect(
        tester.getSemantics(_pill(VoicePart.alto)),
        isSemantics(isSelected: false),
      );
    });

    testWidgets('picking a voice again after All voices saves it', (
      tester,
    ) async {
      await _Harness(session: _liveSession()).pump(tester);
      await tester.tap(find.text(VoicePart.tenor.label));
      await tester.pumpAndSettle();
      await _save(tester);
      expect(
        await OnboardingPrefsService().getDefaultVoicePart(),
        VoicePart.tenor,
      );
    });

    for (final (size, scale) in const [
      (Size(360, 640), 1.0),
      (Size(360, 640), 1.3),
    ]) {
      testWidgets('AC5: no overflow at 360 dp, ${scale}x text', (tester) async {
        await _Harness(
          session: _liveSession(),
          prefs: {'onboarding_default_voice': VoicePart.soprano.name},
        ).pump(tester, logicalSize: size, textScale: scale);
        await _scrollTo(tester, find.text(SettingsMessages.allVoices));
        expect(tester.takeException(), isNull);
        expect(
          tester.getRect(find.text(SettingsMessages.allVoices)).right,
          lessThanOrEqualTo(size.width),
        );
      });
    }
  });

  group('default tempo (AC8)', () {
    testWidgets('starts at 90, steps by one, and saves only on Save changes', (
      tester,
    ) async {
      final harness = _Harness(session: _liveSession());
      await harness.pump(tester);
      await _scrollTo(tester, _tempoValue);
      expect(find.text(SettingsMessages.tempoValue(90)), findsOneWidget);

      await tester.tap(find.byIcon(Icons.add_rounded));
      await tester.pumpAndSettle();
      expect(find.text(SettingsMessages.tempoValue(91)), findsOneWidget);
      expect(harness.tempoPrefs.saves, isEmpty);

      await tester.tap(find.byIcon(Icons.remove_rounded));
      await tester.tap(find.byIcon(Icons.remove_rounded));
      await tester.pumpAndSettle();
      expect(harness.tempoPrefs.saves, isEmpty);

      await _save(tester);
      expect(await SettingsPrefsService().getDefaultTempo(), 89);
      expect(harness.tempoPrefs.saves, [89]);
    });

    testWidgets('holding + repeats and stops at 180; one write on Save', (
      tester,
    ) async {
      final harness = _Harness(
        session: _liveSession(),
        prefs: {SettingsPrefsService.defaultTempoKey: 176},
      );
      await harness.pump(tester);
      await _scrollTo(tester, _tempoValue);
      final gesture = await tester.startGesture(
        tester.getCenter(find.byIcon(Icons.add_rounded)),
      );
      await tester.pump(const Duration(seconds: 2));
      await gesture.up();
      await tester.pumpAndSettle();
      expect(find.text(SettingsMessages.tempoValue(180)), findsOneWidget);
      expect(harness.tempoPrefs.saves, isEmpty);
      await _save(tester);
      expect(
        await SettingsPrefsService().getDefaultTempo(),
        ScoreDetails.maxTempo,
      );
      expect(harness.tempoPrefs.saves, [ScoreDetails.maxTempo]);
    });

    testWidgets('a failed save keeps the draft, says so, and can retry', (
      tester,
    ) async {
      final harness = _Harness(session: _liveSession());
      await harness.pump(tester);
      await _scrollTo(tester, _tempoValue);
      await tester.tap(find.byIcon(Icons.add_rounded));
      await tester.pumpAndSettle();
      harness.tempoPrefs.fail = true;
      await _save(tester);
      expect(find.text(SettingsMessages.saveFailed), findsOneWidget);
      expect(find.text(SettingsMessages.tempoValue(91)), findsOneWidget);
      expect(tester.widget<ElevatedButton>(_saveChanges).onPressed, isNotNull);

      harness.tempoPrefs.fail = false;
      // The snackbar floats over the button until it times out.
      await tester.pump(const Duration(seconds: 11));
      await tester.pumpAndSettle();
      await _save(tester);
      expect(await SettingsPrefsService().getDefaultTempo(), 91);
      expect(tester.widget<ElevatedButton>(_saveChanges).onPressed, isNull);
    });

    testWidgets('cannot go below 30', (tester) async {
      await _Harness(
        session: _liveSession(),
        prefs: {SettingsPrefsService.defaultTempoKey: 30},
      ).pump(tester);
      await _scrollTo(tester, _tempoValue);
      await tester.tap(find.byIcon(Icons.remove_rounded));
      await tester.pumpAndSettle();
      expect(find.text(SettingsMessages.tempoValue(30)), findsOneWidget);
    });

    testWidgets('reads as one adjustable value for screen readers', (
      tester,
    ) async {
      final handle = tester.ensureSemantics();
      await _Harness(session: _liveSession()).pump(tester);
      await _scrollTo(tester, _tempoValue);
      final node = tester.getSemantics(
        find.bySemanticsLabel(SettingsMessages.defaultTempo).last,
      );
      expect(node.value, '90 beats per minute');
      expect(node.increasedValue, '91 beats per minute');
      expect(node.decreasedValue, '89 beats per minute');

      tester.semantics.increase(
        find.semantics.byValue(SettingsMessages.tempoSemanticsValue(90)),
      );
      await tester.pumpAndSettle();
      expect(find.text(SettingsMessages.tempoValue(91)), findsOneWidget);
      handle.dispose();
    });
  });

  group('save and leave prompt (F6b)', () {
    testWidgets('Save changes is disabled until something changes', (
      tester,
    ) async {
      await _Harness(session: _liveSession()).pump(tester);
      await _scrollTo(tester, _saveChanges);
      expect(tester.widget<ElevatedButton>(_saveChanges).onPressed, isNull);
      await _dirtyVoice(tester);
      await _scrollTo(tester, _saveChanges);
      expect(tester.widget<ElevatedButton>(_saveChanges).onPressed, isNotNull);
    });

    testWidgets('no prompt without changes: Library and Capture just go', (
      tester,
    ) async {
      await _Harness(session: _liveSession()).pump(tester);
      await tester.tap(find.text('Capture'));
      await tester.pumpAndSettle();
      expect(_prompt, findsNothing);
      expect(find.text('ROUTE:capture'), findsOneWidget);
    });

    testWidgets('no prompt without changes: Library tab and system back', (
      tester,
    ) async {
      await _Harness(session: _liveSession()).pump(tester);
      await tester.tap(find.text('Library'));
      await tester.pumpAndSettle();
      expect(_prompt, findsNothing);
      expect(find.text(libraryMarker), findsOneWidget);
    });

    testWidgets('prompt shows Discard on the left, plain, Save on the right, '
        'coloured', (tester) async {
      await _Harness(session: _liveSession()).pump(tester);
      await _dirtyVoice(tester);
      await tester.tap(find.text('Capture'));
      await tester.pumpAndSettle();

      final discard = find.widgetWithText(TextButton, SettingsMessages.discard);
      final save = find.widgetWithText(FilledButton, SettingsMessages.save);
      expect(discard, findsOneWidget);
      expect(save, findsOneWidget);
      expect(tester.getCenter(discard).dx, lessThan(tester.getCenter(save).dx));
      expect(tester.widget<TextButton>(discard).style?.backgroundColor, isNull);
      final theme = Theme.of(tester.element(save));
      final fill = tester
          .widget<FilledButton>(save)
          .style
          ?.backgroundColor
          ?.resolve({});
      expect(fill ?? theme.colorScheme.primary, theme.colorScheme.primary);
    });

    testWidgets('Capture tab: Save stores, then goes', (tester) async {
      await _Harness(session: _liveSession()).pump(tester);
      await _dirtyVoice(tester);
      await tester.tap(find.text('Capture'));
      await tester.pumpAndSettle();
      await tester.tap(_promptButton(SettingsMessages.save));
      await tester.pumpAndSettle();
      expect(find.text('ROUTE:capture'), findsOneWidget);
      expect(
        await OnboardingPrefsService().getDefaultVoicePart(),
        VoicePart.bass,
      );
    });

    testWidgets('Capture tab: Discard drops, then goes', (tester) async {
      await _Harness(session: _liveSession()).pump(tester);
      await _dirtyVoice(tester);
      await tester.tap(find.text('Capture'));
      await tester.pumpAndSettle();
      await tester.tap(_promptButton(SettingsMessages.discard));
      await tester.pumpAndSettle();
      expect(find.text('ROUTE:capture'), findsOneWidget);
      expect(await OnboardingPrefsService().getDefaultVoicePart(), isNull);
    });

    testWidgets('dismissing the prompt stays on Settings with the draft', (
      tester,
    ) async {
      await _Harness(session: _liveSession()).pump(tester);
      await _dirtyVoice(tester);
      await tester.tap(find.text('Capture'));
      await tester.pumpAndSettle();
      await tester.tapAt(const Offset(5, 5));
      await tester.pumpAndSettle();
      expect(_prompt, findsNothing);
      expect(find.byType(SettingsScreen), findsOneWidget);
      expect(
        tester.getSemantics(_pill(VoicePart.bass)),
        isSemantics(isSelected: true),
      );
    });

    testWidgets('Library tab and system back use the same prompt', (
      tester,
    ) async {
      await _Harness(session: _liveSession()).pump(tester);
      await _dirtyVoice(tester);
      await tester.tap(find.text('Library'));
      await tester.pumpAndSettle();
      expect(_prompt, findsOneWidget);
      await tester.tap(_promptButton(SettingsMessages.discard));
      await tester.pumpAndSettle();
      expect(find.text(libraryMarker), findsOneWidget);

      await tester.tap(find.text(_openSettings));
      await tester.pumpAndSettle();
      await _dirtyVoice(tester);
      await tester.binding.handlePopRoute();
      await tester.pumpAndSettle();
      expect(_prompt, findsOneWidget);
      await tester.tap(_promptButton(SettingsMessages.save));
      await tester.pumpAndSettle();
      expect(find.text(libraryMarker), findsOneWidget);
      expect(
        await OnboardingPrefsService().getDefaultVoicePart(),
        VoicePart.bass,
      );
    });

    testWidgets('Log out with unsaved changes asks first, then confirms', (
      tester,
    ) async {
      await _Harness(session: _liveSession()).pump(tester);
      await _dirtyVoice(tester);
      await _scrollTo(tester, find.text(SettingsMessages.logOut));
      await tester.tap(find.text(SettingsMessages.logOut));
      await tester.pumpAndSettle();
      expect(find.text(SettingsMessages.unsavedTitle), findsOneWidget);
      await tester.tap(_promptButton(SettingsMessages.discard));
      await tester.pumpAndSettle();
      expect(find.text(SettingsMessages.logOutTitle), findsOneWidget);
    });

    testWidgets('a failed Save keeps the user on Settings', (tester) async {
      final harness = _Harness(session: _liveSession());
      await harness.pump(tester);
      await _scrollTo(tester, _tempoValue);
      await tester.tap(find.byIcon(Icons.add_rounded));
      await tester.pumpAndSettle();
      harness.tempoPrefs.fail = true;
      await tester.tap(find.text('Capture'));
      await tester.pumpAndSettle();
      await tester.tap(_promptButton(SettingsMessages.save));
      await tester.pumpAndSettle();
      expect(find.byType(SettingsScreen), findsOneWidget);
      expect(find.text(SettingsMessages.saveFailed), findsOneWidget);
    });

    for (final (size, scale) in const [
      (Size(320, 568), 2.0),
      (Size(412, 915), 2.0),
    ]) {
      testWidgets('no overflow with the prompt open at ${size.width.toInt()} '
          'dp, ${scale}x text', (tester) async {
        await _Harness(session: _liveSession())
            .pump(tester, logicalSize: size, textScale: scale);
        await _scrollTo(tester, find.text(VoicePart.bass.label));
        await _dirtyVoice(tester);
        await _scrollTo(tester, _saveChanges);
        expect(tester.takeException(), isNull);
        await tester.tap(find.text('Capture'));
        await tester.pumpAndSettle();
        expect(_prompt, findsOneWidget);
        expect(tester.takeException(), isNull);
      });
    }
  });

  group('saved defaults reach playback (F6)', () {
    test(
      'a saved voice and tempo are what the open-score paths read',
      () async {
        SharedPreferences.setMockInitialValues({});
        await OnboardingPrefsService().setDefaultVoicePart(VoicePart.tenor);
        await SettingsPrefsService().setDefaultTempo(120);
        // playback_providers._defaultSelection and readFallbackTempo read
        // these same services at use time, with no cache in between.
        expect(
          await OnboardingPrefsService().getDefaultVoicePart(),
          VoicePart.tenor,
        );
        expect(await readFallbackTempo(SettingsPrefsService()), 120);
      },
    );
  });

  group('help (AC9)', () {
    testWidgets('each ? opens its explanation', (tester) async {
      await _Harness(session: _liveSession()).pump(tester);

      await tester.tap(find.byTooltip(SettingsMessages.voiceHelpTooltip));
      await tester.pumpAndSettle();
      expect(find.text(SettingsMessages.voiceHelpBody), findsOneWidget);
      await tester.tapAt(const Offset(10, 10));
      await tester.pumpAndSettle();
      expect(find.text(SettingsMessages.voiceHelpBody), findsNothing);

      await _scrollTo(
        tester,
        find.byTooltip(SettingsMessages.tempoHelpTooltip),
      );
      await tester.tap(find.byTooltip(SettingsMessages.tempoHelpTooltip));
      await tester.pumpAndSettle();
      expect(find.text(SettingsMessages.tempoHelpBody), findsOneWidget);
    });
  });

  group('change password (AC6)', () {
    testWidgets('success sends the session token and confirms', (tester) async {
      final harness = _Harness(session: _liveSession());
      await harness.pump(tester);
      await _openChangePassword(tester);
      await _fillChangePassword(tester);
      await tester.tap(_submitButton);
      await tester.pumpAndSettle();

      expect(harness.api.changePasswordCalls, 1);
      expect(harness.api.lastToken, _token);
      expect(harness.api.lastCurrentPassword, 'OldPassw0rd!');
      expect(harness.api.lastNewPassword, _strongPassword);
      expect(find.byType(BottomSheet), findsNothing);
      expect(find.text(SettingsMessages.passwordChanged), findsOneWidget);
    });

    testWidgets('a 403 marks the current-password field', (tester) async {
      final harness = _Harness(session: _liveSession());
      harness.api.onChangePassword = () async =>
          throw const CurrentPasswordIncorrectException();
      await harness.pump(tester);
      await _openChangePassword(tester);
      await _fillChangePassword(tester);
      await tester.tap(_submitButton);
      await tester.pumpAndSettle();

      expect(
        find.text(SettingsMessages.currentPasswordIncorrect),
        findsOneWidget,
      );
      expect(find.byType(BottomSheet), findsOneWidget);

      // Editing the field withdraws the server's verdict.
      await tester.enterText(_sheetFields.at(0), 'Other1!x');
      await tester.pump();
      expect(
        find.text(SettingsMessages.currentPasswordIncorrect),
        findsNothing,
      );
    });

    testWidgets('mismatched confirmation is caught before sending', (
      tester,
    ) async {
      final harness = _Harness(session: _liveSession());
      await harness.pump(tester);
      await _openChangePassword(tester);
      await _fillChangePassword(tester, confirm: 'Different1!');
      await tester.tap(_submitButton);
      await tester.pumpAndSettle();
      expect(find.text(AuthMessages.passwordsDoNotMatch), findsOneWidget);
      expect(harness.api.changePasswordCalls, 0);
    });

    testWidgets('a weak new password follows the Sign-Up rule', (tester) async {
      final harness = _Harness(session: _liveSession());
      await harness.pump(tester);
      await _openChangePassword(tester);
      await _fillChangePassword(tester, next: 'short');
      await tester.tap(_submitButton);
      await tester.pumpAndSettle();
      expect(find.text(AuthMessages.passwordTooWeak), findsOneWidget);
      expect(harness.api.changePasswordCalls, 0);
    });

    testWidgets('an expired session offers Log in, which ends it', (
      tester,
    ) async {
      final harness = _Harness(session: _liveSession());
      harness.api.onChangePassword = () async =>
          throw const AuthSessionExpiredException();
      await harness.pump(tester);
      await _openChangePassword(tester);
      await _fillChangePassword(tester);
      await tester.tap(_submitButton);
      await tester.pumpAndSettle();
      expect(find.text(SettingsMessages.sessionExpired), findsOneWidget);

      await tester.tap(find.text(SettingsMessages.logIn));
      await tester.pumpAndSettle();
      expect(find.text(loginMarker), findsOneWidget);
      expect(harness.storage.values, isEmpty);
    });

    testWidgets('rate limited says how many minutes to wait', (tester) async {
      final harness = _Harness(session: _liveSession());
      await harness.pump(tester);
      // 125 s rounds up to 3 minutes: never promise sooner than the server.
      await _submitChangePassword(
        tester,
        harness,
        const AuthRateLimitedException(retryAfterSeconds: 125),
      );
      expect(
        find.text('Too many attempts. Try again in 3 minutes.'),
        findsOneWidget,
      );
      expect(find.byType(BottomSheet), findsOneWidget);
    });

    testWidgets('a weak_password 400 shows the Sign-Up rule under New', (
      tester,
    ) async {
      final harness = _Harness(session: _liveSession());
      await harness.pump(tester);
      await _submitChangePassword(
        tester,
        harness,
        const AuthValidationException(
          'Server wording that must not be shown',
          code: weakPasswordCode,
          field: newPasswordField,
        ),
      );
      expect(_fieldError(1, AuthMessages.passwordTooWeak), findsOneWidget);
      expect(find.text('Server wording that must not be shown'), findsNothing);

      // Editing the new password withdraws the server's verdict.
      await tester.enterText(_sheetFields.at(1), 'Another1pass');
      // Settle: the error fades out, so one frame still has it in the tree.
      await tester.pumpAndSettle();
      expect(find.text(AuthMessages.passwordTooWeak), findsNothing);
    });

    testWidgets('another 400 shows the app fallback, not the server text', (
      tester,
    ) async {
      final harness = _Harness(session: _liveSession());
      await harness.pump(tester);
      await _submitChangePassword(
        tester,
        harness,
        const AuthValidationException('raw server text', code: 'missing_field'),
      );
      expect(find.text(AuthMessages.validationFallback), findsOneWidget);
      expect(find.text('raw server text'), findsNothing);
    });

    testWidgets('a network failure keeps the form with a banner', (
      tester,
    ) async {
      final harness = _Harness(session: _liveSession());
      harness.api.onChangePassword = () async =>
          throw const AuthNetworkException();
      await harness.pump(tester);
      await _openChangePassword(tester);
      await _fillChangePassword(tester);
      await tester.tap(_submitButton);
      await tester.pumpAndSettle();
      expect(find.text(AuthMessages.network), findsOneWidget);
      expect(find.byType(BottomSheet), findsOneWidget);
    });
  });

  group('log out (AC3, AC4)', () {
    testWidgets('Cancel keeps the session', (tester) async {
      final harness = _Harness(session: _liveSession());
      await harness.pump(tester);
      await _scrollTo(tester, find.text(SettingsMessages.logOut));
      await tester.tap(find.text(SettingsMessages.logOut));
      await tester.pumpAndSettle();
      expect(find.text(SettingsMessages.logOutTitle), findsOneWidget);

      await tester.tap(find.text(SettingsMessages.cancel));
      await tester.pumpAndSettle();
      expect(find.byType(SettingsScreen), findsOneWidget);
      expect(harness.storage.values['session_token'], _token);
    });

    testWidgets('confirming clears the session and lands on Login', (
      tester,
    ) async {
      final harness = _Harness(session: _liveSession());
      await harness.pump(tester);
      await _scrollTo(tester, find.text(SettingsMessages.logOut));
      await tester.tap(find.text(SettingsMessages.logOut));
      await tester.pumpAndSettle();
      await tester.tap(
        find.descendant(
          of: find.byType(AlertDialog),
          matching: find.text(SettingsMessages.logOut),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text(loginMarker), findsOneWidget);
      expect(harness.storage.values, isEmpty);
      // Login replaced the whole stack: Back can't return to Settings.
      expect(find.text(libraryMarker), findsNothing);
    });
  });

  group('bottom bar', () {
    testWidgets('Library goes back to the library', (tester) async {
      await _Harness(session: _liveSession()).pump(tester);
      await tester.tap(find.text('Library'));
      await tester.pumpAndSettle();
      expect(find.text(libraryMarker), findsOneWidget);
      expect(find.byType(SettingsScreen), findsNothing);
    });
  });

  group('rate-limit wording', () {
    test('rounds up to whole minutes, at least one', () {
      const one = 'Too many attempts. Try again in 1 minute.';
      expect(SettingsMessages.rateLimited(0), one);
      expect(SettingsMessages.rateLimited(1), one);
      expect(SettingsMessages.rateLimited(60), one);
      expect(
        SettingsMessages.rateLimited(61),
        'Too many attempts. Try again in 2 minutes.',
      );
      expect(
        SettingsMessages.rateLimited(null),
        'Too many attempts. Try again later.',
      );
    });
  });

  group('F5 header matches Library', () {
    for (final size in const [Size(320, 568), Size(412, 915)]) {
      testWidgets(
        'backdrop logo at left edge, bell top-right at ${size.width.toInt()} dp',
        (tester) async {
          await _Harness(session: _liveSession())
              .pump(tester, logicalSize: size, textScale: 1.0);
          final logo = find.byKey(
            const ValueKey('library-header-backdrop-logo'),
          );
          expect(logo, findsOneWidget);
          expect(tester.getTopLeft(logo).dx, 0);
          expect(find.byType(ScanBell), findsOneWidget);
          expect(
            tester.getTopRight(find.byType(ScanBell)).dx,
            greaterThan(size.width - 40),
          );
          expect(find.byType(LibrarySearchField), findsNothing);
          expect(tester.takeException(), isNull);
        },
      );
    }
  });

  group('NFR-10 layout', () {
    for (final (size, scale) in const [
      (Size(320, 568), 2.0),
      (Size(320, 568), 1.0),
      (Size(412, 915), 2.0),
    ]) {
      testWidgets('no overflow at ${size.width.toInt()} dp, ${scale}x text', (
        tester,
      ) async {
        await _Harness(session: _liveSession())
            .pump(tester, logicalSize: size, textScale: scale);
        expect(tester.takeException(), isNull);
        await _scrollTo(tester, find.text(SettingsMessages.logOut));
        expect(tester.takeException(), isNull);

        final help = find.byTooltip(SettingsMessages.tempoHelpTooltip);
        await _scrollTo(tester, help, up: true);
        await tester.tap(help);
        await tester.pumpAndSettle();
        expect(find.text(SettingsMessages.tempoHelpBody), findsOneWidget);
        expect(tester.takeException(), isNull);
        await tester.tapAt(const Offset(5, 5));
        await tester.pumpAndSettle();

        await _scrollTo(
          tester,
          find.text(SettingsMessages.changePasswordHint),
          up: true,
        );
        await _openChangePassword(tester);
        expect(tester.takeException(), isNull);
      });
    }

    testWidgets(
      'no overflow at 320 dp, 2x text with the error banner and log-out '
      'dialog',
      (tester) async {
        final harness = _Harness(session: _liveSession());
        await harness.pump(
          tester,
          logicalSize: const Size(320, 568),
          textScale: 2.0,
        );
        await _scrollTo(tester, find.text(SettingsMessages.changePasswordHint));
        // The longest banner: it carries a Log in action too.
        harness.api.onChangePassword = () async =>
            throw const AuthSessionExpiredException();
        await _openChangePassword(tester);
        await _fillChangePassword(tester);
        // At 2x text the sheet scrolls; the button starts below the fold.
        await tester.ensureVisible(_submitButton);
        await tester.pumpAndSettle();
        await tester.tap(_submitButton);
        await tester.pumpAndSettle();
        final banner = find.text(SettingsMessages.sessionExpired);
        expect(banner, findsOneWidget);
        await tester.ensureVisible(banner);
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);

        final close = find.byTooltip(PlaybackMessages.close);
        await tester.ensureVisible(close);
        await tester.pumpAndSettle();
        await tester.tap(close);
        await tester.pumpAndSettle();
        expect(find.byType(BottomSheet), findsNothing);

        await _scrollTo(tester, find.text(SettingsMessages.logOut));
        await tester.tap(find.text(SettingsMessages.logOut));
        await tester.pumpAndSettle();
        expect(find.text(SettingsMessages.logOutTitle), findsOneWidget);
        expect(tester.takeException(), isNull);
      },
    );
  });
  group('delete account (F9)', () {
    const throttleKey = 'login_throttle.until.$_email';

    Finder confirmButton() =>
        find.byKey(const ValueKey('delete-account-confirm'));

    Future<void> openDialog(WidgetTester tester) async {
      await _scrollTo(tester, find.text(SettingsMessages.deleteAccount));
      await tester.tap(find.text(SettingsMessages.deleteAccount));
      await tester.pumpAndSettle();
    }

    /// Types [password] and taps through both confirmation steps.
    Future<void> confirmDelete(WidgetTester tester, String password) async {
      await tester.enterText(
        find.descendant(of: _prompt, matching: find.byType(EditableText)),
        password,
      );
      await tester.tap(confirmButton());
      await tester.pumpAndSettle();
      expect(find.text(SettingsMessages.deleteConfirmBody), findsOneWidget);
      await tester.tap(confirmButton());
      await tester.pumpAndSettle();
    }

    testWidgets('says what is lost and sends nothing on the first tap', (
      tester,
    ) async {
      final harness = _Harness(session: _liveSession());
      await harness.pump(tester);
      await openDialog(tester);
      expect(find.text(SettingsMessages.deleteAccountBody), findsOneWidget);
      await tester.enterText(
        find.descendant(of: _prompt, matching: find.byType(EditableText)),
        'pw',
      );
      await tester.tap(confirmButton());
      await tester.pumpAndSettle();
      expect(harness.api.deleteAccountCalls, 0);
      expect(find.text(SettingsMessages.deleteConfirmBody), findsOneWidget);
    });

    testWidgets('cancel keeps the account and the session', (tester) async {
      final harness = _Harness(session: _liveSession());
      await harness.pump(tester);
      await openDialog(tester);
      await tester.tap(_promptButton(SettingsMessages.cancel));
      await tester.pumpAndSettle();
      expect(_prompt, findsNothing);
      expect(harness.api.deleteAccountCalls, 0);
      expect(find.text(loginMarker), findsNothing);
      expect(harness.storage.values['session_token'], _token);
    });

    testWidgets('wrong password says so and keeps account and session', (
      tester,
    ) async {
      final harness = _Harness(
        session: _liveSession(),
        prefs: {throttleKey: 1},
      );
      harness.api.onDeleteAccount = () async =>
          throw const CurrentPasswordIncorrectException();
      await harness.pump(tester);
      await openDialog(tester);
      await confirmDelete(tester, 'wrong');
      expect(find.text(SettingsMessages.wrongPassword), findsOneWidget);
      expect(find.text(loginMarker), findsNothing);
      expect(harness.storage.values['session_token'], _token);
      // Not a login failure: the login wait is untouched.
      expect((await SharedPreferences.getInstance()).getInt(throttleKey), 1);
    });

    testWidgets('network failure keeps the account and the session', (
      tester,
    ) async {
      final harness = _Harness(session: _liveSession());
      harness.api.onDeleteAccount = () async =>
          throw const AuthNetworkException();
      await harness.pump(tester);
      await openDialog(tester);
      await confirmDelete(tester, 'pw');
      expect(find.text(AuthMessages.network), findsOneWidget);
      expect(find.text(loginMarker), findsNothing);
      expect(harness.storage.values['session_token'], _token);
    });

    testWidgets('success wipes local data and goes to Login', (tester) async {
      final harness = _Harness(
        session: _liveSession(),
        prefs: {throttleKey: 1, 'work_owner_v1': 7},
      );
      harness.api.onDeleteAccount = () async {};
      await harness.pump(tester);
      await openDialog(tester);
      await confirmDelete(tester, 'RightPassw0rd!');
      expect(harness.api.deleteAccountCalls, 1);
      expect(harness.api.lastToken, _token);
      expect(harness.api.lastDeletePassword, 'RightPassw0rd!');
      expect(find.text(loginMarker), findsOneWidget);
      expect(harness.storage.values, isEmpty);
      final prefs = await SharedPreferences.getInstance();
      expect(
        prefs.getKeys().where((k) => k.startsWith('login_throttle')),
        isEmpty,
      );
      expect(prefs.getInt('work_owner_v1'), isNull);
      expect(harness.resultsStore.deleteAllCalls, 1);
    });

    for (final scale in const [1.0, 2.0]) {
      testWidgets('no overflow at 320 dp, ${scale}x text incl. dialog', (
        tester,
      ) async {
        final harness = _Harness(session: _liveSession());
        harness.api.onDeleteAccount = () async =>
            throw const AuthNetworkException();
        await harness.pump(
          tester,
          logicalSize: const Size(320, 568),
          textScale: scale,
        );
        await _scrollTo(tester, find.text(SettingsMessages.deleteAccount));
        expect(tester.takeException(), isNull);
        await openDialog(tester);
        expect(tester.takeException(), isNull);
        await confirmDelete(tester, 'pw');
        expect(find.text(AuthMessages.network), findsOneWidget);
        expect(tester.takeException(), isNull);
        // The last-confirmation step is the other dialog layout.
        await tester.enterText(
          find.descendant(of: _prompt, matching: find.byType(EditableText)),
          'pw',
        );
        await tester.tap(confirmButton());
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
      });
    }
  });
}
