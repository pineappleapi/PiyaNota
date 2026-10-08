import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:piyanota_application/app.dart';
import 'package:piyanota_application/services/fake_auth_api.dart';
import 'package:piyanota_application/services/fake_score_library_api.dart';
import 'package:piyanota_application/state/auth_providers.dart';

/// Full app with the real fakes: logging in lands on the real library, the
/// demo account sees its scores, and back does not return to Login.
void main() {
  // The fakes' latency runs on the fake test clock, so these generous pumps
  // cost nothing in wall time.
  const settle = Duration(seconds: 2);

  Future<void> pumpApp(WidgetTester tester) async {
    SharedPreferences.setMockInitialValues({'onboarding_completed': true});
    FlutterSecureStorage.setMockInitialValues({});
    tester.view.physicalSize = const Size(1080, 2340);
    tester.view.devicePixelRatio = 2.75;
    addTearDown(tester.view.reset);

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          fakeAuthApiProvider.overrideWithValue(
            FakeAuthApi(latency: Duration.zero),
          ),
        ],
        child: const PiyaNotaApp(),
      ),
    );
    await tester.pump();
    await tester.pump(settle);
  }

  testWidgets('demo login lands on the library with the demo scores', (
    tester,
  ) async {
    await pumpApp(tester);

    await tester.enterText(
      find.byType(TextFormField).at(0),
      FakeAuthApi.demoEmail,
    );
    await tester.enterText(
      find.byType(TextFormField).at(1),
      FakeAuthApi.demoPassword,
    );
    // Rebuild so Log In enables (PIYA-202 AC1) before tapping it.
    await tester.pump();
    final logIn = find.widgetWithText(ElevatedButton, 'Log In');
    await tester.ensureVisible(logIn);
    await tester.tap(logIn);
    await tester.pump();
    await tester.pump(settle);
    await tester.pump(FakeScoreLibraryApi.defaultLatency + settle);

    expect(find.text('My Scores'), findsOneWidget);
    expect(find.text('5 Scores • Tap to Listen'), findsOneWidget);
    expect(find.text('Bahay Kubo'), findsOneWidget);

    // Library is the root route: back has nowhere to go but out.
    final navigator = tester.state<NavigatorState>(find.byType(Navigator));
    expect(navigator.canPop(), isFalse);

    // AC7 through the real route table: the placeholder shows the id.
    await tester.tap(find.text('Paraiso'));
    await tester.pump();
    await tester.pump(settle);
    expect(find.text('Playback — coming soon'), findsOneWidget);
    expect(find.text('Paraiso (score #102)'), findsOneWidget);
  });
}
