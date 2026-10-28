import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:piyanota_application/app.dart';
import 'package:piyanota_application/routes/app_routes.dart';
import 'package:piyanota_application/screens/auth/login_screen.dart';
import 'package:piyanota_application/screens/library/library_messages.dart';
import 'package:piyanota_application/screens/library/score_library_screen.dart';
import 'package:piyanota_application/screens/library/widgets/score_cards.dart';
import 'package:piyanota_application/screens/onboarding/widgets/splash_overlay.dart';
import 'package:piyanota_application/screens/settings/settings_messages.dart';
import 'package:piyanota_application/screens/settings/settings_screen.dart';
import 'package:piyanota_application/services/fake_auth_api.dart';
import 'package:piyanota_application/services/fake_score_library_api.dart';
import 'package:piyanota_application/state/auth_providers.dart';
import 'package:piyanota_application/state/playback_providers.dart';
import 'package:piyanota_application/state/processing_providers.dart';
import 'package:piyanota_application/state/scan_job_store.dart';
import 'package:piyanota_application/state/score_library_providers.dart';
import 'package:piyanota_application/state/work_owner.dart';

import '../playback/playback_fakes.dart';

/// PIYA-205-V2.3: after a logout of the demo account, the next account's
/// library never shows a demo score, not even for one frame.
void main() {
  const settle = Duration(seconds: 2);
  const frame = Duration(milliseconds: 16);
  const newEmail = 'fresh@example.com';
  const newPassword = 'brand new 7';

  /// Starts signed in as the demo account (a stored earlier-run token),
  /// with the demo scores on screen.
  Future<void> launchAsDemo(WidgetTester tester) async {
    SharedPreferences.setMockInitialValues({'onboarding_completed': true});
    FlutterSecureStorage.setMockInitialValues({
      'session_token': 'fake_sess_1_0_${FakeAuthApi.demoEmail}',
      'session_expires_at': DateTime.now()
          .toUtc()
          .add(const Duration(days: 30))
          .toIso8601String(),
      'session_email': FakeAuthApi.demoEmail,
    });
    tester.view.physicalSize = const Size(1080, 2340);
    tester.view.devicePixelRatio = 2.75;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          fakeAuthApiProvider.overrideWithValue(FakeAuthApi()),
          playbackEngineFactoryProvider.overrideWithValue(
            FakePlaybackEngine.new,
          ),
        ],
        child: const PiyaNotaApp(),
      ),
    );
    await tester.pump();
    await tester.pump(splashIntroDuration);
    await tester.pump(FakeScoreLibraryApi.defaultLatency + settle);
    expect(find.text('6 Scores • Tap to Listen'), findsOneWidget);
  }

  Future<void> logOut(WidgetTester tester) async {
    tester
        .state<NavigatorState>(find.byType(Navigator))
        .pushNamed(AppRoutes.settings);
    await tester.pumpAndSettle();
    final logOutRow = find.text(SettingsMessages.logOut);
    await tester.dragUntilVisible(
      logOutRow,
      find
          .descendant(
            of: find.byType(SettingsScreen),
            matching: find.byType(Scrollable),
          )
          .first,
      const Offset(0, -120),
    );
    await Scrollable.ensureVisible(tester.element(logOutRow), alignment: 0.5);
    await tester.pumpAndSettle();
    await tester.tap(logOutRow);
    await tester.pump();
    await tester.pump(settle);
    await tester.tap(
      find.descendant(
        of: find.byType(AlertDialog),
        matching: find.text(SettingsMessages.logOut),
      ),
    );
    await tester.pump();
    await tester.pump(settle);
    expect(find.byType(LoginScreen), findsOneWidget);
  }

  Future<void> fillAndTap(
    WidgetTester tester,
    List<String> fields,
    String button,
  ) async {
    for (var i = 0; i < fields.length; i++) {
      await tester.enterText(find.byType(TextFormField).at(i), fields[i]);
    }
    await tester.pump();
    final submit = find.widgetWithText(ElevatedButton, button);
    await tester.ensureVisible(submit);
    await tester.tap(submit);
  }

  /// Steps frame by frame until the Library has loaded, failing on any
  /// frame that builds a previous account's card (a score or a scan).
  /// [eachFrame] adds a per-frame check. Returns once the time is up.
  Future<void> expectNoDemoScoreUntilLoaded(
    WidgetTester tester, {
    void Function(Duration t)? eachFrame,
  }) async {
    var sawLoading = false;
    final end = FakeScoreLibraryApi.defaultLatency + settle;
    for (var t = Duration.zero; t < end; t += frame) {
      await tester.pump(frame);
      expect(
        find.byType(ScoreCard),
        findsNothing,
        reason: 'a previous account\'s score card was built at $t',
      );
      expect(
        find.byType(ScanningScoreCard),
        findsNothing,
        reason: 'a previous account\'s scan card was built at $t',
      );
      eachFrame?.call(t);
      if (find.byType(ScoreLibraryScreen).evaluate().isNotEmpty &&
          find.text(LibraryMessages.loadingSubtitle).evaluate().isNotEmpty) {
        sawLoading = true;
      }
    }
    expect(sawLoading, isTrue, reason: 'the loading state never showed');
  }

  testWidgets('sign-up after a demo logout goes from loading straight to the '
      'empty state', (tester) async {
    await launchAsDemo(tester);
    await logOut(tester);

    await tester.tap(find.text('Sign Up'));
    await tester.pumpAndSettle();
    await fillAndTap(tester, [
      newEmail,
      newPassword,
      newPassword,
    ], 'Create Account');

    await expectNoDemoScoreUntilLoaded(tester);
    expect(find.text(LibraryMessages.emptySubtitle), findsOneWidget);
  });

  testWidgets('login as another account after a demo logout never shows a '
      'demo score', (tester) async {
    await launchAsDemo(tester);
    await logOut(tester);

    // Register the second account, then come back to Login as that user
    // would on another day.
    await tester.tap(find.text('Sign Up'));
    await tester.pumpAndSettle();
    await fillAndTap(tester, [
      newEmail,
      newPassword,
      newPassword,
    ], 'Create Account');
    await tester.pump(FakeScoreLibraryApi.defaultLatency + settle);
    await logOut(tester);
    // Back on the demo, so the provider last held demo scores.
    await fillAndTap(tester, [
      FakeAuthApi.demoEmail,
      FakeAuthApi.demoPassword,
    ], 'Log In');
    await tester.pump();
    await tester.pump(settle);
    await tester.pump(FakeScoreLibraryApi.defaultLatency + settle);
    expect(find.text('6 Scores • Tap to Listen'), findsOneWidget);
    await logOut(tester);

    await fillAndTap(tester, [newEmail, newPassword], 'Log In');
    await expectNoDemoScoreUntilLoaded(tester);
    expect(find.text(LibraryMessages.emptySubtitle), findsOneWidget);
  });

  testWidgets('sign-up on a phone an earlier demo run left behind shows none '
      'of the demo account scans', (tester) async {
    // What an earlier run leaves when it ends without a logout (app killed,
    // then the session expired): the demo's owner id (its first fake
    // userId) and a running scan, but no usable session.
    SharedPreferences.setMockInitialValues({
      'onboarding_completed': true,
      WorkOwnerStore.storageKey: 1,
      ScanJobStore.storageKey: jsonEncode([
        {'jobId': 'job-demo', 'title': 'Bahay Kubo', 'phase': 'active'},
      ]),
    });
    FlutterSecureStorage.setMockInitialValues({});
    tester.view.physicalSize = const Size(1080, 2340);
    tester.view.devicePixelRatio = 2.75;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          fakeAuthApiProvider.overrideWithValue(FakeAuthApi()),
          playbackEngineFactoryProvider.overrideWithValue(
            FakePlaybackEngine.new,
          ),
        ],
        child: const PiyaNotaApp(),
      ),
    );
    await tester.pump();
    await tester.pump(splashIntroDuration);
    await tester.pump(settle);
    expect(find.byType(LoginScreen), findsOneWidget);

    await tester.tap(find.text('Sign Up'));
    await tester.pumpAndSettle();
    await fillAndTap(tester, [
      newEmail,
      newPassword,
      newPassword,
    ], 'Create Account');

    // The tracker assert below carries the repro (it was RED before the
    // fake ids were made unique across runs); the widget checks are only a
    // guard, since the fake drops the unknown job before the list loads.
    final container = ProviderScope.containerOf(
      tester.element(find.byType(Navigator)),
    );
    await expectNoDemoScoreUntilLoaded(
      tester,
      eachFrame: (t) => expect(
        container.read(processingJobsProvider).keys,
        isNot(contains('job-demo')),
        reason: 'the demo account scan was kept for the new account at $t',
      ),
    );
    expect(find.text(LibraryMessages.emptySubtitle), findsOneWidget);
  });

  // A stored session with onboarding not done (onboarding flag lost, token
  // kept). Finishing onboarding is the user choosing Sign Up or Login, not
  // a cold start, so the old session must not restore underneath it. Fast
  // fakes, so a Library mounted under the route would show its cards.
  for (final (label, toSignUp) in [
    ('Get Started', ['Next', 'Next', 'Get Started']),
    ('Skip', ['Skip', 'Sign Up']),
  ]) {
    testWidgets('finishing onboarding via $label never mounts the stored '
        'session Library before sign-up', (tester) async {
      const fast = Duration(milliseconds: 20);
      SharedPreferences.setMockInitialValues({});
      FlutterSecureStorage.setMockInitialValues({
        'session_token': 'fake_sess_1_0_${FakeAuthApi.demoEmail}',
        'session_expires_at': DateTime.now()
            .toUtc()
            .add(const Duration(days: 30))
            .toIso8601String(),
        'session_email': FakeAuthApi.demoEmail,
      });
      tester.view.physicalSize = const Size(1080, 2340);
      tester.view.devicePixelRatio = 2.75;
      addTearDown(tester.view.reset);
      final auth = FakeAuthApi(latency: fast);
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            fakeAuthApiProvider.overrideWithValue(auth),
            scoreLibraryApiProvider.overrideWith(
              (ref) => FakeScoreLibraryApi(
                sessionStorage: ref.watch(sessionStorageProvider),
                accountForToken: auth.accountForToken,
                latency: fast,
              ),
            ),
            playbackEngineFactoryProvider.overrideWithValue(
              FakePlaybackEngine.new,
            ),
          ],
          child: const PiyaNotaApp(),
        ),
      );

      var signedUp = false;
      Future<void> frames(Duration d) async {
        for (var t = Duration.zero; t < d; t += frame) {
          await tester.pump(frame);
          expect(
            find.byType(ScoreCard, skipOffstage: false),
            findsNothing,
            reason: 'a demo score card was built ($label, $t)',
          );
          if (signedUp) continue;
          expect(
            find.byType(ScoreLibraryScreen, skipOffstage: false),
            findsNothing,
            reason: 'a Library mounted before sign-up ($label, $t)',
          );
        }
      }

      await frames(splashIntroDuration + settle);
      for (final button in toSignUp) {
        await tester.tap(find.text(button));
        await frames(settle);
      }
      for (var i = 0; i < 3; i++) {
        await tester.enterText(
          find.byType(TextFormField).at(i),
          [newEmail, newPassword, newPassword][i],
        );
        await frames(frame);
      }
      final submit = find.widgetWithText(ElevatedButton, 'Create Account');
      await tester.ensureVisible(submit);
      await frames(frame);
      await tester.tap(submit);
      // From here the Library may mount: it is the new account's, empty.
      signedUp = true;
      await frames(settle);
      expect(find.text(LibraryMessages.emptySubtitle), findsOneWidget);
    });
  }
}
