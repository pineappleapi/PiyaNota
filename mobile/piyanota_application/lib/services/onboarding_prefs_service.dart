import 'package:shared_preferences/shared_preferences.dart';

import '../models/voice_part.dart';

/// Persists onboarding completion + the voice part chosen on PIYA-201's
/// final step (PIYA-201 AC1, AC5). Uses shared_preferences rather than
/// flutter_secure_storage since neither value is a secret — secure storage
/// stays reserved for the session token (FR-21).
class OnboardingPrefsService {
  static const _completedKey = 'onboarding_completed';
  static const _defaultVoiceKey = 'onboarding_default_voice';

  Future<bool> isOnboardingCompleted() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getBool(_completedKey) ?? false;
  }

  Future<void> completeOnboarding({VoicePart? defaultVoice}) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_completedKey, true);
    if (defaultVoice != null) {
      await prefs.setString(_defaultVoiceKey, defaultVoice.name);
    }
  }

  Future<VoicePart?> getDefaultVoicePart() async {
    final prefs = await SharedPreferences.getInstance();
    final stored = prefs.getString(_defaultVoiceKey);
    if (stored == null) return null;
    return VoicePart.values.asNameMap()[stored];
  }
}
