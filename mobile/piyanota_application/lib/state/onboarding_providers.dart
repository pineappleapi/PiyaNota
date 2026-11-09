import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/voice_part.dart';
import '../services/onboarding_prefs_service.dart';

final onboardingPrefsServiceProvider = Provider<OnboardingPrefsService>((ref) {
  return OnboardingPrefsService();
});

/// Drives the app-entry routing decision (PIYA-201 AC1): whether onboarding
/// has already been completed/skipped on a prior launch.
final onboardingCompletedProvider = FutureProvider<bool>((ref) {
  return ref.watch(onboardingPrefsServiceProvider).isOnboardingCompleted();
});

/// In-flow voice-part selection on the final onboarding step, before it's
/// persisted via [OnboardingPrefsService.completeOnboarding]. Riverpod 3
/// dropped the legacy `StateProvider`, so this is a minimal hand-written
/// `Notifier` standing in for it — still supports `.notifier.state = x`.
class SelectedVoicePart extends Notifier<VoicePart?> {
  @override
  VoicePart? build() => null;

  void select(VoicePart part) => state = part;

  void clear() => state = null;
}

final selectedVoicePartProvider =
    NotifierProvider<SelectedVoicePart, VoicePart?>(SelectedVoicePart.new);

/// PIYA-201-V2.1: "I'm a Conductor / I'm not sure yet" is a fifth choice on
/// the voice step. It is kept apart from [selectedVoicePartProvider] because
/// it must not be a [VoicePart]; the step keeps the two mutually exclusive.
/// Saving it means no default voice, i.e. all voices.
class ConductorSelected extends Notifier<bool> {
  @override
  bool build() => false;

  void set(bool value) => state = value;
}

final conductorSelectedProvider = NotifierProvider<ConductorSelected, bool>(
  ConductorSelected.new,
);
