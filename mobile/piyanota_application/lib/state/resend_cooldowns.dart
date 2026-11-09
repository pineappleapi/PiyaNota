import 'package:flutter_riverpod/flutter_riverpod.dart';

/// PIYA-204-V2.2: the resend countdown belongs to the email address, not to
/// the screen, so going back and resubmitting the same email can't restart it.
const int resendCooldownSeconds = 30;

/// Tests override this to move time without waiting.
final resendClockProvider = Provider<DateTime Function()>(
  (ref) => DateTime.now,
);

/// When a reset code was last sent to each email (trimmed, lowercase).
/// Kept alive for the app session only (V2.2 AC3); not persisted.
final resendCooldownsProvider =
    NotifierProvider<ResendCooldowns, Map<String, DateTime>>(
      ResendCooldowns.new,
    );

class ResendCooldowns extends Notifier<Map<String, DateTime>> {
  @override
  Map<String, DateTime> build() => {};

  static String _key(String email) => email.trim().toLowerCase();

  void recordSent(String email) =>
      state = {...state, _key(email): ref.read(resendClockProvider)()};

  void clear(String email) => state = {...state}..remove(_key(email));

  /// Recomputed from the stored send time on each call, so a countdown
  /// that was suspended in the background is not stale when it resumes.
  int secondsLeft(String email) {
    final sentAt = state[_key(email)];
    if (sentAt == null) return 0;
    final left = sentAt
        .add(const Duration(seconds: resendCooldownSeconds))
        .difference(ref.read(resendClockProvider)());
    if (left <= Duration.zero) return 0;
    return (left.inMilliseconds + 999) ~/ 1000;
  }
}
