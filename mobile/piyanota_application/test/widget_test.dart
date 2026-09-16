import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:piyanota_application/app.dart';

void main() {
  testWidgets('First launch shows onboarding, ending on Skip (PIYA-201 AC1/AC4)',
      (WidgetTester tester) async {
    SharedPreferences.setMockInitialValues({});

    await tester.pumpWidget(const ProviderScope(child: PiyaNotaApp()));
    await tester.pump(); // resolve onboardingCompletedProvider
    await tester.pump(const Duration(milliseconds: 2500)); // splash animation
    await tester.pump(const Duration(milliseconds: 500)); // post-splash delay

    expect(find.text('Skip'), findsOneWidget);
  });
}
