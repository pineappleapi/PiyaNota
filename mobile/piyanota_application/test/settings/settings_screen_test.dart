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
import 'package:piyanota_application/screens/settings/settings_messages.dart';
import 'package:piyanota_application/screens/settings/settings_screen.dart';
import 'package:piyanota_application/services/auth_api.dart';
import 'package:piyanota_application/services/onboarding_prefs_service.dart';
import 'package:piyanota_application/services/session_storage.dart';
import 'package:piyanota_application/services/settings_prefs_service.dart';
import 'package:piyanota_application/state/auth_providers.dart';
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
          sessionStorageProvider.overrideWithValue(sessionStorage),
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

  group('default tempo (AC8)', () {
    testWidgets('starts at 90 and steps by one, saving each step', (
      tester,
    ) async {
      await _Harness(session: _liveSession()).pump(tester);
      await _scrollTo(tester, _tempoValue);
      expect(find.text(SettingsMessages.tempoValue(90)), findsOneWidget);

      await tester.tap(find.byIcon(Icons.add_rounded));
      await tester.pumpAndSettle();
      expect(find.text(SettingsMessages.tempoValue(91)), findsOneWidget);
      expect(await SettingsPrefsService().getDefaultTempo(), 91);

      await tester.tap(find.byIcon(Icons.remove_rounded));
      await tester.tap(find.byIcon(Icons.remove_rounded));
      await tester.pumpAndSettle();
      expect(await SettingsPrefsService().getDefaultTempo(), 89);
    });

    testWidgets('holding + repeats, and stops at 240', (tester) async {
      await _Harness(
        session: _liveSession(),
        prefs: {SettingsPrefsService.defaultTempoKey: 236},
      ).pump(tester);
      await _scrollTo(tester, _tempoValue);
      final gesture = await tester.startGesture(
        tester.getCenter(find.byIcon(Icons.add_rounded)),
      );
      await tester.pump(const Duration(seconds: 2));
      await gesture.up();
      await tester.pumpAndSettle();
      expect(find.text(SettingsMessages.tempoValue(240)), findsOneWidget);
      expect(
        await SettingsPrefsService().getDefaultTempo(),
        ScoreDetails.maxTempo,
      );
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

    testWidgets('a 401 marks the current-password field', (tester) async {
      final harness = _Harness(session: _liveSession());
      harness.api.onChangePassword = () async =>
          throw const InvalidCredentialsException();
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
  });
}
