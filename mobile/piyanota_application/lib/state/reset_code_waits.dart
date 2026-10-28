import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../services/backoff.dart';
import 'resend_cooldowns.dart';

/// Wrong reset codes and the wait they earned, per email (trimmed,
/// lowercase). Kept alive for the app session only, like
/// [resendCooldownsProvider]; the server enforces the real limit (AC5).
typedef ResetCodeWait = ({int failures, DateTime? until, DateTime? last});

final resetCodeWaitsProvider =
    NotifierProvider<ResetCodeWaits, Map<String, ResetCodeWait>>(ResetCodeWaits.new);

class ResetCodeWaits extends Notifier<Map<String, ResetCodeWait>> {
  @override
  Map<String, ResetCodeWait> build() => {};

  static String _key(String email) => email.trim().toLowerCase();

  DateTime _now() => ref.read(resendClockProvider)();

  /// The count as of now: a count whose last wrong code is 24 h old is 0.
  int failures(String email) {
    final entry = state[_key(email)];
    if (entry == null) return 0;
    final last = entry.last;
    if (last != null && !_now().isBefore(last.add(wrongCountResetAfter))) {
      return 0;
    }
    return entry.failures;
  }

  /// Counts one wrong code; from the 3rd on, starts the next, longer wait.
  void recordWrong(String email) {
    final count = failures(email) + 1;
    final over = count - resetCodeFreeAttempts;
    state = {
      ...state,
      _key(email): (
        failures: count,
        until: over > 0 ? _now().add(backoffAfter(over)) : null,
        last: _now(),
      ),
    };
  }

  /// The server's 429 wait replaces our own; the count is left alone since
  /// the server, not a wrong code seen here, caused this wait.
  void recordServerWait(String email, Duration wait) => state = {
    ...state,
    _key(email): (
      failures: failures(email),
      until: _now().add(wait),
      last: state[_key(email)]?.last,
    ),
  };

  /// A successful reset or a newly sent code (AC4).
  void reset(String email) => state = {...state}..remove(_key(email));

  /// Recomputed from the stored deadline on each call, so a countdown that
  /// was suspended in the background is not stale when it resumes.
  Duration remaining(String email) {
    final until = state[_key(email)]?.until;
    if (until == null) return Duration.zero;
    final left = until.difference(_now());
    if (left <= Duration.zero) return Duration.zero;
    return Duration(seconds: (left.inMilliseconds / 1000).ceil());
  }
}
