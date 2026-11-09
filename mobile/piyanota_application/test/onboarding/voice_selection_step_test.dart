import 'dart:ui' show Tristate;

import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:piyanota_application/routes/app_routes.dart';
import 'package:piyanota_application/screens/onboarding/onboarding_flow_screen.dart';
import 'package:piyanota_application/screens/onboarding/steps/voice_selection_step.dart';
import 'package:piyanota_application/services/onboarding_prefs_service.dart';

const _conductorLabel = "I'm a Conductor / I'm not sure yet";

/// The step marks each option with Semantics(selected: ...), so the test
/// reads the same flag a screen reader would.
bool _isSelected(WidgetTester tester, String label) => tester
    .widgetList<Semantics>(
      find.ancestor(of: find.text(label), matching: find.byType(Semantics)),
    )
    .any((s) => s.properties.selected ?? false);

Future<void> _tap(WidgetTester tester, String label) async {
  await tester.tap(find.text(label));
  await tester.pump();
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('VoiceSelectionStep conductor option (PIYA-201-V2.1)', () {
    Future<void> pumpStep(WidgetTester tester) async {
      tester.view.physicalSize = const Size(1236, 2400);
      tester.view.devicePixelRatio = 3;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(
        const ProviderScope(
          child: MaterialApp(home: Scaffold(body: VoiceSelectionStep())),
        ),
      );
    }

    testWidgets('conductor shows selected, the four voices do not', (
      tester,
    ) async {
      await pumpStep(tester);
      await _tap(tester, _conductorLabel);

      expect(_isSelected(tester, _conductorLabel), isTrue);
      for (final v in ['Soprano', 'Alto', 'Tenor', 'Bass']) {
        expect(_isSelected(tester, v), isFalse, reason: v);
      }
    });

    testWidgets(
      'every option is a labelled, tappable button for screen readers',
      (tester) async {
        final handle = tester.ensureSemantics();
        try {
          await pumpStep(tester);
          await _tap(tester, 'Alto');

          for (final label in [
            'Soprano',
            'Alto',
            'Tenor',
            'Bass',
            _conductorLabel,
          ]) {
            final data = tester
                .getSemantics(find.text(label))
                .getSemanticsData();
            expect(data.label, label, reason: label);
            expect(data.hasAction(SemanticsAction.tap), isTrue, reason: label);
            expect(
              data.flagsCollection.isButton,
              isTrue,
              reason: '$label button',
            );
            expect(
              data.flagsCollection.isSelected == Tristate.isTrue,
              label == 'Alto',
              reason: '$label selected',
            );
          }
        } finally {
          handle.dispose();
        }
      },
    );

    testWidgets('picking Soprano afterwards moves the selection', (
      tester,
    ) async {
      await pumpStep(tester);
      await _tap(tester, _conductorLabel);
      await _tap(tester, 'Soprano');

      expect(_isSelected(tester, 'Soprano'), isTrue);
      expect(_isSelected(tester, _conductorLabel), isFalse);

      await _tap(tester, _conductorLabel);
      expect(_isSelected(tester, _conductorLabel), isTrue);
      expect(_isSelected(tester, 'Soprano'), isFalse);
    });
  });

  testWidgets('Get Started with conductor saves "all voices" (null)', (
    tester,
  ) async {
    await tester.pumpWidget(
      ProviderScope(
        child: MaterialApp(
          home: const OnboardingFlowScreen(),
          routes: {AppRoutes.signUp: (_) => const Text('signup-stub')},
        ),
      ),
    );
    await tester.pump();
    await _tap(tester, 'Next');
    await tester.pump(const Duration(milliseconds: 400));
    await _tap(tester, 'Next');
    await tester.pump(const Duration(milliseconds: 400));

    await _tap(tester, _conductorLabel);
    // Tapping must not leave the step.
    expect(find.text('Get Started'), findsOneWidget);
    expect(find.text('signup-stub'), findsNothing);

    await _tap(tester, 'Get Started');
    await tester.pumpAndSettle();

    final prefs = OnboardingPrefsService();
    expect(await prefs.isOnboardingCompleted(), isTrue);
    expect(await prefs.getDefaultVoicePart(), isNull);
    expect(find.text('signup-stub'), findsOneWidget);
  });
}
