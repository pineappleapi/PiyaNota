import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:piyanota_application/app.dart';
import 'package:piyanota_application/screens/auth/login_screen.dart';
import 'package:piyanota_application/screens/onboarding/onboarding_flow_screen.dart';
import 'package:piyanota_application/screens/onboarding/widgets/splash_overlay.dart';
import 'package:piyanota_application/services/leaving_app.dart';
import 'package:piyanota_application/splash_gate.dart';

/// PIYA-201-V2.2: the splash plays on every cold start and warm resume,
/// except when the app itself sent the user out.
void main() {
  setUp(resetLeavingApp);

  final splash = find.byType(SplashOverlay);
  const logo = AssetImage('assets/branding/Piyanota_App_Logo.png');

  /// Same lifecycle walk the engine reports when Android backgrounds the
  /// app and brings it back.
  void background(WidgetTester tester) {
    for (final state in [
      AppLifecycleState.inactive,
      AppLifecycleState.hidden,
      AppLifecycleState.paused,
    ]) {
      tester.binding.handleAppLifecycleStateChanged(state);
    }
  }

  void foreground(WidgetTester tester) {
    for (final state in [
      AppLifecycleState.hidden,
      AppLifecycleState.inactive,
      AppLifecycleState.resumed,
    ]) {
      tester.binding.handleAppLifecycleStateChanged(state);
    }
  }

  /// A screen under the gate the way PiyaNotaApp mounts it: the gate
  /// wraps MaterialApp, so it is above the Navigator.
  Future<void> pumpGated(WidgetTester tester, {VoidCallback? onTap}) async {
    await tester.pumpWidget(
      SplashGate(
        child: MaterialApp(
          home: Scaffold(
            body: Column(
              children: [
                const TextField(),
                ElevatedButton(onPressed: onTap, child: const Text('Tap me')),
              ],
            ),
          ),
        ),
      ),
    );
  }

  /// The splash's clock starts on the first frame after it mounts, so one
  /// bare pump first, then exactly one splash length.
  Future<void> pumpPastSplash(WidgetTester tester) async {
    await tester.pump();
    await tester.pump(splashIntroDuration);
    await tester.pump();
  }

  testWidgets('AC1: cold start shows the splash, then the routed screen', (
    tester,
  ) async {
    SharedPreferences.setMockInitialValues({'onboarding_completed': true});
    // No stored session, so the routed screen is Login (PIYA-202-V2.2).
    FlutterSecureStorage.setMockInitialValues({});
    await tester.pumpWidget(const ProviderScope(child: PiyaNotaApp()));
    await tester.pump(); // resolve onboardingCompletedProvider

    expect(splash, findsOneWidget);

    await pumpPastSplash(tester);

    expect(splash, findsNothing);
    expect(find.byType(LoginScreen), findsOneWidget);
  });

  testWidgets('AC2: resume after paused plays the splash over the same '
      'screen and keeps its state', (tester) async {
    await pumpGated(tester);
    await pumpPastSplash(tester);
    await tester.enterText(find.byType(TextField), 'Bahay Kubo');
    final fieldState = tester.state(find.byType(EditableText));

    background(tester);
    foreground(tester);
    await tester.pump();

    expect(splash, findsOneWidget);

    await pumpPastSplash(tester);

    expect(splash, findsNothing);
    expect(find.text('Bahay Kubo'), findsOneWidget);
    // Same State object: the screen was covered, never rebuilt from scratch.
    expect(tester.state(find.byType(EditableText)), same(fieldState));
  });

  testWidgets('AC2 ruling: inactive alone (a system sheet) does not replay', (
    tester,
  ) async {
    await pumpGated(tester);
    await pumpPastSplash(tester);

    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pump();

    expect(splash, findsNothing);
  });

  testWidgets('AC3: a resume inside withoutSplash shows no splash', (
    tester,
  ) async {
    await pumpGated(tester);
    await pumpPastSplash(tester);

    final picker = Completer<String>();
    final picked = withoutSplash(() => picker.future);
    background(tester);
    foreground(tester);
    picker.complete('page.jpg');
    expect(await picked, 'page.jpg');
    await tester.pump();

    expect(splash, findsNothing);

    // Leaving the app on its own afterwards still replays it.
    background(tester);
    foreground(tester);
    await tester.pump();
    expect(splash, findsOneWidget);
  });

  testWidgets('AC3: the picker result arriving before resumed still skips', (
    tester,
  ) async {
    await pumpGated(tester);
    await pumpPastSplash(tester);

    final picker = Completer<void>();
    final picked = withoutSplash(() => picker.future);
    background(tester);
    picker.complete();
    await picked;
    foreground(tester);
    await tester.pump();

    expect(splash, findsNothing);
  });

  testWidgets('AC3: a fire-and-forget launch (returns before paused) '
      'still skips', (tester) async {
    await pumpGated(tester);
    await pumpPastSplash(tester);

    // openAppSettings / openFolder: startActivity, then the future ends.
    expect(await withoutSplash(() async => true), isTrue);
    background(tester);
    foreground(tester);
    await tester.pump();

    expect(splash, findsNothing);
  });

  testWidgets('AC3: a launch that opened nothing (false) leaves the next '
      'real background replaying', (tester) async {
    await pumpGated(tester);
    await pumpPastSplash(tester);

    expect(await withoutSplash(() async => false), isFalse);
    background(tester);
    foreground(tester);
    await tester.pump();

    expect(splash, findsOneWidget);
  });

  testWidgets('AC3: a launch that never paused the app stops counting after '
      'leaveAppGrace', (tester) async {
    await pumpGated(tester);
    await pumpPastSplash(tester);

    await withoutSplash(() async => true);
    await tester.pump(leaveAppGrace);
    background(tester);
    foreground(tester);
    await tester.pump();

    expect(splash, findsOneWidget);
  });

  testWidgets('AC2: Android back during the splash does not pop the screen '
      'beneath it', (tester) async {
    await pumpGated(tester);
    await pumpPastSplash(tester);
    final navigator = tester.state<NavigatorState>(find.byType(Navigator));
    navigator.push(
      MaterialPageRoute<void>(
        builder: (_) => const Scaffold(body: Text('Pushed page')),
      ),
    );
    await tester.pumpAndSettle();

    background(tester);
    foreground(tester);
    await tester.pump();
    expect(splash, findsOneWidget);

    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    expect(find.text('Pushed page'), findsOneWidget);
    expect(splash, findsNothing); // pumpAndSettle ran it out

    // Once the splash is gone, back works again.
    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    expect(find.text('Pushed page'), findsNothing);
  });

  testWidgets('AC4: lasts no longer than the onboarding intro and a tap '
      'does not skip it', (tester) async {
    expect(splashIntroDuration, const Duration(milliseconds: 4600));
    var taps = 0;
    await pumpGated(tester, onTap: () => taps++);
    await tester.pump(); // splash clock starts here

    await tester.pump(const Duration(milliseconds: 500));
    await tester.tap(find.text('Tap me'), warnIfMissed: false);
    await tester.pump();

    expect(splash, findsOneWidget);
    expect(taps, 0);

    await tester.pump(splashIntroDuration - const Duration(milliseconds: 600));
    expect(splash, findsOneWidget);

    await tester.pump(const Duration(milliseconds: 100));
    await tester.pump();
    expect(splash, findsNothing);

    await tester.tap(find.text('Tap me'));
    expect(taps, 1);
  });

  testWidgets('AC5: first launch plays the splash once, then onboarding '
      'without a second intro', (tester) async {
    SharedPreferences.setMockInitialValues({});
    await tester.pumpWidget(const ProviderScope(child: PiyaNotaApp()));
    await tester.pump();

    expect(splash, findsOneWidget);

    await pumpPastSplash(tester);

    expect(splash, findsNothing);
    expect(find.byType(OnboardingFlowScreen), findsOneWidget);
    expect(find.text('Skip'), findsOneWidget);
    // Onboarding no longer carries its own copy of the logo intro.
    expect(find.image(logo), findsNothing);

    await tester.pump(splashIntroDuration);
    expect(splash, findsNothing);
    expect(find.image(logo), findsNothing);
  });
}
