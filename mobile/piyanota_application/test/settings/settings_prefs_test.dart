import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:piyanota_application/models/score_details.dart';
import 'package:piyanota_application/models/voice_part.dart';
import 'package:piyanota_application/services/onboarding_prefs_service.dart';
import 'package:piyanota_application/services/settings_prefs_service.dart';
import 'package:piyanota_application/state/settings_providers.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('default tempo (PIYA-212 AC8)', () {
    test('defaults to 90 when never set', () async {
      expect(
        await SettingsPrefsService().getDefaultTempo(),
        ScoreDetails.defaultTempo,
      );
    });

    test('persists across service instances', () async {
      await SettingsPrefsService().setDefaultTempo(72);
      expect(await SettingsPrefsService().getDefaultTempo(), 72);
    });

    test('writes are clamped to 30–240', () async {
      final prefs = SettingsPrefsService();
      await prefs.setDefaultTempo(29);
      expect(await prefs.getDefaultTempo(), ScoreDetails.minTempo);
      await prefs.setDefaultTempo(241);
      expect(await prefs.getDefaultTempo(), ScoreDetails.maxTempo);
    });

    test('an out-of-range stored value is clamped on read', () async {
      SharedPreferences.setMockInitialValues({
        SettingsPrefsService.defaultTempoKey: 500,
      });
      expect(
        await SettingsPrefsService().getDefaultTempo(),
        ScoreDetails.maxTempo,
      );
    });
  });

  group('default voice (PIYA-212 AC7)', () {
    test('the Settings setter is the pref onboarding writes', () async {
      final prefs = OnboardingPrefsService();
      await prefs.completeOnboarding(defaultVoice: VoicePart.alto);
      await prefs.setDefaultVoicePart(VoicePart.bass);
      expect(
        await OnboardingPrefsService().getDefaultVoicePart(),
        VoicePart.bass,
      );
    });

    test('setting a voice does not mark onboarding complete', () async {
      final prefs = OnboardingPrefsService();
      await prefs.setDefaultVoicePart(VoicePart.tenor);
      expect(await prefs.isOnboardingCompleted(), isFalse);
    });
  });

  group('app version (PIYA-212 AC2)', () {
    test('shows version and build number', () {
      expect(formatAppVersion('1.0.0', '1'), '1.0.0 (1)');
    });

    test('an empty build number is left out', () {
      expect(formatAppVersion('1.0.0', ''), '1.0.0');
    });
  });
}
